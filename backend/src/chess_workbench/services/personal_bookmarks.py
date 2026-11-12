"""Store notebook material at its source occurrence; use the graph only for position lookup."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Row, Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from chess_workbench.schemas.personal_bookmarks import (
    MatchField,
    NotebookBookmark,
    NotebookBookmarkCreate,
    NotebookBookmarkList,
    NotebookBookmarkTags,
    NotebookBookmarkUpdate,
    NotebookMatch,
    NotebookOccurrence,
    NotebookOccurrenceList,
    NotebookRelatedMove,
)
from chess_workbench.services import ServiceError
from chess_workbench.store.models.personal_bookmarks import (
    PersonalBookmark,
    PersonalBookmarkMove,
    PersonalBookmarkTag,
)
from chess_workbench.store.models.personal_games import PersonalGame, PersonalGameNode


def _sources(node: PersonalGameNode, game: PersonalGame) -> NotebookOccurrence:
    return NotebookOccurrence(
        game_id=game.id,
        node_id=node.id,
        white=game.white,
        black=game.black,
        date=game.date,
        fen=node.fen,
        ply=node.ply,
        san=node.san,
        is_mainline=node.is_mainline,
        archived=game.archived_at is not None,
    )


def _query() -> Select[tuple[PersonalBookmark, PersonalGameNode, PersonalGame]]:
    return (
        select(PersonalBookmark, PersonalGameNode, PersonalGame)
        .options(
            load_only(
                PersonalGame.white, PersonalGame.black, PersonalGame.date, PersonalGame.archived_at
            ),
            load_only(
                PersonalGameNode.fen,
                PersonalGameNode.ply,
                PersonalGameNode.san,
                PersonalGameNode.is_mainline,
            ),
        )
        .join(PersonalGameNode, PersonalGameNode.id == PersonalBookmark.node_id)
        .join(PersonalGame, PersonalGame.id == PersonalGameNode.game_id)
    )


def _matching_fields(
    bookmark: PersonalBookmark, tags: list[str], moves: list[NotebookRelatedMove], query: str
) -> list[NotebookMatch]:
    if not query:
        return []
    fields: list[tuple[MatchField, str]] = [("title", bookmark.title), ("note", bookmark.note)]
    fields.extend(("tag", tag) for tag in tags)
    fields.extend(("move_note", move.note) for move in moves)
    hits = []
    for field, text in fields:
        match = re.search(re.escape(query), text, re.IGNORECASE)
        if match is None:
            continue
        left = max(0, match.start() - 28)
        right = min(len(text), match.end() + 48)
        snippet = ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")
        hits.append(NotebookMatch(field=field, text=snippet))
    return hits


async def _materialize(
    session: AsyncSession,
    rows: Sequence[Row[tuple[PersonalBookmark, PersonalGameNode, PersonalGame]]],
    query: str = "",
) -> list[NotebookBookmark]:
    # Keep related notes authoritative: a later edit to a move is immediately searchable.
    bookmark_ids = [bookmark.id for bookmark, _, _ in rows]
    tags: defaultdict[UUID, list[str]] = defaultdict(list)
    moves: defaultdict[UUID, list[NotebookRelatedMove]] = defaultdict(list)
    # SQLite's bound-parameter limit varies by build. A game-scoped list can be unpaged.
    for start in range(0, len(bookmark_ids), 500):
        batch = bookmark_ids[start : start + 500]
        for owner, tag in await session.execute(
            select(PersonalBookmarkTag.bookmark_id, PersonalBookmarkTag.name)
            .where(PersonalBookmarkTag.bookmark_id.in_(batch))
            .order_by(PersonalBookmarkTag.name)
        ):
            tags[owner].append(tag)
        for owner, node in await session.execute(
            select(PersonalBookmarkMove.bookmark_id, PersonalGameNode)
            .join(PersonalGameNode, PersonalGameNode.id == PersonalBookmarkMove.node_id)
            .where(PersonalBookmarkMove.bookmark_id.in_(batch))
            .order_by(PersonalGameNode.ply, PersonalGameNode.sort_order, PersonalGameNode.id)
        ):
            if node.san is not None:
                moves[owner].append(
                    NotebookRelatedMove(node_id=node.id, san=node.san, note=node.note)
                )

    return [
        NotebookBookmark(
            **_sources(node, game).model_dump(),
            id=bookmark.id,
            title=bookmark.title,
            note=bookmark.note,
            active=bookmark.active,
            version=bookmark.version,
            created_at=bookmark.created_at,
            tags=tags[bookmark.id],
            related_moves=moves[bookmark.id],
            matches=_matching_fields(bookmark, tags[bookmark.id], moves[bookmark.id], query),
        )
        for bookmark, node, game in rows
    ]


async def get_bookmark(session: AsyncSession, bookmark_id: UUID) -> NotebookBookmark:
    rows = (await session.execute(_query().where(PersonalBookmark.id == bookmark_id))).all()
    if not rows:
        raise ServiceError("not_found", 404, "找不到这条局面收藏")
    return (await _materialize(session, rows))[0]


async def star_bookmark(session: AsyncSession, data: NotebookBookmarkCreate) -> NotebookBookmark:
    # Lock the immutable source occurrence too: concurrent first stars share one row.
    node = await session.get(PersonalGameNode, data.node_id, with_for_update=True)
    if node is None:
        raise ServiceError("not_found", 404, "找不到棋谱中的这个局面")
    related_id = data.related_node_id
    if related_id is None or related_id == node.id:
        related_id = node.id if node.parent_id is not None else None
    else:
        related = await session.get(PersonalGameNode, related_id)
        if related is None or related.parent_id != node.id or related.game_id != node.game_id:
            raise ServiceError("validation_error", 422, "关联棋步必须是当前局面的直接后续着法")

    bookmark = await session.scalar(
        select(PersonalBookmark).where(PersonalBookmark.node_id == node.id).with_for_update()
    )
    created = bookmark is None
    if bookmark is None:
        bookmark = PersonalBookmark(node_id=node.id)
        session.add(bookmark)
        await session.flush()
    if (
        related_id is not None
        and await session.get(PersonalBookmarkMove, (bookmark.id, related_id)) is None
    ):
        session.add(PersonalBookmarkMove(bookmark_id=bookmark.id, node_id=related_id))
        if not created:
            bookmark.version += 1
    bookmark.active = True
    await session.flush()
    return await get_bookmark(session, bookmark.id)


async def _locked_bookmark(
    session: AsyncSession, bookmark_id: UUID, expected_version: int
) -> PersonalBookmark:
    bookmark = await session.get(PersonalBookmark, bookmark_id, with_for_update=True)
    if bookmark is None:
        raise ServiceError("not_found", 404, "找不到这条局面收藏")
    if bookmark.version != expected_version:
        raise ServiceError("stale_version", 409, "收藏已在别处修改，请刷新后再保存")
    return bookmark


async def update_bookmark(
    session: AsyncSession, bookmark_id: UUID, data: NotebookBookmarkUpdate
) -> NotebookBookmark:
    bookmark = await _locked_bookmark(session, bookmark_id, data.expected_version)
    if data.tags is not None:
        old_tags = set(
            await session.scalars(
                select(PersonalBookmarkTag.name).where(
                    PersonalBookmarkTag.bookmark_id == bookmark_id
                )
            )
        )
        desired = set(data.tags)
        if old_tags != desired:
            await session.execute(
                delete(PersonalBookmarkTag).where(
                    PersonalBookmarkTag.bookmark_id == bookmark_id,
                    PersonalBookmarkTag.name.in_(old_tags - desired),
                )
            )
            session.add_all(
                PersonalBookmarkTag(bookmark_id=bookmark_id, name=name)
                for name in sorted(desired - old_tags)
            )
            # Tag-only changes must invalidate stale editors on other devices.
            bookmark.version += 1
    if data.title is not None:
        bookmark.title = data.title.strip()
    if data.note is not None:
        bookmark.note = data.note
    if data.active is not None:
        bookmark.active = data.active
    await session.flush()
    return await get_bookmark(session, bookmark_id)


async def delete_bookmark(session: AsyncSession, bookmark_id: UUID, expected_version: int) -> None:
    await session.delete(await _locked_bookmark(session, bookmark_id, expected_version))


async def bookmark_tags(session: AsyncSession) -> NotebookBookmarkTags:
    stmt = (
        select(PersonalBookmarkTag.name)
        .join(PersonalBookmark, PersonalBookmark.id == PersonalBookmarkTag.bookmark_id)
        .where(PersonalBookmark.active.is_(True))
        .distinct()
        .order_by(PersonalBookmarkTag.name)
    )
    return NotebookBookmarkTags(tags=list(await session.scalars(stmt)))


async def list_bookmarks(
    session: AsyncSession,
    *,
    query: str,
    tags: list[str],
    game_id: UUID | None,
    offset: int,
    limit: int | None,
) -> NotebookBookmarkList:
    stmt = _query().where(PersonalBookmark.active.is_(True))
    if game_id is not None:
        stmt = stmt.where(PersonalGame.id == game_id)
    tags_of_bookmark = select(PersonalBookmarkTag.name).where(
        PersonalBookmarkTag.bookmark_id == PersonalBookmark.id
    )
    for tag in set(tags):
        stmt = stmt.where(tags_of_bookmark.where(PersonalBookmarkTag.name == tag).exists())
    if query:
        # Explicitly escape SQL LIKE metacharacters: quotes, %, _ and / are ordinary note text.
        needle = query.lower()
        move = aliased(PersonalGameNode)
        linked_notes = (
            select(PersonalBookmarkMove.node_id)
            .join(move, move.id == PersonalBookmarkMove.node_id)
            .where(
                PersonalBookmarkMove.bookmark_id == PersonalBookmark.id,
                func.lower(move.note).contains(needle, autoescape=True),
            )
        )
        stmt = stmt.where(
            or_(
                func.lower(PersonalBookmark.title).contains(needle, autoescape=True),
                func.lower(PersonalBookmark.note).contains(needle, autoescape=True),
                tags_of_bookmark.where(
                    func.lower(PersonalBookmarkTag.name).contains(needle, autoescape=True)
                ).exists(),
                linked_notes.exists(),
            )
        )
    total = (
        await session.scalar(stmt.with_only_columns(func.count(), maintain_column_froms=True)) or 0
    )
    stmt = stmt.order_by(PersonalBookmark.created_at.desc(), PersonalBookmark.id.desc()).offset(
        offset
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    return NotebookBookmarkList(total=total, items=await _materialize(session, rows, query))


async def other_occurrences(
    session: AsyncSession,
    bookmark_id: UUID,
    *,
    include_variations: bool,
    offset: int,
    limit: int,
) -> NotebookOccurrenceList:
    source = (
        await session.execute(
            select(PersonalGameNode.id, PersonalGameNode.position_id)
            .join(PersonalBookmark, PersonalBookmark.node_id == PersonalGameNode.id)
            .where(PersonalBookmark.id == bookmark_id)
        )
    ).one_or_none()
    if source is None:
        raise ServiceError("not_found", 404, "找不到这条局面收藏")
    node_id, position_id = source
    stmt = (
        select(PersonalGameNode, PersonalGame)
        .options(
            load_only(
                PersonalGame.white, PersonalGame.black, PersonalGame.date, PersonalGame.archived_at
            ),
            load_only(
                PersonalGameNode.fen,
                PersonalGameNode.ply,
                PersonalGameNode.san,
                PersonalGameNode.is_mainline,
            ),
        )
        .join(PersonalGame, PersonalGame.id == PersonalGameNode.game_id)
        .where(PersonalGameNode.position_id == position_id, PersonalGameNode.id != node_id)
    )
    if include_variations:
        # The original game still reached its played positions after review edits.
        # Removed analysis variations remain accessible from their exact bookmarks.
        stmt = stmt.where(
            or_(PersonalGameNode.is_mainline.is_(True), PersonalGameNode.hidden.is_(False))
        )
    else:
        stmt = stmt.where(PersonalGameNode.is_mainline.is_(True))
    total = (
        await session.scalar(stmt.with_only_columns(func.count(), maintain_column_froms=True)) or 0
    )
    rows = await session.execute(
        stmt.order_by(
            PersonalGame.created_at.desc(),
            PersonalGame.id,
            PersonalGameNode.ply,
            PersonalGameNode.sort_order,
            PersonalGameNode.id,
        )
        .offset(offset)
        .limit(limit)
    )
    return NotebookOccurrenceList(items=[_sources(node, game) for node, game in rows], total=total)
