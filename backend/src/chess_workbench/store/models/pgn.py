"""Immutable PGN source/provenance adapter records."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin


def _ascii_string(length: int) -> String:
    return String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class PgnAsset(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "pgn_assets"
    __table_args__ = (
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        UniqueConstraint("content_sha256", name="uq_pgn_assets_content_sha256"),
        UniqueConstraint("source_id", name="uq_pgn_assets_source_id"),
        UniqueConstraint("source_version_id", name="uq_pgn_assets_source_version_id"),
        UniqueConstraint("source_file_id", name="uq_pgn_assets_source_file_id"),
        {"mysql_engine": "InnoDB"},
    )

    content_sha256: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="RESTRICT"), nullable=False
    )


class PgnImport(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "pgn_imports"
    __table_args__ = (
        CheckConstraint("length(effective_key_hash) = 64", name="key_hash_length"),
        CheckConstraint("length(logical_fingerprint) = 64", name="fingerprint_length"),
        CheckConstraint("game_count >= 1", name="game_count_positive"),
        CheckConstraint("occurrence_count >= game_count", name="occurrence_count_valid"),
        CheckConstraint("course_version >= 1", name="course_version_positive"),
        UniqueConstraint("effective_key_hash", name="uq_pgn_imports_effective_key_hash"),
        {"mysql_engine": "InnoDB"},
    )

    effective_key_hash: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    logical_fingerprint: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("pgn_assets.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    game_count: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    course_version: Mapped[int] = mapped_column(Integer, nullable=False)


class PgnImportGame(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    __tablename__ = "pgn_import_games"
    __table_args__ = (
        CheckConstraint("game_index >= 0", name="game_index_nonnegative"),
        CheckConstraint("occurrence_count >= 1", name="occurrence_count_positive"),
        CheckConstraint("movetext_result IN ('1-0','0-1','1/2-1/2','*')", name="result"),
        CheckConstraint("length(semantic_hash) = 64", name="semantic_hash_length"),
        UniqueConstraint("pgn_import_id", "game_index", name="uq_pgn_import_games_index"),
        UniqueConstraint("module_id", name="uq_pgn_import_games_module_id"),
        UniqueConstraint("root_occurrence_id", name="uq_pgn_import_games_root_id"),
        UniqueConstraint("source_span_id", name="uq_pgn_import_games_span_id"),
        {"mysql_engine": "InnoDB"},
    )

    pgn_import_id: Mapped[UUID] = mapped_column(
        ForeignKey("pgn_imports.id", ondelete="RESTRICT"), nullable=False
    )
    game_index: Mapped[int] = mapped_column(Integer, nullable=False)
    module_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_modules.id", ondelete="RESTRICT"), nullable=False
    )
    root_occurrence_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_occurrences.id", ondelete="RESTRICT"), nullable=False
    )
    source_span_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_spans.id", ondelete="RESTRICT"), nullable=False
    )
    headers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    movetext_result: Mapped[str] = mapped_column(String(9), nullable=False)
    semantic_hash: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)


class PgnOccurrenceAnnotation(UTCCreatedAtMixin, Base):
    __tablename__ = "pgn_occurrence_annotations"
    __table_args__ = ({"mysql_engine": "InnoDB"},)

    occurrence_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_occurrences.id", ondelete="RESTRICT"), primary_key=True
    )
    pgn_import_game_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "pgn_import_games.id",
            ondelete="RESTRICT",
            name="fk_pgn_annotations_import_game",
        ),
        nullable=False,
    )
    nags: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    starting_comment: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
