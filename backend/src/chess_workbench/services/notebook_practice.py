from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain import PositionError, parse_position
from chess_workbench.schemas.notebook_practice import PracticeEdit, PracticeRead
from chess_workbench.services import ServiceError
from chess_workbench.store.models.notebook_practice import NotebookPractice
from chess_workbench.store.models.personal_bookmarks import PersonalBookmark
from chess_workbench.store.models.personal_games import PersonalGameNode


async def _starting_fen(session: AsyncSession, bookmark_id: UUID) -> str:
    fen = await session.scalar(
        select(PersonalGameNode.fen)
        .join(PersonalBookmark, PersonalGameNode.id == PersonalBookmark.node_id)
        .where(PersonalBookmark.id == bookmark_id)
    )
    if fen is None:
        raise ServiceError("not_found", 404, "此收藏已被永久删除。")
    return fen


def _response(row: NotebookPractice | None) -> PracticeRead:
    if row is None:
        return PracticeRead(version=0, prompt="", lines=[])
    return PracticeRead(version=row.version, prompt=row.prompt, lines=row.lines)


async def read_practice(session: AsyncSession, bookmark_id: UUID) -> PracticeRead:
    await _starting_fen(session, bookmark_id)
    return _response(await session.get(NotebookPractice, bookmark_id))


async def save_practice(
    session: AsyncSession, bookmark_id: UUID, data: PracticeEdit
) -> PracticeRead:
    start = parse_position(await _starting_fen(session, bookmark_id))
    row = await session.get(NotebookPractice, bookmark_id, with_for_update=True)
    if (row.version if row else 0) != data.expected_version:
        raise ServiceError("stale_version", 409, "练习已在另一处修改，请重新载入。")
    accepted: list[list[str]] = []
    for number, line in enumerate(data.lines, 1):
        position = start
        for ply, move in enumerate(line, 1):
            try:
                position = position.apply_uci(move).after
            except PositionError as error:
                raise ServiceError(
                    "invalid_move", 422, f"第 {number} 条答案的第 {ply} 个半回合不合法。"
                ) from error
        if line not in accepted:
            accepted.append(line)
    if row is None:
        row = NotebookPractice(bookmark_id=bookmark_id)
        session.add(row)
    row.prompt = data.prompt.strip()
    row.lines = accepted
    await session.flush()
    return _response(row)


async def delete_practice(session: AsyncSession, bookmark_id: UUID, expected: int) -> None:
    row = await session.get(NotebookPractice, bookmark_id, with_for_update=True)
    if row is None:
        raise ServiceError("not_found", 404, "这道练习已删除。")
    if row.version != expected:
        raise ServiceError("stale_version", 409, "练习已在另一处修改，请重新载入。")
    await session.delete(row)
