"""Import selected games into a private collection and retain each exact source occurrence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import cast
from urllib.parse import SplitResult, urlsplit
from uuid import UUID

import httpx
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from chess_workbench.domain.position_identity import PositionError, PositionState
from chess_workbench.logic.pgn import PgnDocument, PgnError, PgnGame, parse_pgn_document
from chess_workbench.schemas.personal_games import (
    NotebookCandidate,
    NotebookGame,
    NotebookGameDetail,
    NotebookGameUpdate,
    NotebookImportItem,
    NotebookImportRequest,
    NotebookNode,
    NotebookNodeUpdate,
    NotebookSelection,
)
from chess_workbench.services import notebook_platforms
from chess_workbench.services.content import ServiceError
from chess_workbench.services.pgn import MAX_PGN_BYTES
from chess_workbench.store.models.mixins import utc_now
from chess_workbench.store.models.personal_games import PersonalGame, PersonalGameNode
from chess_workbench.store.personal_game_graph import persist_game_tree

_LICHESS_PATH = re.compile(
    r"/(?:game/(?:export/)?)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?:/(?:white|black))?/?"
)
_STANDARD = {"standard", "chess", "normal", "from position"}


def _safe_url(text: str | None) -> SplitResult | None:
    if not text or len(text) > 2048:
        return None
    try:
        url = urlsplit(text)
        if (
            url.scheme in {"https", "http"}
            and url.hostname
            and not url.username
            and not url.password
            and url.port in (None, 80, 443)
        ):
            return url
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class GameSource:
    platform: str | None
    external_id: str | None
    url: str | None


def game_source(text: str | None) -> GameSource:
    url = _safe_url(text)
    if url is None:
        return GameSource(None, None, None)
    if url.hostname in {"lichess.org", "www.lichess.org"} and (
        match := _LICHESS_PATH.fullmatch(url.path)
    ):
        game_id = match[1]
        return GameSource("lichess", game_id, f"https://lichess.org/{game_id}")
    if identity := notebook_platforms.chesscom_id(url.geturl()):
        kind, game_id = identity
        return GameSource(
            "chess.com", f"{kind}/{game_id}", f"https://www.chess.com/game/{kind}/{game_id}"
        )
    return GameSource(None, None, url.geturl())


def _source(game: PgnGame, source_url: str | None = None) -> GameSource:
    descriptions = [game_source(game.header(tag)) for tag in ("link", "site")]
    embedded = next((item for item in descriptions if item.platform), None)
    if source_url is not None:
        explicit = game_source(source_url)
        if not explicit.platform or (embedded and explicit.url != embedded.url):
            raise ServiceError("invalid_pgn", 422, "来源链接与棋谱记录的对局编号不符。")
        return explicit
    return embedded or next(
        (item for item in descriptions if item.url), GameSource(None, None, None)
    )


async def fetch_notebook_pgn(url: str, username: str | None, month: str | None) -> str:
    source = game_source(url.strip())
    if source.platform == "chess.com":
        assert source.url is not None
        return await notebook_platforms.fetch_chesscom_pgn(source.url, username, month)
    if source.platform != "lichess":
        raise ServiceError(
            "validation_error", 422, "请粘贴 Lichess 或 Chess.com 的单局链接，也可以导入 PGN。"
        )
    endpoint = f"https://lichess.org/game/export/{source.external_id}"
    try:
        async with (
            notebook_platforms.client() as client,
            client.stream(
                "GET",
                endpoint,
                headers={"Accept": "application/x-chess-pgn"},
                params={"clocks": "true", "opening": "true", "evals": "true"},
            ) as response,
        ):
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_PGN_BYTES:
                    raise ServiceError(
                        "payload_too_large", 413, "棋谱超过大小限制，请导入较小的 PGN。"
                    )
        pgn = content.decode("utf-8")
    except (httpx.HTTPError, UnicodeError) as exc:
        raise ServiceError(
            "lichess_request_failed",
            502,
            "无法读取这盘公开对局。请检查链接，或从平台导出 PGN 再导入。",
        ) from exc
    return pgn


def parse_notebook_pgn(pgn: str) -> PgnDocument:
    if len(pgn.encode("utf-8")) > MAX_PGN_BYTES:
        raise ServiceError("payload_too_large", 413, "PGN 超过 5 MiB，请分批导入。")
    try:
        document = parse_pgn_document(pgn.removeprefix("\ufeff"))
        for game in document.games:
            if (game.header("variant") or "standard").strip().lower() not in _STANDARD:
                raise ServiceError("invalid_pgn", 422, "目前仅支持标准国际象棋。")
            PositionState(game.root.fen)
    except PgnError as exc:
        location = f"第 {exc.game_index + 1} 盘" if exc.game_index is not None else "PGN"
        reason = {
            "missing_result": "缺少结尾结果标记（1-0、0-1、1/2-1/2 或 *）",
            "result_conflict": "棋谱头的对局结果与结尾标记不同",
            "parser_error": "包含无法识别或不合法的着法",
            "illegal_move": "包含不合法的着法",
            "duplicate_tag": "包含重复的棋谱头标签",
            "empty_document": "内容为空",
        }.get(exc.reason, str(exc))
        raise ServiceError(
            exc.kind, 422, f"{location}：{reason}。", cast(dict[str, JsonValue], exc.details())
        ) from exc
    except (PositionError, ValueError) as exc:
        raise ServiceError("invalid_pgn", 422, "起始局面或棋规无效。") from exc
    return document


def _fingerprint(game: PgnGame) -> str:
    # Annotations may change between exports. Offer an explicit choice when
    # players and the complete recorded mainline agree, without merging games.
    values = [game.header("white") or "?", game.header("black") or "?", game.root.fen]
    node = game.root
    while node.children:
        node = node.children[0]
        values.append(node.uci or "")
    return sha256("\0".join(values).encode()).hexdigest()


async def _candidate(
    session: AsyncSession, game: PgnGame, index: int, source_url: str | None = None
) -> NotebookCandidate:
    source = _source(game, source_url)
    existing_id = None
    possible: list[UUID] = []
    if source.platform:
        existing_id = await session.scalar(
            select(PersonalGame.id).where(
                PersonalGame.platform == source.platform,
                PersonalGame.external_id == source.external_id,
            )
        )
    else:
        possible = list(
            await session.scalars(
                select(PersonalGame.id)
                .where(PersonalGame.fingerprint == _fingerprint(game))
                .order_by(PersonalGame.created_at.desc())
            )
        )
    return NotebookCandidate(
        index=index,
        white=game.header("white") or "?",
        black=game.header("black") or "?",
        date=game.header("date") or "????.??.??",
        result=game.result,
        platform=source.platform,
        source_url=source.url,
        existing_id=existing_id,
        possible_duplicates=possible,
    )


def _validate_link_document(document: PgnDocument, source_url: str | None) -> None:
    if source_url and len(document.games) != 1:
        raise ServiceError("invalid_pgn", 422, "单局链接只能对应一盘棋。")
    if source_url and document.games[0].result == "*":
        raise ServiceError("invalid_pgn", 422, "请在对局结束后收藏，或改用 PGN。")


async def preview_games(
    session: AsyncSession, document: PgnDocument, source_url: str | None = None
) -> list[NotebookCandidate]:
    _validate_link_document(document, source_url)
    return [await _candidate(session, game, i, source_url) for i, game in enumerate(document.games)]


async def save_games(
    session: AsyncSession, document: PgnDocument, request: NotebookImportRequest
) -> list[NotebookImportItem]:
    indices = [selection.index for selection in request.selections]
    _validate_link_document(document, request.source_url)
    if max(indices) >= len(document.games) or len(set(indices)) != len(indices):
        raise ServiceError("validation_error", 422, "请选择预览中不同的有效棋局。")
    result: list[NotebookImportItem] = []
    created_here: set[UUID] = set()
    # The parser's spans exclude a leading Unicode BOM if one was supplied.
    offset = int(request.pgn.startswith("\ufeff"))
    for selection in request.selections:
        game = document.games[selection.index]
        start = game.source_start + offset if game.source_start else 0
        end = game.source_end + offset if selection.index + 1 < len(document.games) else None
        raw = request.pgn[start:end]
        import_key = None
        if request.request_id:
            import_key = sha256(
                f"{request.request_id}:{selection.index}:{raw}".encode()
            ).hexdigest()
        item = await _save_game(
            session, game, raw, selection, import_key, request.source_url, created_here
        )
        result.append(item)
        if item.created:
            created_here.add(item.id)
    return result


async def _save_game(
    session: AsyncSession,
    game: PgnGame,
    raw: str,
    selection: NotebookSelection,
    import_key: str | None,
    source_url: str | None = None,
    created_here: set[UUID] | None = None,
) -> NotebookImportItem:
    candidate = await _candidate(session, game, selection.index, source_url)
    existing = candidate.existing_id
    if existing is None and import_key:
        existing = await session.scalar(
            select(PersonalGame.id).where(PersonalGame.import_key == import_key)
        )
    if existing is not None:
        return NotebookImportItem(index=selection.index, id=existing, created=False)
    if selection.action == "open":
        if (
            selection.existing_id not in candidate.possible_duplicates
            or selection.existing_id is None
        ):
            raise ServiceError(
                "validation_error", 422, "所选对局不在此项的重复候选中，请刷新预览。"
            )
        return NotebookImportItem(index=selection.index, id=selection.existing_id, created=False)
    if (
        set(candidate.possible_duplicates).difference(created_here or ())
        and selection.action != "copy"
    ):
        raise ServiceError(
            "idempotency_conflict", 409, "发现可能相同的棋谱，请选择打开已有对局或保存副本。"
        )
    source = _source(game, source_url)
    row = PersonalGame(
        white=candidate.white,
        black=candidate.black,
        date=candidate.date,
        result=game.result,
        headers={header.name: header.value for header in game.header_items},
        original_pgn=raw,
        platform=source.platform,
        external_id=source.external_id,
        source_url=source.url,
        fingerprint=_fingerprint(game),
        import_key=import_key,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        candidate = await _candidate(session, game, selection.index, source_url)
        existing = candidate.existing_id
        if existing is None and import_key:
            existing = await session.scalar(
                select(PersonalGame.id).where(PersonalGame.import_key == import_key)
            )
        if existing is None:
            raise
        return NotebookImportItem(index=selection.index, id=existing, created=False)
    await persist_game_tree(session, row.id, game.root)
    return NotebookImportItem(index=selection.index, id=row.id, created=True)


async def import_online_game(
    session: AsyncSession, pgn: str, *, source_url: str | None = None
) -> NotebookImportItem:
    document = parse_notebook_pgn(pgn)
    if len(document.games) != 1 or not _source(document.games[0], source_url).external_id:
        raise ServiceError("invalid_pgn", 422, "同步的棋谱缺少可核验的单局编号。")
    return await _save_game(
        session, document.games[0], pgn, NotebookSelection(index=0), None, source_url
    )


async def get_game(session: AsyncSession, game_id: UUID) -> PersonalGame:
    row = await session.get(PersonalGame, game_id)
    if row is None:
        raise ServiceError("not_found", 404, "这盘棋已删除或不存在。")
    return row


async def game_detail(session: AsyncSession, game_id: UUID) -> NotebookGameDetail:
    game = await get_game(session, game_id)
    nodes = await session.scalars(
        select(PersonalGameNode)
        .where(PersonalGameNode.game_id == game_id)
        .order_by(PersonalGameNode.ply, PersonalGameNode.sort_order, PersonalGameNode.id)
    )
    return NotebookGameDetail(
        **NotebookGame.model_validate(game, from_attributes=True).model_dump(),
        headers=game.headers,
        nodes=[NotebookNode.model_validate(node, from_attributes=True) for node in nodes],
    )


def _check_version(version: int, expected: int) -> None:
    if version != expected:
        raise ServiceError("stale_version", 409, "记录已在其他设备更新，请重新载入后保存。")


async def _flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except StaleDataError as error:
        raise ServiceError(
            "stale_version", 409, "记录已在其他设备更新，请重新载入后保存。"
        ) from error


async def update_game(
    session: AsyncSession, game_id: UUID, changes: NotebookGameUpdate
) -> NotebookGame:
    row = await get_game(session, game_id)
    _check_version(row.version, changes.expected_version)
    if changes.summary is not None:
        row.summary = changes.summary
    if changes.archived is not None and changes.archived != (row.archived_at is not None):
        row.archived_at = utc_now() if changes.archived else None
    await _flush(session)
    return NotebookGame.model_validate(row, from_attributes=True)


async def update_node(
    session: AsyncSession, game_id: UUID, node_id: UUID, changes: NotebookNodeUpdate
) -> NotebookNode:
    row = await session.get(PersonalGameNode, node_id)
    if row is None or row.game_id != game_id:
        raise ServiceError("not_found", 404, "未找到此棋步。")
    _check_version(row.version, changes.expected_version)
    row.note = changes.note
    await _flush(session)
    return NotebookNode.model_validate(row, from_attributes=True)


async def delete_game(session: AsyncSession, game_id: UUID, expected_version: int) -> None:
    row = await get_game(session, game_id)
    _check_version(row.version, expected_version)
    if row.archived_at is None:
        raise ServiceError("resource_referenced", 409, "请先归档此对局，再从归档列表永久删除。")
    # Unlink internal self-references in the same transaction so very long games
    # can be removed without exhausting a database's cascaded-trigger depth.
    await session.execute(
        update(PersonalGameNode).where(PersonalGameNode.game_id == game_id).values(parent_id=None)
    )
    await session.delete(row)
    await _flush(session)
