"""Local Lichess opening names keyed by canonical position, including transpositions.

CC0 data from https://github.com/lichess-org/chess-openings/tree/3ba6b20d31b2e6125cb0e6a2e792f400717d9d39
To reproduce the table from that revision: make dist/all.tsv && cut -f1,2,5 dist/all.tsv
"""

from functools import cache
from importlib.resources import files

from chess_workbench.domain.position_identity import POSITION_KEY_PREFIX

# scalachess OpeningDb searches up to the first 40 half-moves of a game.
OPENING_MAX_PLIES = 40


@cache
def lichess_openings() -> dict[str, tuple[str, str]]:
    """Use the same legal-en-passant EPD as our shared position graph."""
    result: dict[str, tuple[str, str]] = {}
    with files(__package__).joinpath("lichess_openings.tsv").open(encoding="utf-8") as rows:
        next(rows)  # eco, name, epd
        for row in rows:
            eco, name, epd = row.rstrip("\n").split("\t")
            if sum(c.isalpha() for c in epd.partition(" ")[0]) >= 20:
                result[POSITION_KEY_PREFIX + epd] = (eco, name)
    return result
