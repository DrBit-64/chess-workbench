"""Populate the catalog projection for notebook games saved before revision 0022."""

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from chess_workbench.domain.game_chronology import game_chronology
from chess_workbench.store.models.mixins import UTCDateTime


def backfill_catalog(connection: Connection) -> None:
    games = sa.table(
        "personal_games",
        sa.column("id", sa.Uuid()),
        sa.column("headers", sa.JSON()),
        sa.column("created_at", UTCDateTime()),
        sa.column("order_at", UTCDateTime()),
        sa.column("started_at", UTCDateTime()),
        sa.column("time_control", sa.Text()),
    )
    missing = (
        sa.select(games.c.id, games.c.headers, games.c.created_at)
        .where(games.c.order_at.is_(None))
        .limit(400)
    )
    change = (
        sa.update(games)
        .where(games.c.id == sa.bindparam("game_id"))
        .values(
            order_at=sa.bindparam("ordering"),
            started_at=sa.bindparam("start"),
            time_control=sa.bindparam("clock"),
        )
    )
    while rows := connection.execute(missing).all():
        changes = []
        for game_id, headers, created_at in rows:
            ordering, start, clock = game_chronology(headers, created_at)
            changes.append(
                {"game_id": game_id, "ordering": ordering, "start": start, "clock": clock}
            )
        connection.execute(change, changes)
