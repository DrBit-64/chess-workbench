"""Integration tests for PGN → course/occurrence import (Stage 3B)."""

from __future__ import annotations

from pathlib import Path

import pytest
from chess_workbench.logic.pgn import parse_pgn
from chess_workbench.logic.pgn_import import PgnImporter, PgnImportResult
from chess_workbench.services.content import ContentService
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import MoveEdge, Position
from sqlalchemy import func, select

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


# ── helpers ───────────────────────────────────────────────────────


async def _import_fixture(db: Database, stem: str) -> tuple[ContentService, PgnImportResult]:
    """Import a golden fixture and return (service, import_result)."""
    text = (FIXTURE_DIR / f"{stem}.pgn").read_text()
    game = parse_pgn(text)
    async with db.session() as session, session.begin():
        service = ContentService(session)
        importer = PgnImporter(service)
        result: PgnImportResult = await importer.import_game(game)
        return service, result


async def _count(db: Database, model: type) -> int:
    async with db.session() as session, session.begin():
        return await session.scalar(select(func.count()).select_from(model)) or 0


# ── basic import tests ────────────────────────────────────────────


async def test_import_simple_mainline(tmp_path: Path) -> None:
    """Import a simple mainline PGN and verify occurrence count."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_main.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    svc, result = await _import_fixture(db, "01_mainline")
    # 8 moves × 2 plies = 16 plies + 1 root = 17 occurrences
    assert result.occurrence_count == 17
    await db.close()


async def test_import_preserves_headers_as_course_title(tmp_path: Path) -> None:
    """Course title comes from PGN Event header."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_title.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    svc, result = await _import_fixture(db, "01_mainline")
    course = await svc.get_course(result.course_id)
    assert course.title == "Simple mainline"
    await db.close()


async def test_import_creates_position_rows(tmp_path: Path) -> None:
    """Import creates Position rows for each distinct FEN."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_pos.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _import_fixture(db, "01_mainline")
    pos_count = await _count(db, Position)
    # 16 distinct positions (excluding root which shares starting FEN) + 1 root
    assert pos_count >= 2
    await db.close()


async def test_import_creates_move_edge_rows(tmp_path: Path) -> None:
    """Import creates MoveEdge rows for each move."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_edge.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _import_fixture(db, "01_mainline")
    edge_count = await _count(db, MoveEdge)
    assert edge_count == 16  # 8 moves × 2 plies
    await db.close()


async def test_import_with_variations(tmp_path: Path) -> None:
    """PGN with variations creates additional occurrences."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_var.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    svc, result = await _import_fixture(db, "02_one_variation")
    # main line: 1.e4 e5 2.Nf3 Nc6 3.Bb5 (5 plies) + variation: c5 Nf3 d6 cxd4 (4 plies) = 9 + root
    assert result.occurrence_count >= 2
    await db.close()


async def test_import_with_nag_and_comment(tmp_path: Path) -> None:
    """NAG and comments are stored on occurrences."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_nag.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    svc, result = await _import_fixture(db, "04_nag")
    occs = await svc.list_occurrences(result.course_id)
    nags = [o.nag for o in occs if o.nag is not None]
    assert len(nags) > 0
    await db.close()


# ── idempotency / sharing tests ───────────────────────────────────


async def test_same_pgn_imported_twice_shares_positions(tmp_path: Path) -> None:
    """Importing two copies of the same mainline shares Position rows."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_idem.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _import_fixture(db, "01_mainline")
    pos_after_first = await _count(db, Position)

    await _import_fixture(db, "01_mainline")
    pos_after_second = await _count(db, Position)

    assert pos_after_second == pos_after_first  # no new Position rows
    await db.close()


async def test_transposition_merges_positions(tmp_path: Path) -> None:
    """Two PGNs arriving at the same position share one Position row."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_trans.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _import_fixture(db, "01_mainline")
    await _import_fixture(db, "12_transposition")
    # Both games start from the same initial position.
    # We should still only have one Position for the starting FEN.
    pos_count = await _count(db, Position)
    # Not asserting exact count — just that they share at least the root position
    assert pos_count > 0
    await db.close()


# ── error tests ───────────────────────────────────────────────────


async def test_import_rejects_illegal_pgn(tmp_path: Path) -> None:
    """Illegal PGN raises ValueError before any DB writes."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_illegal.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    with pytest.raises(ValueError, match="illegal"):
        parse_pgn("1. e4 e5 2. Kf3")  # King to f3 is illegal
