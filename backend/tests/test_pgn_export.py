"""Round-trip tests for PGN import → export → reimport (Stage 3C)."""

from __future__ import annotations

from pathlib import Path

from chess_workbench.logic.pgn import parse_pgn
from chess_workbench.logic.pgn_compare import compare_games
from chess_workbench.logic.pgn_export import export_pgn
from chess_workbench.logic.pgn_import import PgnImporter
from chess_workbench.services.content import ContentService
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


async def _round_trip(db: Database, stem: str) -> bool:
    """Import → export → reimport → compare.  Returns True if equivalent."""
    text = (FIXTURE_DIR / f"{stem}.pgn").read_text()
    original = parse_pgn(text)

    async with db.session() as session, session.begin():
        service = ContentService(session)
        importer = PgnImporter(service)
        result = await importer.import_game(original)

        exported_text = await export_pgn(service, result.course_id)

    reimported = parse_pgn(exported_text)
    cmp_result = compare_games(original, reimported)
    return cmp_result.equivalent


async def _round_trip_with_details(db: Database, stem: str) -> tuple[bool, list[str]]:
    """Like _round_trip but returns (equivalent, differences)."""
    text = (FIXTURE_DIR / f"{stem}.pgn").read_text()
    original = parse_pgn(text)

    async with db.session() as session, session.begin():
        service = ContentService(session)
        importer = PgnImporter(service)
        result = await importer.import_game(original)
        exported_text = await export_pgn(service, result.course_id)

    reimported = parse_pgn(exported_text)
    cmp_result = compare_games(original, reimported)
    return cmp_result.equivalent, cmp_result.differences


async def _all_fixture_stems() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.pgn"))


# ── round-trip tests ──────────────────────────────────────────────


async def test_mainline_round_trip(tmp_path: Path) -> None:
    """01_mainline: import → export → reimport is semantically equivalent."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_main.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok = await _round_trip(db, "01_mainline")
    assert ok
    await db.close()


async def test_variation_round_trip(tmp_path: Path) -> None:
    """02_one_variation: round-trip preserves variation structure."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_var.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok = await _round_trip(db, "02_one_variation")
    assert ok
    await db.close()


async def test_nested_variations_round_trip(tmp_path: Path) -> None:
    """03_nested_variations: nested parentheses survive round-trip."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_nest.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok, diffs = await _round_trip_with_details(db, "03_nested_variations")
    assert ok, f"differences: {diffs}"
    await db.close()


async def test_nag_round_trip(tmp_path: Path) -> None:
    """04_nag: NAG annotations survive round-trip."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_nag.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok = await _round_trip(db, "04_nag")
    assert ok
    await db.close()


async def test_setup_fen_round_trip(tmp_path: Path) -> None:
    """08_setup_fen: non-standard starting position survives round-trip."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_fen.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok = await _round_trip(db, "08_setup_fen")
    assert ok
    await db.close()


async def test_multiple_variations_round_trip(tmp_path: Path) -> None:
    """11_multiple_variations: 4-way branch survives round-trip."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_multi.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ok = await _round_trip(db, "11_multiple_variations")
    assert ok
    await db.close()


async def test_exported_pgn_is_parseable(tmp_path: Path) -> None:
    """Every exported PGN from every fixture can be re-parsed."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3c_all.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for stem in await _all_fixture_stems():
        text = (FIXTURE_DIR / f"{stem}.pgn").read_text()
        original = parse_pgn(text)

        async with db.session() as session, session.begin():
            service = ContentService(session)
            importer = PgnImporter(service)
            result = await importer.import_game(original)
            exported_text = await export_pgn(service, result.course_id)

        # Must parse without error.
        parse_pgn(exported_text)
    await db.close()


# ── comparator unit tests ─────────────────────────────────────────


def test_identical_games_are_equivalent() -> None:
    """Two parses of the same PGN text are equivalent."""
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    g1 = parse_pgn(text)
    g2 = parse_pgn(text)
    result = compare_games(g1, g2)
    assert result.equivalent


def test_different_headers_are_detected() -> None:
    """Changing a header produces a difference."""
    text = (FIXTURE_DIR / "01_mainline.pgn").read_text()
    g1 = parse_pgn(text)
    g2 = parse_pgn(text)
    g2.headers["event"] = "Different Event"
    result = compare_games(g1, g2)
    assert not result.equivalent
    assert any("event" in d for d in result.differences)


def test_different_nag_is_detected() -> None:
    """Changing a NAG produces a difference."""
    text = (FIXTURE_DIR / "04_nag.pgn").read_text()
    g1 = parse_pgn(text)
    # Modify an existing NAG in the tree.
    # Walk to the first child and change its NAG.
    child = g1.root.children[0]
    from chess_workbench.logic.pgn import PgnNode

    modified = PgnNode(
        ply=child.ply,
        fen=child.fen,
        san=child.san,
        uci=child.uci,
        nag=99,  # different NAG
        comment=child.comment,
        children=child.children,
    )
    fake_root = PgnNode(
        ply=g1.root.ply,
        fen=g1.root.fen,
        san=g1.root.san,
        uci=g1.root.uci,
        nag=g1.root.nag,
        comment=g1.root.comment,
        children=(modified, *g1.root.children[1:]),
    )
    from chess_workbench.logic.pgn import PgnGame

    g2 = PgnGame(headers=g1.headers, root=fake_root)
    result = compare_games(g1, g2)
    assert not result.equivalent
    assert any("NAG" in d for d in result.differences)
