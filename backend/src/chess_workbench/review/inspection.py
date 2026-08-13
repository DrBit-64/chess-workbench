"""Pure consumer-side CCEF review inspection (packet DS-STAGE8D-REVIEW-INSPECTION-01).

Turns one already validated, locally normalized CCEF package into a
deterministic ordered list of review issues.  This module performs no I/O,
does not load an artifact, create a review session, expose HTTP, write SQL or
render UI, and never mutates its input.
"""

from __future__ import annotations

import copy
import re
from typing import Annotated, Literal

import chess
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..extraction.contracts import (
    DiagnosticCode,
    EvidenceRef,
    ExtractionPackage,
    ExtractionWarning,
    FenPosition,
    FigureItem,
    HeadingItem,
    LocalId,
    MoveSequenceItem,
    PositionAnchor,
    ProseItem,
    StartPosition,
    UnresolvedItem,
)

REVIEW_INSPECTION_VERSION: Literal["ccef-review-inspection/1.0"] = "ccef-review-inspection/1.0"

ReviewIssueScope = Literal["item", "node", "diagnostic"]
ReviewIssueSeverity = Literal["warning", "error"]

_HEADING_TOO_LONG_MESSAGE = "Heading exceeds the publishable 200-character limit"
_POSITION_ANCHOR_NO_MATCH_MESSAGE = "Position anchor has no candidate occurrence"
_POSITION_ANCHOR_AMBIGUOUS_MESSAGE = "Position anchor matches multiple candidate occurrences"
_UNSUPPORTED_FIGURE_MESSAGE = "Non-chess figures require an explicit rejection before publication"
_CHESSBOARD_POSITION_UNRESOLVED_MESSAGE = (
    "Chessboard figure does not contain a valid standard position"
)
_MOVE_NOT_PUBLISHABLE_MESSAGE = "Move is not publishable in its current state"
_MULTIPLE_NAGS_MESSAGE = "Multiple NAGs require an explicit reviewer choice"
_UNRESOLVED_MESSAGE = "Unresolved content requires review"
_NOT_NORMALIZED_MESSAGE = "review candidate must be locally normalized"

# Standard-chess castling rights: canonical ordered K?Q?k?q? form or ``-``.
# Shredder-FEN castling letters and any other ordering are rejected.
_STANDARD_CASTLING = re.compile(r"(?:K?Q?k?q?|-)")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ReviewIssue(_StrictModel):
    issue_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9._:-]{0,511}$")]
    scope: ReviewIssueScope
    severity: ReviewIssueSeverity
    blocking: bool
    item_id: LocalId | None
    node_id: LocalId | None
    code: DiagnosticCode
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    evidence: tuple[EvidenceRef, ...] = ()


class ReviewInspection(_StrictModel):
    inspection_version: Literal["ccef-review-inspection/1.0"] = REVIEW_INSPECTION_VERSION
    item_count: Annotated[int, Field(ge=0)]
    move_node_count: Annotated[int, Field(ge=0)]
    issue_count: Annotated[int, Field(ge=0)]
    blocking_issue_count: Annotated[int, Field(ge=0)]
    issues: tuple[ReviewIssue, ...] = ()


def _issue(
    *,
    issue_id: str,
    scope: ReviewIssueScope,
    severity: ReviewIssueSeverity,
    blocking: bool,
    item_id: LocalId | None,
    node_id: LocalId | None,
    code: DiagnosticCode,
    message: str,
    evidence: tuple[EvidenceRef, ...],
) -> ReviewIssue:
    return ReviewIssue(
        issue_id=issue_id,
        scope=scope,
        severity=severity,
        blocking=blocking,
        item_id=item_id,
        node_id=node_id,
        code=code,
        message=message,
        evidence=evidence,
    )


def _copied_evidence(refs: tuple[EvidenceRef, ...] | list[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    return tuple(copy.deepcopy(ref) for ref in refs)


def _canonical_fen(fen: str) -> str | None:
    """Canonical standard full FEN, or None when invalid/non-standard.

    Mirrors the extraction normalizer's standard-position validity boundary:
    exactly six fields, no promoted-piece ``~`` marker, ordered standard
    castling letters or ``-``, a constructible standard ``chess.Board`` and
    ``board.is_valid()``.  Every failure returns None.
    """
    fields = fen.split()
    if len(fields) != 6:
        return None
    placement, _, castling, *_ = fields
    if "~" in placement:
        return None
    if _STANDARD_CASTLING.fullmatch(castling) is None:
        return None
    try:
        board = chess.Board(fen, chess960=False)
    except ValueError:
        return None
    if not board.is_valid():
        return None
    return board.fen(en_passant="fen")


def _occurrence_positions(package: ExtractionPackage) -> list[str]:
    """Every candidate occurrence position package-wide, duplicates preserved."""
    positions: list[str] = []
    for item in package.items:
        if not isinstance(item, MoveSequenceItem):
            continue
        initial = item.initial_position
        if isinstance(initial, StartPosition):
            positions.append(chess.Board().fen(en_passant="fen"))
        elif isinstance(initial, FenPosition):
            canonical = _canonical_fen(initial.fen)
            if canonical is not None:
                positions.append(canonical)
        for node in item.nodes:
            if node.validation_status == "valid" and node.fen_after is not None:
                canonical = _canonical_fen(node.fen_after)
                if canonical is not None:
                    positions.append(canonical)
    return positions


def _raise_if_not_normalized(package: ExtractionPackage) -> None:
    for item in package.items:
        if not isinstance(item, MoveSequenceItem):
            continue
        if any(node.validation_status == "unvalidated" for node in item.nodes):
            raise ValueError(_NOT_NORMALIZED_MESSAGE)


def _append_item_warnings(
    issues: list[ReviewIssue], item_id: LocalId, warnings: list[ExtractionWarning]
) -> None:
    for index, warning in enumerate(warnings):
        issues.append(
            _issue(
                issue_id=f"item:{item_id}:warning:{index}",
                scope="item",
                severity="warning",
                blocking=False,
                item_id=item_id,
                node_id=None,
                code=warning.code,
                message=warning.message,
                evidence=_copied_evidence(warning.evidence),
            )
        )


def inspect_review_candidate(package: ExtractionPackage) -> ReviewInspection:
    """Inspect one locally normalized package and return ordered review issues."""
    if type(package) is not ExtractionPackage:
        raise TypeError("package must be ExtractionPackage")
    _raise_if_not_normalized(package)

    occurrences = _occurrence_positions(package)
    issues: list[ReviewIssue] = []
    move_node_count = 0

    for item in package.items:
        if isinstance(item, MoveSequenceItem):
            move_node_count += len(item.nodes)

        # 1. Item warnings in original order.
        _append_item_warnings(issues, item.id, item.warnings)

        # 2. Derived item issues.
        if isinstance(item, HeadingItem):
            if len(item.text) > 200:
                issues.append(
                    _issue(
                        issue_id=f"item:{item.id}:heading-too-long",
                        scope="item",
                        severity="error",
                        blocking=True,
                        item_id=item.id,
                        node_id=None,
                        code="heading_too_long",
                        message=_HEADING_TOO_LONG_MESSAGE,
                        evidence=_copied_evidence(item.evidence),
                    )
                )
        elif isinstance(item, ProseItem) and isinstance(item.anchor, PositionAnchor):
            anchor_canonical = _canonical_fen(item.anchor.fen)
            matches = (
                0
                if anchor_canonical is None
                else sum(1 for position in occurrences if position == anchor_canonical)
            )
            if matches == 0:
                issues.append(
                    _issue(
                        issue_id=f"item:{item.id}:position-anchor-no-match",
                        scope="item",
                        severity="error",
                        blocking=True,
                        item_id=item.id,
                        node_id=None,
                        code="position_anchor_no_match",
                        message=_POSITION_ANCHOR_NO_MATCH_MESSAGE,
                        evidence=_copied_evidence(item.evidence),
                    )
                )
            elif matches > 1:
                issues.append(
                    _issue(
                        issue_id=f"item:{item.id}:position-anchor-ambiguous",
                        scope="item",
                        severity="error",
                        blocking=True,
                        item_id=item.id,
                        node_id=None,
                        code="position_anchor_ambiguous",
                        message=_POSITION_ANCHOR_AMBIGUOUS_MESSAGE,
                        evidence=_copied_evidence(item.evidence),
                    )
                )
        elif isinstance(item, FigureItem):
            if item.figure_type != "chessboard":
                issues.append(
                    _issue(
                        issue_id=f"item:{item.id}:unsupported-figure",
                        scope="item",
                        severity="error",
                        blocking=True,
                        item_id=item.id,
                        node_id=None,
                        code="unsupported_figure",
                        message=_UNSUPPORTED_FIGURE_MESSAGE,
                        evidence=_copied_evidence(item.evidence),
                    )
                )
            elif (
                item.position_fen_candidate is None
                or _canonical_fen(item.position_fen_candidate) is None
            ):
                issues.append(
                    _issue(
                        issue_id=f"item:{item.id}:chessboard-position-unresolved",
                        scope="item",
                        severity="error",
                        blocking=True,
                        item_id=item.id,
                        node_id=None,
                        code="chessboard_position_unresolved",
                        message=_CHESSBOARD_POSITION_UNRESOLVED_MESSAGE,
                        evidence=_copied_evidence(item.evidence),
                    )
                )
        elif isinstance(item, UnresolvedItem):
            # The fixed summary message is auditable; the full details/raw_text
            # stay available on the immutable package item for the review UI.
            issues.append(
                _issue(
                    issue_id=f"item:{item.id}:unresolved",
                    scope="item",
                    severity="error",
                    blocking=True,
                    item_id=item.id,
                    node_id=None,
                    code=item.reason_code,
                    message=_UNRESOLVED_MESSAGE,
                    evidence=_copied_evidence(item.evidence),
                )
            )

        # 3. Move sequence nodes in topology/source order.
        if isinstance(item, MoveSequenceItem):
            for node in item.nodes:
                if node.validation_status in ("invalid", "ambiguous"):
                    issues.append(
                        _issue(
                            issue_id=f"node:{item.id}:{node.id}:status",
                            scope="node",
                            severity="error",
                            blocking=True,
                            item_id=item.id,
                            node_id=node.id,
                            code=(
                                "move_invalid"
                                if node.validation_status == "invalid"
                                else "move_ambiguous"
                            ),
                            message=_MOVE_NOT_PUBLISHABLE_MESSAGE,
                            evidence=_copied_evidence(node.evidence),
                        )
                    )
                for index, warning in enumerate(node.warnings):
                    issues.append(
                        _issue(
                            issue_id=f"node:{item.id}:{node.id}:warning:{index}",
                            scope="node",
                            severity="warning",
                            blocking=False,
                            item_id=item.id,
                            node_id=node.id,
                            code=warning.code,
                            message=warning.message,
                            evidence=_copied_evidence(warning.evidence),
                        )
                    )
                if len(node.nags) > 1:
                    issues.append(
                        _issue(
                            issue_id=f"node:{item.id}:{node.id}:multiple-nags",
                            scope="node",
                            severity="error",
                            blocking=True,
                            item_id=item.id,
                            node_id=node.id,
                            code="multiple_nags",
                            message=_MULTIPLE_NAGS_MESSAGE,
                            evidence=_copied_evidence(node.evidence),
                        )
                    )

    # Diagnostics in original order; info ignored; warning/error kept.
    for index, diagnostic in enumerate(package.diagnostics):
        if diagnostic.severity == "info":
            continue
        issues.append(
            _issue(
                issue_id=f"diagnostic:{index}",
                scope="diagnostic",
                severity=diagnostic.severity,
                blocking=diagnostic.severity == "error",
                item_id=diagnostic.item_id,
                node_id=diagnostic.node_id,
                code=diagnostic.code,
                message=diagnostic.message,
                evidence=_copied_evidence(diagnostic.evidence),
            )
        )

    return ReviewInspection(
        item_count=len(package.items),
        move_node_count=move_node_count,
        issue_count=len(issues),
        blocking_issue_count=sum(1 for issue in issues if issue.blocking),
        issues=tuple(issues),
    )


__all__ = [
    "REVIEW_INSPECTION_VERSION",
    "ReviewInspection",
    "ReviewIssue",
    "ReviewIssueScope",
    "ReviewIssueSeverity",
    "inspect_review_candidate",
]
