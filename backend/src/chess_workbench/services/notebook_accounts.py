"""Resume account synchronization in bounded, database-backed steps."""

from datetime import UTC, date, datetime, time
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.schemas.notebook_accounts import (
    GamePlatform,
    NotebookAccountCreate,
    NotebookAccountView,
    NotebookSyncResult,
)
from chess_workbench.services import ServiceError
from chess_workbench.services import notebook_platforms as platforms
from chess_workbench.store.database import Database
from chess_workbench.store.models.notebook_accounts import NotebookAccount, NotebookAccountGame

DRAIN_BATCH = 5
RECHECK_INTERVAL_MS = 2 * 24 * 60 * 60 * 1000


def day_ms(value: date) -> int:
    return int(datetime.combine(value, time(), tzinfo=UTC).timestamp()) * 1000


async def require_account(session: AsyncSession, account_id: UUID) -> NotebookAccount:
    row = await session.get(NotebookAccount, account_id)
    if row is None:
        raise ServiceError("not_found", 404, "找不到这个对局账号。")
    return row


async def account_view(session: AsyncSession, row: NotebookAccount) -> NotebookAccountView:
    model = NotebookAccountGame
    counts = dict(
        (
            await session.execute(
                select(model.state, func.count())
                .where(model.account_id == row.id)
                .group_by(model.state)
            )
        )
        .tuples()
        .all()
    )
    last_error = None
    if counts.get("failed"):
        last_error = await session.scalar(
            select(model.error).where(model.account_id == row.id, model.state == "failed").limit(1)
        )
    return NotebookAccountView(
        id=row.id,
        platform=cast(GamePlatform, row.platform),
        username=row.username,
        start_date=row.start_date,
        last_synced_ms=row.last_synced_ms,
        imported=counts.get("new", 0),
        existing=counts.get("existing", 0),
        queued=counts.get("queued", 0),
        waiting=counts.get("waiting", 0),
        failed=counts.get("failed", 0),
        last_error=last_error,
    )


async def list_accounts(session: AsyncSession) -> list[NotebookAccountView]:
    rows = (
        await session.scalars(select(NotebookAccount).order_by(NotebookAccount.created_at))
    ).all()
    return [await account_view(session, row) for row in rows]


async def create_account(session: AsyncSession, body: NotebookAccountCreate) -> NotebookAccountView:
    row = NotebookAccount(
        platform=body.platform,
        username=body.username.lower(),
        start_date=body.start_date,
        cursor_ms=day_ms(body.start_date),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ServiceError(
            "idempotency_conflict", 409, "这个平台账号已添加。可直接同步已有账号。"
        ) from exc
    return await account_view(session, row)


async def remove_account(session: AsyncSession, account_id: UUID) -> None:
    await require_account(session, account_id)
    await session.execute(delete(NotebookAccount).where(NotebookAccount.id == account_id))


async def retry_failures(session: AsyncSession, account_id: UUID) -> NotebookAccountView:
    row = await require_account(session, account_id)
    await session.execute(
        update(NotebookAccountGame)
        .where(
            NotebookAccountGame.account_id == account_id,
            NotebookAccountGame.state == "failed",
        )
        .values(state="queued", error=None)
    )
    return await account_view(session, row)


async def stage(
    session: AsyncSession, account_id: UUID, games: list[platforms.RemoteGame], target: int
) -> None:
    model = NotebookAccountGame
    for start in range(0, len(games), 250):
        chunk = games[start : start + 250]
        existing = {
            item.external_id: item
            for item in (
                await session.scalars(
                    select(model).where(
                        model.account_id == account_id,
                        model.external_id.in_([game.external_id for game in chunk]),
                    )
                )
            ).all()
        }
        for game in chunk:
            item = existing.get(game.external_id)
            if item is None:
                item = model(
                    account_id=account_id, external_id=game.external_id, source_url=game.url
                )
                session.add(item)
                existing[game.external_id] = item
            elif item.state != "waiting":
                continue
            if game.abandoned:
                item.state = "ignored"
            else:
                item.state = "queued" if game.pgn else "waiting"
            if game.started_at is not None:
                item.started_at = game.started_at
            item.pending_pgn = game.pgn
            item.checked_ms = target


async def sync_step(db: Database, account_id: UUID) -> NotebookSyncResult:
    model = NotebookAccountGame
    now = int(datetime.now(UTC).timestamp() * 1000)

    async def begin(session: AsyncSession) -> NotebookAccount:
        row = await require_account(session, account_id)
        if row.target_ms is None:
            row.target_ms = max(now, row.cursor_ms)
            # Public archives may appear late, including across a UTC-month boundary.
            # Seen IDs let us revisit two days without recreating deleted games.
            if row.last_synced_ms is not None:
                row.cursor_ms = max(day_ms(row.start_date), row.cursor_ms - RECHECK_INTERVAL_MS)
        return row

    account = await db.run_write(begin)
    target = account.target_ms
    assert target is not None

    async def import_one(session: AsyncSession) -> bool:
        from chess_workbench.services.personal_games import import_online_game

        item = await session.scalar(
            select(model)
            .where(model.account_id == account_id, model.state == "queued")
            .order_by(model.external_id)
            .limit(1)
        )
        if item is None:
            return False
        assert item.pending_pgn is not None
        try:
            # A malformed game can fail after some graph inserts; roll the game back
            # while preserving its upstream PGN for an explicit retry.
            async with session.begin_nested():
                result = await import_online_game(
                    session,
                    item.pending_pgn,
                    source_url=item.source_url,
                    source_started_at=item.started_at,
                )
        except ServiceError as exc:
            if exc.status >= 500:
                raise
            item.state, item.error = "failed", exc.message
        else:
            item.state = "new" if result.created else "existing"
            item.pending_pgn = None
            item.error = None
        return True

    async def progress(session: AsyncSession) -> NotebookSyncResult:
        row = await require_account(session, account_id)
        details = await account_view(session, row)
        due = await session.scalar(
            select(model.external_id)
            .where(
                model.account_id == account_id, model.state == "waiting", model.checked_ms < target
            )
            .limit(1)
        )
        more = bool(details.queued or row.cursor_ms < target or due)
        if not more:
            row.last_synced_ms = target
            row.target_ms = None
            details = details.model_copy(update={"last_synced_ms": target})
        return NotebookSyncResult(account=details, more=more)

    async with db.session() as session:
        queued = await session.scalar(
            select(model.external_id)
            .where(model.account_id == account_id, model.state == "queued")
            .limit(1)
        )
        waiting = list(
            (
                await session.scalars(
                    select(model.external_id)
                    .where(
                        model.account_id == account_id,
                        model.state == "waiting",
                        model.checked_ms < target,
                    )
                    .order_by(model.checked_ms)
                    .limit(100)
                )
            ).all()
        )

    if not queued:
        if waiting:
            async with platforms.client() as http:
                refreshed = await platforms.refresh_waiting(http, waiting)

            async def record_waiting(session: AsyncSession) -> None:
                await require_account(session, account_id)
                # Missing/aborted/private games need not block progress. Check again next sync.
                await session.execute(
                    update(model)
                    .where(model.account_id == account_id, model.external_id.in_(waiting))
                    .values(checked_ms=target)
                )
                await stage(session, account_id, refreshed, target)

            await db.run_write(record_waiting)
        elif account.cursor_ms < target:
            async with platforms.client() as http:
                fetch = (
                    platforms.lichess_page
                    if account.platform == "lichess"
                    else platforms.chesscom_page
                )
                games, boundary = await fetch(http, account.username, account.cursor_ms, target)

            async def record_page(session: AsyncSession) -> None:
                row = await require_account(session, account_id)
                await stage(session, account_id, games, target)
                row.cursor_ms = max(row.cursor_ms, boundary)

            await db.run_write(record_page)
    for _ in range(DRAIN_BATCH):
        if not await db.run_write(import_one):
            break
    return await db.run_write(progress)
