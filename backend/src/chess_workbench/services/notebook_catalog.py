"""Project catalog cards from saved PGN headers and actual mainline occurrences."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.domain.game_chronology import catalog_date
from chess_workbench.domain.openings import OPENING_MAX_PLIES, lichess_openings
from chess_workbench.schemas.personal_games import NotebookGame, NotebookGameCard
from chess_workbench.store.models.graph import Position
from chess_workbench.store.models.personal_games import PersonalGame, PersonalGameNode


def _rating(value: str) -> int | None:
    value = value.strip().removesuffix("?")
    if value.isascii() and value.isdigit() and len(value) <= 5:
        return int(value) or None
    return None


async def catalog_cards(
    session: AsyncSession,
    games: Sequence[PersonalGame],
) -> list[NotebookGameCard]:
    if not games:
        return []
    ids = [game.id for game in games]
    node = PersonalGameNode
    # Each game has one root and exactly one mainline node at each subsequent ply.
    # Read just the last one, even when a PGN side line goes on much longer.
    final_fen = (
        select(node.fen)
        .where(node.game_id == PersonalGame.id, node.is_mainline.is_(True))
        .order_by(node.ply.desc())
        .limit(1)
        .correlate(PersonalGame)
        .scalar_subquery()
    )
    finals = dict(
        (await session.execute(select(PersonalGame.id, final_fen).where(PersonalGame.id.in_(ids))))
        .tuples()
        .all()
    )
    positions = await session.execute(
        select(node.game_id, Position.position_key)
        .join(Position, Position.id == node.position_id)
        .where(node.game_id.in_(ids), node.is_mainline.is_(True), node.ply <= OPENING_MAX_PLIES)
        .order_by(node.game_id, node.ply)
    )
    book = lichess_openings()
    openings: dict[UUID, tuple[str, str]] = {}
    for game_id, key in positions:
        if opening := book.get(key):
            openings[game_id] = opening

    cards = []
    for game in games:
        headers = {tag.lower(): value.strip() for tag, value in game.headers.items()}
        eco, name = openings.get(game.id, (None, None))
        if game.platform == "lichess":
            # A direct Lichess export carries the classification published for this game.
            published_eco = headers.get("eco", "")
            published_name = headers.get("opening", "")
            if (
                len(published_eco) == 3
                and published_eco[0] in "ABCDE"
                and published_eco[1:].isdigit()
                and published_name not in {"", "?", "-"}
            ):
                eco, name = published_eco, published_name
        cards.append(
            NotebookGameCard(
                **NotebookGame.model_validate(game, from_attributes=True).model_dump(
                    exclude={"date"}
                ),
                date=catalog_date(headers),
                white_rating=_rating(headers.get("whiteelo", "")),
                black_rating=_rating(headers.get("blackelo", "")),
                time_control=game.time_control,
                started_at=game.started_at,
                final_fen=finals[game.id],
                opening_eco=eco,
                opening_name=name,
            )
        )
    return cards
