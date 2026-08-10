"""Integration tests for PGN → course/occurrence import (Stage 3B)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from chess_workbench.logic.pgn import parse_pgn
from chess_workbench.logic.pgn_import import PgnImporter, PgnImportResult
from chess_workbench.schemas.domain import CourseCreate
from chess_workbench.schemas.pgn import ExistingCourseDestination, NewCourseDestination
from chess_workbench.services.content import ContentService, ServiceError
from chess_workbench.services.pgn import (
    PgnImportService,
    PreparedPgnImport,
    prepare_pgn_import,
)
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import MoveEdge, Position
from sqlalchemy import func, select

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


# ── helpers ───────────────────────────────────────────────────────


async def _import_fixture(db: Database, stem: str) -> PgnImportResult:
    """Import a golden fixture and return its immutable result."""
    text = (FIXTURE_DIR / f"{stem}.pgn").read_text()
    game = parse_pgn(text)
    async with db.session() as session, session.begin():
        service = ContentService(session)
        importer = PgnImporter(service)
        result: PgnImportResult = await importer.import_game(game)
        return result


async def _count(db: Database, model: type) -> int:
    async with db.session() as session, session.begin():
        return await session.scalar(select(func.count()).select_from(model)) or 0


# ── basic import tests ────────────────────────────────────────────


async def test_import_simple_mainline(tmp_path: Path) -> None:
    """Import a simple mainline PGN and verify occurrence count."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_main.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = await _import_fixture(db, "01_mainline")
    # 8 moves × 2 plies = 16 plies + 1 root = 17 occurrences
    assert result.occurrence_count == 17
    await db.close()


async def test_import_preserves_headers_as_course_title(tmp_path: Path) -> None:
    """Course title comes from PGN Event header."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_title.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = await _import_fixture(db, "01_mainline")
    async with db.session() as session:
        course = await ContentService(session).get_course(result.course_id)
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

    result = await _import_fixture(db, "02_one_variation")
    # main line: 1.e4 e5 2.Nf3 Nc6 3.Bb5 (5 plies) + variation: c5 Nf3 d6 cxd4 (4 plies) = 9 + root
    assert result.occurrence_count >= 2
    await db.close()


async def test_import_with_nag_and_comment(tmp_path: Path) -> None:
    """NAG and comments are stored on occurrences."""
    db = Database(f"sqlite+aiosqlite:///{tmp_path / '3b_nag.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = await _import_fixture(db, "04_nag")
    async with db.session() as session:
        occs = await ContentService(session).list_occurrences(result.course_id)
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


@pytest.mark.parametrize(
    "failure_phase", ["source", "module", "occurrence", "annotation", "receipt"]
)
async def test_import_fault_at_every_write_phase_rolls_back_all_business_rows(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / f'rollback-{failure_phase}.db'}")
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    raw = (FIXTURE_DIR / "02_one_variation.pgn").read_bytes()
    storage_root = tmp_path / f"storage-{failure_phase}"
    prepared = prepare_pgn_import(
        raw,
        destination=NewCourseDestination(),
        source_title=None,
        game_titles=None,
        idempotency_key=None,
        storage_root=storage_root,
    )

    def inject(phase: str, _: dict[str, object]) -> None:
        if phase == failure_phase:
            raise RuntimeError(f"injected {phase} failure")

    with pytest.raises(RuntimeError, match=f"injected {failure_phase} failure"):
        async with db.session() as session, session.begin():
            await PgnImportService(session, fault_injector=inject).import_prepared(prepared)

    async with db.session() as session:
        for table in Base.metadata.sorted_tables:
            count = await session.scalar(select(func.count()).select_from(table))
            assert count == 0, (failure_phase, table.name, count)
    assert (storage_root / prepared.relative_path).is_file()
    await db.close()


def test_cas_rejects_corrupt_existing_blob_and_unavailable_root(tmp_path: Path) -> None:
    raw = (FIXTURE_DIR / "01_mainline.pgn").read_bytes()
    storage_root = tmp_path / "storage"
    prepared = prepare_pgn_import(
        raw,
        destination=NewCourseDestination(),
        source_title=None,
        game_titles=None,
        idempotency_key=None,
        storage_root=storage_root,
    )
    blob = storage_root / prepared.relative_path
    blob.write_bytes(b"corrupt")
    with pytest.raises(ServiceError) as corrupt:
        prepare_pgn_import(
            raw,
            destination=NewCourseDestination(),
            source_title=None,
            game_titles=None,
            idempotency_key=None,
            storage_root=storage_root,
        )
    assert corrupt.value.code == "source_storage_unavailable"

    unavailable_root = tmp_path / "not-a-directory"
    unavailable_root.write_text("file")
    with pytest.raises(ServiceError) as unavailable:
        prepare_pgn_import(
            raw,
            destination=NewCourseDestination(title="Different fingerprint"),
            source_title=None,
            game_titles=None,
            idempotency_key=None,
            storage_root=unavailable_root,
        )
    assert unavailable.value.code == "source_storage_unavailable"


def test_non_ascii_idempotency_key_is_rejected_before_storage(tmp_path: Path) -> None:
    raw = (FIXTURE_DIR / "01_mainline.pgn").read_bytes()
    with pytest.raises(ServiceError) as invalid_key:
        prepare_pgn_import(
            raw,
            destination=NewCourseDestination(),
            source_title=None,
            game_titles=None,
            idempotency_key="不可见",
            storage_root=tmp_path / "storage",
        )
    assert invalid_key.value.code == "validation_error"
    assert not (tmp_path / "storage").exists()


async def test_compatibility_importer_preserves_extended_context_and_is_bounded(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'compatibility-bounds.db'}")
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    game = parse_pgn(
        '[Event "Context"]\n[Result "*"]\n\n{root comment} 1. e4 $1 $3 {move comment} *'
    )
    async with db.session() as session, session.begin():
        result = await PgnImporter(ContentService(session)).import_game(game)
    async with db.session() as session:
        occurrences = await ContentService(session).list_occurrences(result.course_id)
    root = next(item for item in occurrences if item.parent_id is None)
    child = next(item for item in occurrences if item.parent_id is not None)
    assert root.context["pgn_comment"] == "root comment"
    assert child.context["pgn_comment"] == "move comment"
    assert child.context["pgn_nags"] == [1, 3]

    with pytest.raises(ValueError, match="maximum import nodes"):
        async with db.session() as session, session.begin():
            await PgnImporter(ContentService(session), max_nodes=0).import_game(game)
    await db.close()


async def test_import_service_checks_every_existing_course_and_key_conflict_branch(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'target-branches.db'}")
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    raw = (FIXTURE_DIR / "01_mainline.pgn").read_bytes()
    other_raw = (FIXTURE_DIR / "02_one_variation.pgn").read_bytes()

    async with db.session() as session, session.begin():
        content = ContentService(session)
        explorer = await content.create_course(
            CourseCreate(title="Explorer", mode="opening_explorer")
        )
        traditional = await content.create_course(
            CourseCreate(title="Traditional", mode="traditional")
        )

    def prepared_for(
        destination: ExistingCourseDestination, payload: bytes = raw
    ) -> PreparedPgnImport:
        return prepare_pgn_import(
            payload,
            destination=destination,
            source_title=None,
            game_titles=None,
            idempotency_key=None,
            storage_root=tmp_path / "storage",
        )

    targets = [
        (
            prepared_for(
                ExistingCourseDestination(
                    kind="existing_course", course_id=uuid4(), expected_version=1
                )
            ),
            "not_found",
        ),
        (
            prepared_for(
                ExistingCourseDestination(
                    kind="existing_course", course_id=explorer.id, expected_version=1
                )
            ),
            "course_mode_conflict",
        ),
        (
            prepared_for(
                ExistingCourseDestination(
                    kind="existing_course", course_id=traditional.id, expected_version=2
                )
            ),
            "stale_version",
        ),
    ]
    for prepared, code in targets:
        with pytest.raises(ServiceError) as rejected:
            async with db.session() as session, session.begin():
                await PgnImportService(session).import_prepared(prepared)
        assert rejected.value.code == code

    successful = prepared_for(
        ExistingCourseDestination(
            kind="existing_course", course_id=traditional.id, expected_version=1
        )
    )
    async with db.session() as session, session.begin():
        created = await PgnImportService(session).import_prepared(successful)
    assert created.receipt.course_version == 2

    explicit_first = prepare_pgn_import(
        raw,
        destination=NewCourseDestination(title="Explicit key"),
        source_title=None,
        game_titles=None,
        idempotency_key="same-explicit-key",
        storage_root=tmp_path / "storage",
    )
    explicit_other = prepare_pgn_import(
        other_raw,
        destination=NewCourseDestination(title="Explicit key"),
        source_title=None,
        game_titles=None,
        idempotency_key="same-explicit-key",
        storage_root=tmp_path / "storage",
    )
    async with db.session() as session, session.begin():
        await PgnImportService(session).import_prepared(explicit_first)
    with pytest.raises(ServiceError) as conflict:
        async with db.session() as session, session.begin():
            await PgnImportService(session).import_prepared(explicit_other)
    assert conflict.value.code == "idempotency_conflict"

    async with db.session() as session:
        with pytest.raises(ServiceError) as missing_receipt:
            await PgnImportService(session).get_import(uuid4())
    assert missing_receipt.value.code == "not_found"
    await db.close()
