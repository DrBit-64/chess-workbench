"""Prepare a course subtree and send it to the official Lichess Study API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.logic.pgn_export import PgnExportError, export_module_pgn
from chess_workbench.schemas.lichess import (
    LichessChapterPreview,
    LichessStudyPreview,
    LichessStudyResult,
)
from chess_workbench.services.content import ContentService, ServiceError
from chess_workbench.store.models import Course, CourseModule

LICHESS_URL = "https://lichess.org"
MAX_CHAPTERS = 64
MAX_CHAPTER_MOVES = 3_000
MAX_CHAPTER_CHARS = 100_000


@dataclass(frozen=True)
class PreparedStudy:
    preview: LichessStudyPreview
    pgn: str


async def prepare_study(
    session: AsyncSession,
    course_id: UUID,
    module_id: UUID,
    *,
    token_configured: bool,
) -> PreparedStudy:
    course = await session.get(Course, course_id)
    if course is None or course.archived_at is not None:
        raise ServiceError("not_found", 404, "课程不存在")
    modules = list(
        await session.scalars(
            select(CourseModule)
            .where(CourseModule.course_id == course_id, CourseModule.archived_at.is_(None))
            .order_by(CourseModule.sort_order, CourseModule.created_at, CourseModule.id)
        )
    )
    by_id = {module.id: module for module in modules}
    selected = by_id.get(module_id)
    if selected is None:
        raise ServiceError("not_found", 404, "章节不属于当前课程，或已归档")
    # The current course contract allows a chapter and one level of subsections.
    scope = [selected, *(module for module in modules if module.parent_id == selected.id)]
    previews: list[LichessChapterPreview] = []
    skipped: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []
    pgns: list[str] = []
    content = ContentService(session)
    for module in scope:
        parent = by_id.get(module.parent_id) if module.parent_id else None
        path = f"{parent.title} / {module.title}" if parent else module.title
        editor = await content.get_module_editor(course_id, module.id)
        if not editor.occurrences:
            skipped.append(path)
            continue
        roots = [node for node in editor.occurrences if node.parent_id is None]
        if len(roots) != 1:
            raise ServiceError("pgn_not_exportable", 409, f"「{path}」的棋谱起点不唯一")
        root = roots[0]
        name = path if len(path) <= 80 else path[:77] + "..."
        if name != path:
            warnings.append(f"章节标题已缩短：{path}")
        move_count = len(editor.occurrences) - 1
        previews.append(
            LichessChapterPreview(module_id=module.id, name=name, move_count=move_count)
        )
        if move_count > MAX_CHAPTER_MOVES:
            blockers.append(f"「{path}」有 {move_count} 个棋步，超过 Lichess 单章 3000 棋步上限")
            continue
        comments: dict[UUID, list[str]] = {}
        introduction = [module.description] if module.description else []
        for block in editor.content_blocks:
            if block.kind == "section_header" and block.heading:
                introduction.append(block.heading)
            elif block.kind == "narrative" and block.markdown:
                introduction.append(block.markdown)
        if introduction:
            comments[root.id] = ["\n\n".join(introduction)]
        for note in editor.notes:
            if note.review_status == "approved" and note.target.kind == "occurrence":
                comments.setdefault(note.target.occurrence_id, []).append(note.rendered_markdown)
        try:
            pgn = await export_module_pgn(
                session,
                course_id,
                module.id,
                extra_headers={"ChapterName": name},
                extra_comments=comments,
            )
        except PgnExportError as error:
            raise ServiceError(
                "pgn_not_exportable", 409, f"「{path}」无法导出 PGN：{error}"
            ) from error
        # Scala strings count UTF-16 code units. Check the actual upstream limit.
        if len(pgn.encode("utf-16-le")) // 2 > MAX_CHAPTER_CHARS:
            blockers.append(f"「{path}」的棋谱和注释超过 Lichess 单章 100000 字符上限")
        pgns.append(pgn.rstrip())
    if not previews:
        blockers.append("所选范围没有可发送的棋谱")
    if len(previews) > MAX_CHAPTERS:
        blockers.append(
            f"所选范围有 {len(previews)} 个棋谱，超过单个研讨 64 章上限，请选择较小范围"
        )
    return PreparedStudy(
        preview=LichessStudyPreview(
            name=f"{course.title} · {selected.title}"[:100],
            chapters=previews,
            skipped_modules=skipped,
            warnings=warnings,
            blockers=blockers,
            token_configured=token_configured,
        ),
        pgn="\n\n".join(pgns) + "\n",
    )


def _failure_message(status: int) -> str:
    if status in {401, 403}:
        return "Lichess 拒绝授权，请检查令牌是否有效且具有 study:write 权限"
    if status == 429:
        return "Lichess 请求限流，请至少等待一分钟，并按其提示稍后再试"
    return f"Lichess 请求失败（HTTP {status}）"


def _study_id(payload: object) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("id")
        if isinstance(value, str) and len(value) == 8 and value.isascii() and value.isalnum():
            return value
    return None


async def publish_study(
    prepared: PreparedStudy,
    *,
    name: str,
    orientation: Literal["white", "black"],
    token: SecretStr,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LichessStudyResult:
    if prepared.preview.blockers:
        raise ServiceError("lichess_export_limit", 422, "；".join(prepared.preview.blockers))
    async with httpx.AsyncClient(
        base_url=LICHESS_URL,
        headers={
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/json",
            "User-Agent": "ChessWorkbench/0.1 (study export)",
        },
        timeout=httpx.Timeout(30.0, connect=10.0),
        transport=transport,
    ) as client:
        try:
            response = await client.post(
                "/api/study",
                data={
                    "name": name,
                    "visibility": "unlisted",
                    "computer": "everyone",
                    "explorer": "everyone",
                    "cloneable": "owner",
                    "shareable": "owner",
                    "chat": "owner",
                    "sticky": "false",
                    "description": "false",
                },
            )
        except httpx.HTTPError:
            raise ServiceError(
                "lichess_create_uncertain",
                502,
                "未能取得 Lichess 创建结果。远端可能已创建空研讨，"
                "请先查看 Lichess 我的研讨，避免重复创建",
            ) from None
        if not response.is_success:
            raise ServiceError(
                "lichess_request_failed", 502, _failure_message(response.status_code)
            )
        try:
            study_id = _study_id(response.json())
        except ValueError:
            study_id = None
        if study_id is None:
            raise ServiceError(
                "lichess_create_uncertain",
                502,
                "Lichess 未返回有效研讨链接，请先查看 Lichess 我的研讨",
            )
        result = LichessStudyResult(
            study_url=f"{LICHESS_URL}/study/{study_id}",
            status="uncertain",
            imported_chapters=0,
            expected_chapters=len(prepared.preview.chapters),
            message="研讨已创建，但导入结果未确认。请先打开研讨检查，避免重复发送",
        )
        try:
            response = await client.post(
                f"/api/study/{study_id}/import-pgn",
                data={
                    "pgn": prepared.pgn,
                    "orientation": orientation,
                    "initial": "true",
                    "sticky": "false",
                    "isDefaultName": "true",
                },
            )
        except httpx.HTTPError:
            return result
        if not response.is_success:
            return result.model_copy(
                update={
                    "message": f"{_failure_message(response.status_code)}。"
                    "研讨已创建，请打开检查导入情况"
                }
            )
        try:
            payload = response.json()
        except ValueError:
            return result
        if not isinstance(payload, dict) or not isinstance(payload.get("chapters"), list):
            return result
        chapters = payload["chapters"]
        if any(_study_id(chapter) is None for chapter in chapters):
            return result
        imported = len(chapters)
        complete = imported == result.expected_chapters and not payload.get("error")
        return result.model_copy(
            update={
                "status": "complete" if complete else "partial",
                "imported_chapters": imported,
                "message": (
                    f"已创建研讨，导入 {imported} 个章节"
                    if complete
                    else f"研讨已创建，只确认导入 {imported}/{result.expected_chapters} 个章节，"
                    "或 Lichess 报告了导入问题。请打开研讨检查；本次未自动重试"
                ),
            }
        )
