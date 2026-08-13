"""Focused tests for the pure Stage 8D review inspection (DS-STAGE8D-REVIEW-INSPECTION-01).

Covers: clean zero-issue packages; exact deterministic issue ordering across
item warnings, heading limits, node status/warning/multi-NAG, unresolved items
and warning/error diagnostics (with info excluded); position anchors with
zero/one/multiple canonical full-FEN matches including duplicate positions;
chessboard/non-chess figure behavior; unvalidated-node and exact-type misuse
rejection; determinism, input non-mutation, deep-copied evidence, frozen /
strict / unknown-field model behavior and unique stable issue IDs.  All
packages are synthetic and non-copyrighted; no filesystem, network, clock,
randomness, SQL or provider call is used.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from chess_workbench.extraction.contracts import ExtractionPackage, UnresolvedItem
from chess_workbench.extraction.validation import normalize_chess_moves
from chess_workbench.review import (
    REVIEW_INSPECTION_VERSION,
    ReviewInspection,
    ReviewIssue,
    inspect_review_candidate,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
EMPTY_FEN = "8/8/8/8/8/8/8/8 w - - 0 1"
INVALID_FEN = "rnbqkbnr/pppppppp/9/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# Canonical fen_after of the valid non-root node after 1. e4 e5.
AFTER_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
# Promoted-piece marker ``~`` in the placement field (non-standard).
PROMOTED_MARKER_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP~/RNBQKBNR w KQkq - 0 1"
# Shredder-FEN (Chess960) castling letters (non-standard for chess960=False).
CHESS960_CASTLING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w HAha - 0 1"

_HEADING_LIMIT = "x" * 201


def _node(
    node_id: str,
    parent_id: str | None,
    order: int,
    move_text: str,
    **extra: Any,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": order,
        "move_text": move_text,
        "evidence": [{"page": 1}],
    }
    data.update(extra)
    return data


def _sequence_payload(nodes: list[dict[str, Any]], seq_id: str = "seq1") -> dict[str, Any]:
    return {
        "kind": "move_sequence",
        "id": seq_id,
        "evidence": [{"page": 1}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
    }


def _package_payload(
    items: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {"source_ref": "opaque-ref-1", "media_type": "application/pdf"},
        "items": items,
        "diagnostics": diagnostics or [],
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }


def _normalized(payload: dict[str, Any]) -> ExtractionPackage:
    return normalize_chess_moves(ExtractionPackage.model_validate(payload))


def _inspect(payload: dict[str, Any]) -> ReviewInspection:
    return inspect_review_candidate(_normalized(payload))


def _issue_ids(inspection: ReviewInspection) -> list[str]:
    return [issue.issue_id for issue in inspection.issues]


# ---------------------------------------------------------------------------
# 1. Clean normalized package -> zero issues
# ---------------------------------------------------------------------------


def test_clean_normalized_package_has_zero_issues() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Chapter 1",
                "evidence": [{"page": 1}],
            },
            {"kind": "prose", "id": "p1", "text": "Opening principles", "evidence": [{"page": 1}]},
            _sequence_payload([_node("n1", None, 0, "e4"), _node("n2", "n1", 0, "e5")]),
        ],
        diagnostics=[{"severity": "info", "code": "note", "message": "informational"}],
    )
    inspection = _inspect(payload)

    assert inspection.inspection_version == REVIEW_INSPECTION_VERSION
    assert inspection.item_count == 3
    assert inspection.move_node_count == 2
    assert inspection.issue_count == 0
    assert inspection.blocking_issue_count == 0
    assert inspection.issues == ()


# ---------------------------------------------------------------------------
# 2. Exact deterministic issue ordering
# ---------------------------------------------------------------------------


def test_issue_ordering_across_all_sources_is_exact() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": _HEADING_LIMIT,
                "evidence": [{"page": 1}],
                "warnings": [
                    {"code": "low_confidence", "message": "low", "evidence": [{"page": 1}]}
                ],
            },
            _sequence_payload(
                [
                    _node("n1", None, 0, "e4", nags=[1, 2]),
                    _node("n2", "n1", 0, "Ke5", nags=[1, 2]),
                ],
                seq_id="seq1",
            ),
            {
                "kind": "unresolved",
                "id": "u1",
                "unresolved_type": "text",
                "reason_code": "ocr_unclear",
                "raw_text": "???",
                "evidence": [{"page": 1}],
            },
        ],
        diagnostics=[
            {"severity": "warning", "code": "low_confidence", "message": "warn"},
            {"severity": "error", "code": "broken_tree", "message": "broken"},
            {"severity": "info", "code": "note", "message": "info"},
        ],
    )
    inspection = _inspect(payload)

    assert _issue_ids(inspection) == [
        "item:h1:warning:0",
        "item:h1:heading-too-long",
        "node:seq1:n1:multiple-nags",
        "node:seq1:n2:status",
        "node:seq1:n2:warning:0",
        "node:seq1:n2:multiple-nags",
        "item:u1:unresolved",
        "diagnostic:0",
        "diagnostic:1",
    ]
    assert len(set(_issue_ids(inspection))) == len(_issue_ids(inspection))

    by_id = {issue.issue_id: issue for issue in inspection.issues}
    assert by_id["item:h1:heading-too-long"].code == "heading_too_long"
    assert by_id["item:h1:heading-too-long"].blocking is True
    assert by_id["item:h1:heading-too-long"].severity == "error"
    assert by_id["node:seq1:n2:status"].code == "move_invalid"
    assert by_id["node:seq1:n2:status"].blocking is True
    assert by_id["node:seq1:n2:warning:0"].blocking is False
    assert by_id["node:seq1:n2:multiple-nags"].code == "multiple_nags"
    assert by_id["item:u1:unresolved"].code == "ocr_unclear"
    assert by_id["item:u1:unresolved"].message == "Unresolved content requires review"
    assert by_id["diagnostic:0"].severity == "warning"
    assert by_id["diagnostic:0"].blocking is False
    assert by_id["diagnostic:1"].severity == "error"
    assert by_id["diagnostic:1"].blocking is True
    # The info diagnostic is excluded and its index is not reused.
    assert "diagnostic:2" not in by_id
    assert inspection.issue_count == 9
    assert inspection.blocking_issue_count == 6


# ---------------------------------------------------------------------------
# 3. Position anchors: zero / one / multiple canonical full-FEN matches
# ---------------------------------------------------------------------------


def test_position_anchor_with_zero_matches_is_blocking() -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4"), _node("n2", "n1", 0, "e5")]),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": EMPTY_FEN},
            },
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]

    assert issue.issue_id == "item:p1:position-anchor-no-match"
    assert issue.code == "position_anchor_no_match"
    assert issue.blocking is True
    assert issue.severity == "error"


def test_position_anchor_with_invalid_fen_is_zero_matches() -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4")]),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": INVALID_FEN},
            },
        ]
    )
    inspection = _inspect(payload)
    assert _issue_ids(inspection) == ["item:p1:position-anchor-no-match"]


def test_position_anchor_with_exactly_one_match_is_clean() -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4"), _node("n2", "n1", 0, "e5")]),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": START_FEN},
            },
        ]
    )
    inspection = _inspect(payload)
    assert inspection.issue_count == 0


def test_position_anchor_with_duplicate_occurrences_is_ambiguous() -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4")], seq_id="seq1"),
            _sequence_payload([_node("m1", None, 0, "d4")], seq_id="seq2"),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": START_FEN},
            },
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]

    assert issue.issue_id == "item:p1:position-anchor-ambiguous"
    assert issue.code == "position_anchor_ambiguous"
    assert issue.blocking is True
    assert inspection.blocking_issue_count == 1


def test_position_anchor_matches_valid_non_root_fen_after_once() -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4"), _node("n2", "n1", 0, "e5")]),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": AFTER_E5_FEN},
            },
        ]
    )
    # The canonical fen_after of the valid non-root node n2 appears exactly
    # once in the package-wide occurrence set, so no anchor issue is emitted.
    inspection = _inspect(payload)
    assert inspection.issue_count == 0


# ---------------------------------------------------------------------------
# 4. Figure behavior
# ---------------------------------------------------------------------------


def test_non_chess_figure_is_blocking_unsupported() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "photo",
                "caption": "Photo",
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]

    assert issue.issue_id == "item:f1:unsupported-figure"
    assert issue.code == "unsupported_figure"
    assert issue.blocking is True


def test_chessboard_figure_without_position_is_blocking() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]

    assert issue.issue_id == "item:f1:chessboard-position-unresolved"
    assert issue.code == "chessboard_position_unresolved"
    assert issue.blocking is True


def test_chessboard_figure_with_invalid_fen_is_blocking() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "position_fen_candidate": INVALID_FEN,
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    assert _issue_ids(inspection) == ["item:f1:chessboard-position-unresolved"]


def test_chessboard_figure_with_valid_fen_is_clean() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "position_fen_candidate": START_FEN,
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    assert inspection.issue_count == 0


def test_chessboard_figure_with_empty_board_fen_is_blocking() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "position_fen_candidate": EMPTY_FEN,
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]
    assert issue.issue_id == "item:f1:chessboard-position-unresolved"
    assert issue.blocking is True


@pytest.mark.parametrize(
    "non_standard_fen",
    [PROMOTED_MARKER_FEN, CHESS960_CASTLING_FEN],
)
def test_chessboard_figure_with_non_standard_fen_is_blocking(
    non_standard_fen: str,
) -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "figure",
                "id": "f1",
                "figure_type": "chessboard",
                "position_fen_candidate": non_standard_fen,
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]
    assert issue.issue_id == "item:f1:chessboard-position-unresolved"
    assert issue.blocking is True


@pytest.mark.parametrize(
    "non_standard_fen",
    [PROMOTED_MARKER_FEN, CHESS960_CASTLING_FEN],
)
def test_position_anchor_with_non_standard_fen_is_zero_matches(
    non_standard_fen: str,
) -> None:
    payload = _package_payload(
        items=[
            _sequence_payload([_node("n1", None, 0, "e4")]),
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": non_standard_fen},
            },
        ]
    )
    inspection = _inspect(payload)
    assert _issue_ids(inspection) == ["item:p1:position-anchor-no-match"]


def test_invalid_explicit_fen_root_is_skipped_and_cannot_satisfy_anchor() -> None:
    # The sequence root declares an illegal empty-board FEN: the root is
    # skipped, its (invalid) nodes produce no fen_after, and an anchor for that
    # same position must get zero matches instead of being satisfied.
    payload = _package_payload(
        items=[
            {
                "kind": "move_sequence",
                "id": "seq1",
                "evidence": [{"page": 1}],
                "initial_position": {"kind": "fen", "fen": EMPTY_FEN},
                "nodes": [_node("n1", None, 0, "e4")],
            },
            {
                "kind": "prose",
                "id": "p1",
                "text": "Prose",
                "evidence": [{"page": 1}],
                "anchor": {"kind": "position", "fen": EMPTY_FEN},
            },
        ]
    )
    inspection = _inspect(payload)
    assert "item:p1:position-anchor-no-match" in _issue_ids(inspection)
    assert "item:p1:position-anchor-ambiguous" not in _issue_ids(inspection)


# ---------------------------------------------------------------------------
# 5. Unvalidated node and exact-type misuse rejection
# ---------------------------------------------------------------------------


def test_unvalidated_node_is_rejected_before_result() -> None:
    payload = _package_payload(items=[_sequence_payload([_node("n1", None, 0, "e4")])])
    package = ExtractionPackage.model_validate(payload)  # still unvalidated
    with pytest.raises(ValueError, match="review candidate must be locally normalized"):
        inspect_review_candidate(package)


def test_non_extraction_package_input_raises_type_error() -> None:
    for value in (cast(Any, {}), cast(Any, object()), cast(Any, None)):
        with pytest.raises(TypeError, match="package must be ExtractionPackage"):
            inspect_review_candidate(value)


# ---------------------------------------------------------------------------
# 6. Determinism, non-mutation, deep-copied evidence, model strictness
# ---------------------------------------------------------------------------


def test_inspection_is_deterministic_and_input_is_never_mutated() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": _HEADING_LIMIT,
                "evidence": [{"page": 1}],
                "warnings": [
                    {"code": "low_confidence", "message": "low", "evidence": [{"page": 1}]}
                ],
            },
            _sequence_payload([_node("n1", None, 0, "Ke5")], seq_id="seq1"),
        ]
    )
    package = _normalized(payload)
    snapshot = package.model_dump(mode="json")

    first = inspect_review_candidate(package)
    second = inspect_review_candidate(package)

    assert first == second
    assert first.issues == second.issues
    assert package.model_dump(mode="json") == snapshot


def test_issue_evidence_is_deep_copied_from_input() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": _HEADING_LIMIT,
                "evidence": [{"page": 7}],
            }
        ]
    )
    package = _normalized(payload)
    inspection = inspect_review_candidate(package)

    issue = inspection.issues[0]
    assert issue.evidence[0].page == 7
    # Mutating the returned evidence must not leak back into the input package.
    issue.evidence[0].page = 999
    assert package.items[0].evidence[0].page == 7
    # And a fresh inspection still sees the original value.
    assert inspect_review_candidate(package).issues[0].evidence[0].page == 7


def test_public_models_are_frozen_strict_and_reject_unknown_fields() -> None:
    base = {
        "issue_id": "item:h1:warning:0",
        "scope": "item",
        "severity": "warning",
        "blocking": False,
        "item_id": "h1",
        "node_id": None,
        "code": "low_confidence",
        "message": "low",
    }
    issue = ReviewIssue.model_validate(base)
    with pytest.raises(ValidationError):
        issue.blocking = True  # frozen
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate({**base, "unknown": 1})
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate({**base, "blocking": 1})  # strict bool

    inspection = ReviewInspection.model_validate(
        {
            "item_count": 0,
            "move_node_count": 0,
            "issue_count": 0,
            "blocking_issue_count": 0,
        }
    )
    assert inspection.inspection_version == REVIEW_INSPECTION_VERSION
    with pytest.raises(ValidationError):
        ReviewInspection.model_validate(
            {
                "item_count": 0,
                "move_node_count": 0,
                "issue_count": 0,
                "blocking_issue_count": 0,
                "extra": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReviewInspection.model_validate(
            {
                "item_count": -1,
                "move_node_count": 0,
                "issue_count": 0,
                "blocking_issue_count": 0,
            }
        )


def test_unresolved_issue_uses_fixed_message_and_keeps_source_on_item() -> None:
    payload = _package_payload(
        items=[
            {
                "kind": "unresolved",
                "id": "u1",
                "unresolved_type": "text",
                "reason_code": "ocr_unclear",
                "raw_text": "raw fallback",
                "details": "structured details",
                "evidence": [{"page": 1}],
            }
        ]
    )
    inspection = _inspect(payload)
    issue = inspection.issues[0]
    assert issue.issue_id == "item:u1:unresolved"
    assert issue.code == "ocr_unclear"
    # The derived issue always carries the fixed auditable summary message.
    assert issue.message == "Unresolved content requires review"
    # The full source remains on the immutable package item.
    assert issue.item_id == "u1"


def test_long_unresolved_source_is_not_truncated_into_the_issue() -> None:
    long_text = "z" * 5000
    payload = _package_payload(
        items=[
            {
                "kind": "unresolved",
                "id": "u1",
                "unresolved_type": "text",
                "reason_code": "ocr_unclear",
                "raw_text": long_text,
                "evidence": [{"page": 1}],
            }
        ]
    )
    package = _normalized(payload)
    inspection = inspect_review_candidate(package)
    issue = inspection.issues[0]
    assert issue.message == "Unresolved content requires review"
    assert "z" * 4001 not in issue.message
    # The full source stays on the input package, unchanged by inspection.
    unresolved = package.items[0]
    assert isinstance(unresolved, UnresolvedItem)
    assert unresolved.raw_text == long_text
