from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from chess_workbench.domain import PositionState
from chess_workbench.store.base import Base
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ArchiveMixin,
    Course,
    CourseContentBlock,
    CourseModule,
    CourseOccurrence,
    KnowledgeNote,
    MoveEdge,
    Position,
    Source,
    SourceSpan,
    SourceVersion,
    UTCDateTime,
    UTCTimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _MixinTestBase(DeclarativeBase):
    pass


class _MutableRecord(
    UUIDPrimaryKeyMixin,
    UTCTimestampMixin,
    VersionMixin,
    ArchiveMixin,
    _MixinTestBase,
):
    __tablename__ = "mutable_records"

    name: Mapped[str] = mapped_column(sa.String(40), nullable=False)


def _alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


class _RevisionModule(Protocol):
    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


def _revision_modules() -> list[_RevisionModule]:
    scripts = ScriptDirectory.from_config(_alembic_config())
    newest_first = scripts.walk_revisions(base="base", head="heads")
    return [cast(_RevisionModule, script.module) for script in reversed(list(newest_first))]


def _run_upgrades(context: MigrationContext) -> None:
    with Operations.context(context):
        for revision in _revision_modules():
            revision.upgrade()


def _run_downgrades(context: MigrationContext) -> None:
    with Operations.context(context):
        for revision in reversed(_revision_modules()):
            revision.downgrade()


def _inserted_uuid(result: Any) -> UUID:
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    return cast(UUID, primary_key[0])


def test_graph_metadata_has_only_global_facts_and_portable_ddl() -> None:
    assert set(Position.__table__.columns.keys()) == {
        "id",
        "created_at",
        "position_key",
        "canonical_fen",
        "piece_placement",
        "side_to_move",
        "castling_rights",
        "en_passant",
        "material_signature",
    }
    assert set(MoveEdge.__table__.columns.keys()) == {
        "id",
        "created_at",
        "from_position_id",
        "to_position_id",
        "uci",
        "san",
    }
    assert {
        "full_fen",
        "version",
        "updated_at",
        "archived_at",
        "nag",
        "sort_order",
        "comment",
        "context",
    }.isdisjoint(set(Position.__table__.columns.keys()) | set(MoveEdge.__table__.columns.keys()))

    sqlite_ddl = "\n".join(
        str(CreateTable(table).compile(dialect=sqlite.dialect()))
        for table in Base.metadata.sorted_tables
    )
    mysql_ddl = "\n".join(
        str(CreateTable(table).compile(dialect=mysql.dialect()))
        for table in Base.metadata.sorted_tables
    )

    assert "ON DELETE RESTRICT" in sqlite_ddl
    assert "UNIQUE (from_position_id, uci)" in sqlite_ddl
    assert "ENGINE=InnoDB" in mysql_ddl
    assert "CHARACTER SET ascii COLLATE ascii_bin" in mysql_ddl
    assert "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" in mysql_ddl
    assert "DATETIME(6) NOT NULL" in mysql_ddl
    assert "ON DELETE RESTRICT" in mysql_ddl


def test_content_metadata_has_lifecycle_context_and_restrictive_foreign_keys() -> None:
    mutable_tables = {
        "courses",
        "course_modules",
        "course_occurrences",
        "course_content_blocks",
        "sources",
        "source_versions",
        "source_files",
        "source_spans",
        "knowledge_notes",
    }
    lifecycle_columns = {"id", "created_at", "updated_at", "version", "archived_at"}

    for table_name in mutable_tables:
        assert lifecycle_columns <= set(Base.metadata.tables[table_name].columns.keys())

    occurrence_columns = set(Base.metadata.tables["course_occurrences"].columns.keys())
    assert {"course_id", "position_id", "full_fen", "nag", "sort_order", "context"} <= (
        occurrence_columns
    )
    assert set(Base.metadata.tables["knowledge_note_citations"].columns.keys()) == {
        "knowledge_note_id",
        "source_span_id",
        "created_at",
    }
    assert set(Base.metadata.tables["course_content_block_citations"].columns.keys()) == {
        "course_content_block_id",
        "source_span_id",
        "created_at",
    }

    foreign_keys = [
        constraint
        for table in Base.metadata.tables.values()
        for constraint in table.foreign_key_constraints
    ]
    assert foreign_keys
    assert {constraint.ondelete for constraint in foreign_keys} == {"RESTRICT"}

    constraint_names = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert max(map(len, constraint_names)) <= 64
    assert not any("ck_courses_ck_courses" in name for name in constraint_names)
    note_checks = {
        str(constraint.sqltext)
        for constraint in Base.metadata.tables["knowledge_notes"].constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert any("note_type IN" in expression for expression in note_checks)
    assert any(
        "source_note_id IS NULL AND markdown IS NOT NULL" in expression
        for expression in note_checks
    )
    assert Base.metadata.tables["knowledge_notes"].c.markdown.nullable
    assert any(
        isinstance(constraint, sa.UniqueConstraint)
        and tuple(column.name for column in constraint.columns)
        == ("occurrence_id", "source_note_id")
        for constraint in Base.metadata.tables["knowledge_notes"].constraints
    )


async def test_position_and_move_edge_round_trip_with_domain_state(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'round-trip.db'}")
    before = PositionState(START_FEN)
    result = before.apply_uci("e2e4")
    source = Position.from_state(before)
    target = Position.from_state(result.after)

    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with database.session() as session:
            session.add_all([source, target])
            await session.flush()
            edge = MoveEdge(
                from_position_id=source.id,
                to_position_id=target.id,
                uci=result.uci,
                san=result.san,
            )
            session.add(edge)
            await session.commit()
            source_id = source.id
            edge_id = edge.id

        async with database.session() as session:
            stored_position = await session.get(Position, source_id)
            stored_edge = await session.get(MoveEdge, edge_id)

        assert stored_position is not None
        assert stored_edge is not None
        assert isinstance(stored_position.id, UUID)
        assert stored_position.position_key == before.position_key
        assert stored_position.canonical_fen == before.canonical_fen
        assert stored_position.created_at.tzinfo is UTC
        assert stored_edge.from_position_id == source_id
        assert stored_edge.to_position_id == target.id
        assert stored_edge.uci == "e2e4"
        assert stored_edge.san == "e4"
        assert stored_edge.created_at.tzinfo is UTC
    finally:
        await database.close()


async def test_database_rejects_duplicate_facts_and_restricted_delete(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'constraints.db'}")
    before = PositionState(START_FEN)
    result = before.apply_uci("e2e4")

    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with database.session() as session:
            source = Position.from_state(before)
            target = Position.from_state(result.after)
            session.add_all([source, target])
            await session.flush()
            edge = MoveEdge(
                from_position_id=source.id,
                to_position_id=target.id,
                uci=result.uci,
                san=result.san,
            )
            session.add(edge)
            await session.commit()
            source_id = source.id
            target_id = target.id

        async with database.session() as session:
            session.add(Position.from_state(before))
            with pytest.raises(IntegrityError):
                await session.commit()

        async with database.session() as session:
            session.add(
                MoveEdge(
                    from_position_id=source_id,
                    to_position_id=target_id,
                    uci=result.uci,
                    san=result.san,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()

        async with database.session() as session:
            with pytest.raises(IntegrityError):
                await session.execute(sa.delete(Position).where(Position.id == source_id))
                await session.commit()
    finally:
        await database.close()


async def test_mutable_entity_mixins_use_uuid_utc_versioning_and_archive(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'mixins.db'}")
    archived_at = datetime(2026, 8, 6, 10, 30, tzinfo=timezone(timedelta(hours=8)))

    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(_MixinTestBase.metadata.create_all)

        async with database.session() as session:
            record = _MutableRecord(name="draft")
            session.add(record)
            await session.commit()
            record_id = record.id
            first_updated_at = record.updated_at

            record.name = "published"
            record.archived_at = archived_at
            await session.commit()

            assert record.version == 2
            assert record.updated_at >= first_updated_at

        async with database.session() as session:
            stored = await session.get(_MutableRecord, record_id)

        assert stored is not None
        assert isinstance(stored.id, UUID)
        assert stored.created_at.tzinfo is UTC
        assert stored.updated_at.tzinfo is UTC
        assert stored.archived_at == archived_at.astimezone(UTC)
        assert stored.version == 2
    finally:
        await database.close()


def test_utc_datetime_normalizes_values_and_rejects_naive_input() -> None:
    column_type = UTCDateTime()
    dialect = sqlite.dialect()
    local_value = datetime(2026, 8, 6, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    naive_utc = datetime(2026, 8, 6, 2, 30)

    assert column_type.process_bind_param(None, dialect) is None
    assert column_type.process_result_value(None, dialect) is None
    assert column_type.process_bind_param(local_value, dialect) == naive_utc
    assert column_type.process_result_value(naive_utc, dialect) == naive_utc.replace(tzinfo=UTC)
    assert column_type.process_result_value(local_value, dialect) == local_value.astimezone(UTC)

    with pytest.raises(ValueError, match="require an aware datetime"):
        column_type.process_bind_param(naive_utc, dialect)


def test_sync_sqlite_migrations_match_metadata_enforce_checks_and_downgrade() -> None:
    engine = sa.create_engine("sqlite://")

    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "target_metadata": Base.metadata,
                    "compare_type": True,
                    "compare_server_default": True,
                },
            )
            _run_upgrades(context)

            assert compare_metadata(context, Base.metadata) == []
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) == set(Base.metadata.tables)
            assert "full_fen" not in {
                column["name"] for column in inspector.get_columns("positions")
            }
            for table_name in Base.metadata.tables:
                for foreign_key in inspector.get_foreign_keys(table_name):
                    assert foreign_key["options"].get("ondelete") == "RESTRICT"

            source_id = _inserted_uuid(
                connection.execute(
                    sa.insert(Source).values(
                        kind="book",
                        title="Constraint source",
                        updated_at=datetime.now(UTC),
                    )
                )
            )
            source_version_id = _inserted_uuid(
                connection.execute(
                    sa.insert(SourceVersion).values(
                        source_id=source_id,
                        label="v1",
                        updated_at=datetime.now(UTC),
                    )
                )
            )

            invalid_locators = (
                {"locator_kind": "page", "page_number": None},
                {"locator_kind": "video", "start_value": None, "end_value": 10},
                {"locator_kind": "text", "start_value": 0, "end_value": None},
            )
            for locator in invalid_locators:
                values = {
                    "source_version_id": source_version_id,
                    "source_file_id": None,
                    "page_number": None,
                    "bbox": None,
                    "start_value": None,
                    "end_value": None,
                    "quote": None,
                    "ocr_text": None,
                    "confidence": None,
                    **locator,
                }
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(sa.insert(SourceSpan).values(**values))

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(SourceSpan).values(
                        source_version_id=source_version_id,
                        source_file_id=None,
                        locator_kind="page",
                        page_number=1,
                    )
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    sa.insert(Course).values(title="Invalid mode", mode="not-a-mode")
                )

            _run_downgrades(context)
            assert sa.inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_migrations_render_mysql_specific_ddl() -> None:
    assert len(_revision_modules()) == 15
    output = StringIO()
    context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={
            "as_sql": True,
            "output_buffer": output,
            "target_metadata": Base.metadata,
        },
    )

    _run_upgrades(context)
    ddl = output.getvalue()
    foreign_key_count = sum(
        len(table.foreign_key_constraints) for table in Base.metadata.tables.values()
    )

    assert ddl.count("ENGINE=InnoDB") == len(Base.metadata.tables)
    assert "CHARACTER SET ascii COLLATE ascii_bin" in ddl
    assert "CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" in ddl
    assert "DATETIME(6) NOT NULL" in ddl
    assert ddl.count("ON DELETE RESTRICT") == foreign_key_count
    assert "ck_courses_ck_courses_status" not in ddl
    assert "fk_course_occurrences_inbound_move_edge_id_move_edges" in ddl

    downgrade_output = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect=mysql.dialect(),
        opts={"as_sql": True, "output_buffer": downgrade_output},
    )
    _run_downgrades(downgrade_context)
    downgrade_ddl = downgrade_output.getvalue()

    assert downgrade_ddl.count("DROP TABLE") == len(Base.metadata.tables)
    # MySQL error 1553: cannot drop an index still needed by an FK
    # constraint. DROP TABLE already cleans ordinary indexes on InnoDB.
    # Revision 0004 legitimately removes its new ``uq_`` constraint when
    # downgrading only to 0003, but no old ``ix_`` may be dropped explicitly.
    assert "DROP INDEX ix_" not in downgrade_ddl, (
        "downgrade DDL explicitly drops an ordinary/FK-supporting index; "
        "DROP TABLE on InnoDB handles those indexes (error 1553 otherwise)"
    )


def test_stage8_models_are_registered_and_exported() -> None:
    """The Stage 8A persistence models import and register their exact tables."""

    from chess_workbench.store.models import (
        ExtractionArtifact,
        ExtractionRun,
        PdfAsset,
    )

    assert {
        PdfAsset.__tablename__,
        ExtractionRun.__tablename__,
        ExtractionArtifact.__tablename__,
    } <= (set(Base.metadata.tables))
    assert set(Base.metadata.tables["pdf_assets"].columns.keys()) == {
        "id",
        "created_at",
        "content_sha256",
        "byte_size",
        "page_count",
        "source_id",
        "source_version_id",
        "source_file_id",
    }


def test_stage2d_migration_removes_legacy_reference_markdown_cache() -> None:
    """A real 0003 reference row upgrades without retaining copied content."""
    engine = sa.create_engine("sqlite://")
    revisions = _revision_modules()

    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for revision in revisions[:3]:
                    revision.upgrade()

                position = Position.from_state(PositionState(START_FEN))
                position_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(Position).values(
                            position_key=position.position_key,
                            canonical_fen=position.canonical_fen,
                            piece_placement=position.piece_placement,
                            side_to_move=position.side_to_move,
                            castling_rights=position.castling_rights,
                            en_passant=position.en_passant,
                            material_signature=position.material_signature,
                        )
                    )
                )
                traditional_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(Course).values(
                            title="Book",
                            mode="traditional",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                explorer_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(Course).values(
                            title="Explorer",
                            mode="opening_explorer",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                traditional_occurrence_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(CourseOccurrence).values(
                            course_id=traditional_id,
                            position_id=position_id,
                            full_fen=START_FEN,
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                explorer_occurrence_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(CourseOccurrence).values(
                            course_id=explorer_id,
                            position_id=position_id,
                            full_fen=START_FEN,
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                source_note_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(KnowledgeNote).values(
                            scope="course",
                            target_kind="occurrence",
                            occurrence_id=traditional_occurrence_id,
                            markdown="Authoritative text",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                reference_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(KnowledgeNote).values(
                            scope="course",
                            target_kind="occurrence",
                            occurrence_id=explorer_occurrence_id,
                            source_note_id=source_note_id,
                            markdown="Legacy copied text",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )

                revisions[3].upgrade()

            migrated_markdown = connection.scalar(
                sa.select(KnowledgeNote.markdown).where(KnowledgeNote.id == reference_id)
            )
            assert migrated_markdown is None
    finally:
        engine.dispose()


def test_stage4_block_migration_backfills_existing_module_root() -> None:
    """Every pre-Stage-4 Module root becomes one explicit MoveSequence block."""
    engine = sa.create_engine("sqlite://")
    revisions = _revision_modules()

    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for revision in revisions[:5]:
                    revision.upgrade()
                position = Position.from_state(PositionState(START_FEN))
                position_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(Position).values(
                            position_key=position.position_key,
                            canonical_fen=position.canonical_fen,
                            piece_placement=position.piece_placement,
                            side_to_move=position.side_to_move,
                            castling_rights=position.castling_rights,
                            en_passant=position.en_passant,
                            material_signature=position.material_signature,
                        )
                    )
                )
                course_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(Course).values(
                            title="Existing PGN course",
                            mode="traditional",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                module_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(CourseModule).values(
                            course_id=course_id,
                            title="Existing game",
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                root_id = _inserted_uuid(
                    connection.execute(
                        sa.insert(CourseOccurrence).values(
                            course_id=course_id,
                            module_id=module_id,
                            position_id=position_id,
                            full_fen=START_FEN,
                            updated_at=datetime.now(UTC),
                        )
                    )
                )
                revisions[5].upgrade()

            blocks = connection.execute(sa.select(CourseContentBlock)).mappings().all()
            assert len(blocks) == 1
            assert blocks[0]["module_id"] == module_id
            assert blocks[0]["kind"] == "move_sequence"
            assert blocks[0]["sort_order"] == 0
            assert blocks[0]["root_occurrence_id"] == root_id
    finally:
        engine.dispose()
