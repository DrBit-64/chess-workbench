from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chess_workbench.store.base import Base
from chess_workbench.store.models.mixins import UTCCreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from chess_workbench.domain.position_identity import PositionState


def _ascii_string(length: int) -> String:
    """Use case-sensitive ASCII identity columns on both supported dialects."""

    return String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
        "mysql",
    )


class Position(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable canonical identity shared by every occurrence of a position."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("position_key", name="uq_positions_position_key"),
        CheckConstraint("side_to_move IN ('w', 'b')", name="side_to_move"),
        CheckConstraint(
            "castling_rights = '-' OR "
            "(length(castling_rights) BETWEEN 1 AND 4 AND "
            "castling_rights NOT LIKE '%-%')",
            name="castling_rights",
        ),
        CheckConstraint(
            "en_passant = '-' OR "
            "(length(en_passant) = 2 AND "
            "substr(en_passant, 1, 1) IN ('a','b','c','d','e','f','g','h') AND "
            "substr(en_passant, 2, 1) IN ('3','6'))",
            name="en_passant",
        ),
        CheckConstraint("canonical_fen LIKE '% 0 1'", name="canonical_fen_counters"),
        CheckConstraint("length(piece_placement) > 0", name="piece_placement_nonempty"),
        CheckConstraint("length(material_signature) > 0", name="material_signature_nonempty"),
        {"mysql_engine": "InnoDB"},
    )

    position_key: Mapped[str] = mapped_column(_ascii_string(160), nullable=False)
    canonical_fen: Mapped[str] = mapped_column(_ascii_string(128), nullable=False)
    piece_placement: Mapped[str] = mapped_column(_ascii_string(80), nullable=False)
    side_to_move: Mapped[str] = mapped_column(_ascii_string(1), nullable=False)
    castling_rights: Mapped[str] = mapped_column(_ascii_string(4), nullable=False)
    en_passant: Mapped[str] = mapped_column(_ascii_string(2), nullable=False)
    material_signature: Mapped[str] = mapped_column(_ascii_string(64), nullable=False)

    outgoing_edges: Mapped[list[MoveEdge]] = relationship(
        back_populates="from_position",
        foreign_keys="MoveEdge.from_position_id",
        passive_deletes=True,
    )
    incoming_edges: Mapped[list[MoveEdge]] = relationship(
        back_populates="to_position",
        foreign_keys="MoveEdge.to_position_id",
        passive_deletes=True,
    )

    @classmethod
    def from_state(cls, state: PositionState) -> Position:
        """Create the persistence representation of a validated domain state."""

        return cls(
            position_key=state.position_key,
            canonical_fen=state.canonical_fen,
            piece_placement=state.piece_placement,
            side_to_move=state.side_to_move,
            castling_rights=state.castling_rights,
            en_passant=state.en_passant,
            material_signature=state.material_signature,
        )


class MoveEdge(UUIDPrimaryKeyMixin, UTCCreatedAtMixin, Base):
    """Immutable legal-move fact in the global position graph.

    Course ordering, NAGs, comments, sources and other teaching context belong
    to course occurrences, never to this shared edge.
    """

    __tablename__ = "move_edges"
    __table_args__ = (
        UniqueConstraint("from_position_id", "uci", name="uq_move_edges_from_uci"),
        CheckConstraint("from_position_id <> to_position_id", name="different_positions"),
        CheckConstraint("length(uci) IN (4, 5)", name="uci_length"),
        CheckConstraint("lower(uci) = uci", name="uci_lowercase"),
        CheckConstraint("length(san) > 0", name="san_nonempty"),
        Index("ix_move_edges_to_position_id", "to_position_id"),
        {"mysql_engine": "InnoDB"},
    )

    from_position_id: Mapped[UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="RESTRICT", name="fk_move_edges_from_position_id"),
        nullable=False,
    )
    to_position_id: Mapped[UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="RESTRICT", name="fk_move_edges_to_position_id"),
        nullable=False,
    )
    uci: Mapped[str] = mapped_column(_ascii_string(5), nullable=False)
    san: Mapped[str] = mapped_column(String(32), nullable=False)

    from_position: Mapped[Position] = relationship(
        back_populates="outgoing_edges",
        foreign_keys=[from_position_id],
    )
    to_position: Mapped[Position] = relationship(
        back_populates="incoming_edges",
        foreign_keys=[to_position_id],
    )
