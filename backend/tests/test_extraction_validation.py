"""Focused tests for the deterministic python-chess move normalizer.

Covers the required behaviors of DS-STAGE8-CHESS-NORMALIZER-01: exact
canonical SAN/UCI/before-after FEN recomputation for startpos and custom-FEN
branches, source-token cleanup, the five validator outcomes and warning
messages, context agreement, idempotency, input immutability, and import
purity. Packages are built as JSON payloads and validated through
``ExtractionPackage`` exactly as a decoded package would arrive.
"""

from __future__ import annotations

import copy
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from chess_workbench.extraction import normalize_chess_moves
from chess_workbench.extraction.contracts import (
    ExtractionPackage,
    MoveSequenceItem,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
AFTER_NF3_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"
AFTER_D4_FEN = "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq d3 0 1"
CASTLE_BEFORE_FEN = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
CASTLE_AFTER_FEN = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R4RK1 b kq - 1 1"
CASTLE_TWICE_FEN = "2kr3r/pppppppp/8/8/8/8/PPPPPPPP/R4RK1 w - - 2 2"
PROMO_BEFORE_FEN = "8/P7/8/8/8/8/8/k6K w - - 0 1"
PROMO_AFTER_FEN = "Q7/8/8/8/8/8/8/k6K b - - 0 1"
EP_BEFORE_FEN = "rnbqkbnr/ppp1pppp/8/8/3pP3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 3"
EP_AFTER_FEN = "rnbqkbnr/ppp1pppp/8/8/8/4p3/PPPP1PPP/RNBQKBNR w KQkq - 0 4"
AMBIGUOUS_FEN = "rnbqkbnr/ppp1pppp/8/4p3/6N1/5N2/PPPPPPPP/R1BQKB1R w KQkq - 0 2"
FULLMOVE_TWO_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 2"

INVALID_INITIAL_MESSAGE = "The sequence initial position is not a legal standard-chess FEN."
UNRESOLVED_PARENT_MESSAGE = "The parent move could not be resolved to one position."
AMBIGUOUS_MESSAGE = "The move text is ambiguous in the reconstructed position."
INVALID_MOVE_MESSAGE = "The move text is not legal in the reconstructed position."
CONTEXT_MISMATCH_MESSAGE = "The move context conflicts with the reconstructed position."


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


def _sequence_payload(
    initial_position: dict[str, Any],
    nodes: list[dict[str, Any]],
    seq_id: str = "seq1",
) -> dict[str, Any]:
    return {
        "kind": "move_sequence",
        "id": seq_id,
        "evidence": [{"page": 1}],
        "initial_position": initial_position,
        "nodes": nodes,
    }


def _package_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "chess-content-extraction/1.0",
        "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
        "source": {"source_ref": "opaque-ref-1", "media_type": "application/pdf"},
        "items": items,
        "provenance": {
            "created_at": "2026-08-11T10:00:00Z",
            "adapter_name": "test-adapter",
            "adapter_version": "0.1.0",
        },
    }


def _normalize(
    initial_position: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> tuple[ExtractionPackage, MoveSequenceItem]:
    package = ExtractionPackage.model_validate(
        _package_payload([_sequence_payload(initial_position, nodes)])
    )
    out = normalize_chess_moves(package)
    sequence = out.items[0]
    assert isinstance(sequence, MoveSequenceItem)
    return out, sequence


def _assert_authoritative_null(node: Any) -> None:
    assert node.san_candidate is None
    assert node.uci_candidate is None
    assert node.fen_before is None
    assert node.fen_after is None


# ---------------------------------------------------------------------------
# 1. Standard-start mainline plus root/child variations, input unchanged
# ---------------------------------------------------------------------------


def test_startpos_mainline_and_root_variation_with_exact_values() -> None:
    package = ExtractionPackage.model_validate(
        _package_payload(
            [
                _sequence_payload(
                    {"kind": "startpos"},
                    [
                        _node("n1", None, 0, "e4"),
                        _node("n2", "n1", 0, "e5"),
                        _node("n3", "n2", 0, "Nf3"),
                        _node("n4", None, 1, "d4"),
                    ],
                )
            ]
        )
    )
    snapshot = package.model_dump()

    out = normalize_chess_moves(package)

    # The input package is never mutated and the result is a distinct object.
    assert package.model_dump() == snapshot
    assert out is not package

    sequence = out.items[0]
    assert isinstance(sequence, MoveSequenceItem)
    n1, n2, n3, n4 = sequence.nodes
    assert n1.validation_status == "valid"
    assert n1.san_candidate == "e4"
    assert n1.uci_candidate == "e2e4"
    assert n1.fen_before == START_FEN
    assert n1.fen_after == AFTER_E4_FEN
    assert n2.validation_status == "valid"
    assert n2.san_candidate == "e5"
    assert n2.uci_candidate == "e7e5"
    assert n2.fen_before == AFTER_E4_FEN
    assert n2.fen_after == AFTER_E5_FEN
    assert n3.validation_status == "valid"
    assert n3.san_candidate == "Nf3"
    assert n3.uci_candidate == "g1f3"
    assert n3.fen_before == AFTER_E5_FEN
    assert n3.fen_after == AFTER_NF3_FEN
    # Root siblings are independent alternatives that reuse the start position.
    assert n4.validation_status == "valid"
    assert n4.san_candidate == "d4"
    assert n4.uci_candidate == "d2d4"
    assert n4.fen_before == START_FEN
    assert n4.fen_after == AFTER_D4_FEN
    for node in sequence.nodes:
        assert node.warnings == []


# ---------------------------------------------------------------------------
# 2. Legal custom FEN, castling, promotion, en-passant, coordinate notation
# ---------------------------------------------------------------------------


def test_fen_position_castling_and_child_branch() -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": CASTLE_BEFORE_FEN},
        [
            _node("c1", None, 0, "O-O", side_to_move="w", move_number=1),
            _node("c2", "c1", 0, "O-O-O", side_to_move="b", move_number=1),
        ],
    )
    c1, c2 = sequence.nodes
    assert c1.validation_status == "valid"
    assert c1.san_candidate == "O-O"
    assert c1.uci_candidate == "e1g1"
    assert c1.fen_before == CASTLE_BEFORE_FEN
    assert c1.fen_after == CASTLE_AFTER_FEN
    assert c2.validation_status == "valid"
    assert c2.san_candidate == "O-O-O"
    assert c2.uci_candidate == "e8c8"
    assert c2.fen_before == CASTLE_AFTER_FEN
    assert c2.fen_after == CASTLE_TWICE_FEN


def test_fen_position_promotion_san_and_coordinate_form() -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": PROMO_BEFORE_FEN},
        [
            _node("p1", None, 0, "a8=Q", side_to_move="w", move_number=1),
            _node("p2", None, 1, "a7a8q", side_to_move="w", move_number=1),
        ],
    )
    p1, p2 = sequence.nodes
    for node in (p1, p2):
        assert node.validation_status == "valid"
        assert node.san_candidate == "a8=Q+"
        assert node.uci_candidate == "a7a8q"
        assert node.fen_before == PROMO_BEFORE_FEN
        assert node.fen_after == PROMO_AFTER_FEN


def test_fen_position_en_passant() -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": EP_BEFORE_FEN},
        [_node("e1", None, 0, "dxe3", side_to_move="b", move_number=3)],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "valid"
    assert node.san_candidate == "dxe3"
    assert node.uci_candidate == "d4e3"
    assert node.fen_before == EP_BEFORE_FEN
    assert node.fen_after == EP_AFTER_FEN


def test_coordinate_notation_is_rewritten_to_canonical_san() -> None:
    _, sequence = _normalize({"kind": "startpos"}, [_node("n1", None, 0, "e2e4")])
    node = sequence.nodes[0]
    assert node.validation_status == "valid"
    assert node.san_candidate == "e4"
    assert node.uci_candidate == "e2e4"
    assert node.fen_before == START_FEN
    assert node.fen_after == AFTER_E4_FEN


# ---------------------------------------------------------------------------
# 3. Source-token normalization and failure tokens
# ---------------------------------------------------------------------------


def test_move_number_prefix_symbolic_suffix_and_nag_tokens_are_cleaned() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node("n1", None, 0, "1.e4"),
            _node("n2", "n1", 0, "1...e5"),
            _node("n3", "n2", 0, "Nf3!!"),
            _node("n4", None, 1, "d4$0"),
            _node("n5", None, 2, "c4 $255"),
            _node("n6", None, 3, "1. Nf3 ! ?"),
        ],
    )
    n1, n2, n3, n4, n5, n6 = sequence.nodes
    assert n1.validation_status == "valid"
    assert n1.san_candidate == "e4"
    assert n2.san_candidate == "e5"
    assert n3.san_candidate == "Nf3"
    assert n4.san_candidate == "d4"
    assert n5.san_candidate == "c4"
    assert n6.san_candidate == "Nf3"


@pytest.mark.parametrize(
    "move_text",
    [
        "e4 {this is a comment}",  # comments are not stripped
        "this is not a move",  # arbitrary prose
        "e4 e5",  # two moves in one token
        "e4$256",  # out-of-range NAG is not stripped
        "1.",  # empty after prefix cleanup
        "1...",  # empty after prefix cleanup
        "!",  # empty after suffix cleanup
        "--",  # null move
        "0000",  # null move
        "Z0",  # null move
    ],
)
def test_bad_tokens_are_invalid_move(move_text: str) -> None:
    _, sequence = _normalize({"kind": "startpos"}, [_node("n1", None, 0, move_text)])
    node = sequence.nodes[0]
    assert node.validation_status == "invalid"
    assert node.warnings[0].code == "ccef_chess_invalid_move"
    _assert_authoritative_null(node)


# ---------------------------------------------------------------------------
# 4. Illegal and ambiguous moves retained for review
# ---------------------------------------------------------------------------


def test_illegal_move_is_invalid_and_blocks_descendants() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node("n1", None, 0, "Ke2"),
            _node("n2", "n1", 0, "e4"),
        ],
    )
    n1, n2 = sequence.nodes
    assert n1.validation_status == "invalid"
    assert n1.warnings[0].code == "ccef_chess_invalid_move"
    assert n1.warnings[0].message == INVALID_MOVE_MESSAGE
    _assert_authoritative_null(n1)
    assert n2.validation_status == "invalid"
    assert n2.warnings[0].code == "ccef_chess_unresolved_parent"
    assert n2.warnings[0].message == UNRESOLVED_PARENT_MESSAGE
    _assert_authoritative_null(n2)


def test_ambiguous_san_is_retained_ambiguous() -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": AMBIGUOUS_FEN},
        [_node("n1", None, 0, "Ne5")],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "ambiguous"
    assert node.warnings[0].code == "ccef_chess_ambiguous_move"
    assert node.warnings[0].message == AMBIGUOUS_MESSAGE
    _assert_authoritative_null(node)


# ---------------------------------------------------------------------------
# 5. Invalid initial positions: exact root and descendant warnings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fen",
    [
        "8/8/8/8/8/8/8/8 w - - 0 1",  # no kings
        "8/8/8/8/8/8/8/KKk5 w - - 0 1",  # two white kings: structurally illegal
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPP~/RNBQKBNR w KQkq - 0 1",  # tilde
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w HAha - 0 1",  # Shredder
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w QKqk - 0 1",  # unordered
    ],
)
def test_invalid_initial_position_fen(fen: str) -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": fen},
        [
            _node("n1", None, 0, "e4"),
            _node("n2", "n1", 0, "e5"),
        ],
    )
    n1, n2 = sequence.nodes
    assert n1.validation_status == "invalid"
    assert n1.warnings[0].code == "ccef_chess_invalid_initial_position"
    assert n1.warnings[0].message == INVALID_INITIAL_MESSAGE
    _assert_authoritative_null(n1)
    assert n2.validation_status == "invalid"
    assert n2.warnings[0].code == "ccef_chess_unresolved_parent"
    assert n2.warnings[0].message == UNRESOLVED_PARENT_MESSAGE
    _assert_authoritative_null(n2)


# ---------------------------------------------------------------------------
# 6. Side-to-move and move-number context agreement
# ---------------------------------------------------------------------------


def test_context_matches_including_black_to_move() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node("n1", None, 0, "e4", side_to_move="w", move_number=1),
            _node("n2", "n1", 0, "e5", side_to_move="b", move_number=1),
        ],
    )
    assert sequence.nodes[0].validation_status == "valid"
    assert sequence.nodes[1].validation_status == "valid"
    assert sequence.nodes[1].san_candidate == "e5"


def test_side_to_move_mismatch_blocks_the_whole_descendant_path() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node("n1", None, 0, "e4"),
            _node("n2", "n1", 0, "e5", side_to_move="w"),  # black is to move
            _node("n3", "n2", 0, "Nf3"),
        ],
    )
    n1, n2, n3 = sequence.nodes
    assert n1.validation_status == "valid"
    assert n2.validation_status == "invalid"
    assert n2.warnings[0].code == "ccef_chess_context_mismatch"
    assert n2.warnings[0].message == CONTEXT_MISMATCH_MESSAGE
    _assert_authoritative_null(n2)
    assert n3.validation_status == "invalid"
    assert n3.warnings[0].code == "ccef_chess_unresolved_parent"


def test_move_number_mismatch_is_context_mismatch() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [_node("n1", None, 0, "e4", side_to_move="w", move_number=2)],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "invalid"
    assert node.warnings[0].code == "ccef_chess_context_mismatch"
    _assert_authoritative_null(node)


def test_custom_fen_fullmove_context_matches() -> None:
    _, sequence = _normalize(
        {"kind": "fen", "fen": FULLMOVE_TWO_FEN},
        [_node("n1", None, 0, "e4", side_to_move="w", move_number=2)],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "valid"
    assert node.fen_before == FULLMOVE_TWO_FEN
    # The fullmove clock from the declared FEN is preserved; it is not reset.
    assert node.fen_after == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 2"


# ---------------------------------------------------------------------------
# 7. Forged normalization is recomputed; idempotency; warning hygiene
# ---------------------------------------------------------------------------


def test_forged_valid_node_is_recomputed_and_unrelated_state_preserved() -> None:
    forged_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node(
                "n1",
                None,
                0,
                "e4",
                validation_status="valid",
                san_candidate="bogus",
                uci_candidate="a1a1",
                fen_before=forged_fen,
                fen_after=forged_fen,
                nags=[1, 2],
                warnings=[
                    {
                        "code": "model_note",
                        "message": "keep me",
                        "evidence": [{"page": 1}],
                    }
                ],
                extensions={"com.example.note": 7},
            )
        ],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "valid"
    assert node.san_candidate == "e4"
    assert node.uci_candidate == "e2e4"
    assert node.fen_before == START_FEN
    assert node.fen_after == AFTER_E4_FEN
    assert node.nags == [1, 2]
    assert node.extensions == {"com.example.note": 7}
    assert [w.code for w in node.warnings] == ["model_note"]


def test_prior_validator_warning_is_removed_when_recomputed_valid() -> None:
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node(
                "n1",
                None,
                0,
                "e4",
                warnings=[
                    {
                        "code": "ccef_chess_invalid_move",
                        "message": "stale",
                        "evidence": [{"page": 1}],
                    }
                ],
            )
        ],
    )
    node = sequence.nodes[0]
    assert node.validation_status == "valid"
    assert node.warnings == []


def test_repeat_normalization_is_value_idempotent() -> None:
    package = ExtractionPackage.model_validate(
        _package_payload(
            [
                _sequence_payload(
                    {"kind": "startpos"},
                    [
                        _node("n1", None, 0, "e4"),
                        _node("n2", "n1", 0, "e5", side_to_move="w"),  # mismatch
                        _node("n3", "n2", 0, "Nf3"),
                        _node("n4", None, 1, "Ke2"),
                        _node(
                            "n5",
                            None,
                            2,
                            "d4",
                            warnings=[
                                {
                                    "code": "model_note",
                                    "message": "keep me",
                                    "evidence": [{"page": 1}],
                                }
                            ],
                        ),
                    ],
                ),
                _sequence_payload(
                    {"kind": "fen", "fen": AMBIGUOUS_FEN},
                    [_node("m1", None, 0, "Ne5")],
                    seq_id="seq2",
                ),
            ]
        )
    )
    once = normalize_chess_moves(package)
    twice = normalize_chess_moves(once)
    assert once.model_dump() == twice.model_dump()


def test_validator_warnings_do_not_duplicate_on_repeat() -> None:
    package = ExtractionPackage.model_validate(
        _package_payload(
            [
                _sequence_payload(
                    {"kind": "startpos"},
                    [
                        _node("n1", None, 0, "Ke2"),
                        _node("n2", "n1", 0, "e4"),
                    ],
                )
            ]
        )
    )
    once = normalize_chess_moves(package)
    twice = normalize_chess_moves(once)
    for out in (once, twice):
        sequence = out.items[0]
        assert isinstance(sequence, MoveSequenceItem)
        assert [w.code for w in sequence.nodes[0].warnings] == ["ccef_chess_invalid_move"]
        assert [w.code for w in sequence.nodes[1].warnings] == ["ccef_chess_unresolved_parent"]
    assert once.model_dump() == twice.model_dump()


def test_warning_evidence_is_an_independent_deep_copy() -> None:
    _, sequence = _normalize({"kind": "startpos"}, [_node("n1", None, 0, "Ke2")])
    node = sequence.nodes[0]
    warning = node.warnings[0]
    # The warning carries a deep copy of the node evidence.
    assert len(warning.evidence) == len(node.evidence) == 1
    assert warning.evidence[0].page == node.evidence[0].page
    warning.evidence.clear()
    assert warning.evidence == []
    assert len(node.evidence) == 1


# ---------------------------------------------------------------------------
# 8. Packages without move sequences are equal, distinct deep copies
# ---------------------------------------------------------------------------


def test_package_without_move_sequence_is_equal_distinct_copy() -> None:
    payload = _package_payload(
        [
            {
                "kind": "heading",
                "id": "h1",
                "level": 1,
                "text": "Chapter one",
                "evidence": [{"page": 1}],
            },
            {
                "kind": "prose",
                "id": "p1",
                "text": "Some prose.",
                "evidence": [{"page": 1}],
            },
        ]
    )
    package = ExtractionPackage.model_validate(payload)
    snapshot = package.model_dump()
    out = normalize_chess_moves(package)
    assert out is not package
    assert out.model_dump() == snapshot


# ---------------------------------------------------------------------------
# 9. Import boundary proof and public export
# ---------------------------------------------------------------------------


def test_validation_module_imports_without_forbidden_modules() -> None:
    code = (
        "import importlib.util, sys, types\n"
        "from pathlib import Path\n"
        "root = types.ModuleType('chess_workbench')\n"
        "sys.modules['chess_workbench'] = root\n"
        "pkg = types.ModuleType('chess_workbench.extraction')\n"
        "pkg.__path__ = [str(Path('backend/src/chess_workbench/extraction'))]\n"
        "sys.modules['chess_workbench.extraction'] = pkg\n"
        "for name in ('contracts', 'validation'):\n"
        "    spec = importlib.util.spec_from_file_location(\n"
        "        f'chess_workbench.extraction.{name}',\n"
        "        f'backend/src/chess_workbench/extraction/{name}.py')\n"
        "    mod = importlib.util.module_from_spec(spec)\n"
        "    sys.modules[spec.name] = mod\n"
        "    spec.loader.exec_module(mod)\n"
        "forbidden = ('httpx', 'chess_workbench.provider', 'chess_workbench.decoder',\n"
        "             'chess_workbench.store', 'chess_workbench.services',\n"
        "             'chess_workbench.api', 'chess_workbench.schemas',\n"
        "             'chess_workbench.config', 'chess_workbench.domain',\n"
        "             'chess_workbench.extraction.provider',\n"
        "             'chess_workbench.extraction.decoder',\n"
        "             'chess_workbench.extraction.deepseek',\n"
        "             'sqlalchemy', 'sanic', 'pydantic_settings')\n"
        "bad = [m for m in forbidden if m in sys.modules]\n"
        "print('bad=', bad)\n"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"forbidden modules imported: {result.stdout}{result.stderr}"


def test_validation_source_does_not_mention_forbidden_concepts() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "chess_workbench" / "extraction" / "validation.py"
    ).read_text(encoding="utf-8")
    for token in (
        "httpx",
        "provider",
        "decoder",
        "deepseek",
        "sanic",
        "sqlalchemy",
        "store",
        "services",
        "jobs",
        "Settings",
        "pydantic_settings",
    ):
        assert re.search(rf"\b{re.escape(token)}\b", source) is None, (
            f"validation.py mentions {token!r}"
        )


def test_normalize_chess_moves_is_exported() -> None:
    from chess_workbench.extraction import __all__ as exported

    assert "normalize_chess_moves" in exported


# ---------------------------------------------------------------------------
# Extra: all five validator warning messages are exact and stable
# ---------------------------------------------------------------------------


def test_all_five_validator_warning_messages_are_exact() -> None:
    assert {
        "ccef_chess_invalid_initial_position": INVALID_INITIAL_MESSAGE,
        "ccef_chess_unresolved_parent": UNRESOLVED_PARENT_MESSAGE,
        "ccef_chess_ambiguous_move": AMBIGUOUS_MESSAGE,
        "ccef_chess_invalid_move": INVALID_MOVE_MESSAGE,
        "ccef_chess_context_mismatch": CONTEXT_MISMATCH_MESSAGE,
    } == {
        "ccef_chess_invalid_initial_position": (
            "The sequence initial position is not a legal standard-chess FEN."
        ),
        "ccef_chess_unresolved_parent": ("The parent move could not be resolved to one position."),
        "ccef_chess_ambiguous_move": ("The move text is ambiguous in the reconstructed position."),
        "ccef_chess_invalid_move": ("The move text is not legal in the reconstructed position."),
        "ccef_chess_context_mismatch": (
            "The move context conflicts with the reconstructed position."
        ),
    }


def test_mixed_branch_with_valid_child_and_unresolved_descendant() -> None:
    """A valid sibling of an invalid node still resolves through its own parent."""
    _, sequence = _normalize(
        {"kind": "startpos"},
        [
            _node("n1", None, 0, "e4"),
            _node("n2", "n1", 0, "Ke2"),  # illegal child (black cannot play it)
            _node("n3", "n2", 0, "e5"),  # unresolved descendant
            _node("n4", "n1", 1, "c5"),  # valid sibling branch (black move)
        ],
    )
    n1, n2, n3, n4 = sequence.nodes
    assert n1.validation_status == "valid"
    assert n2.validation_status == "invalid"
    assert n3.validation_status == "invalid"
    assert n3.warnings[0].code == "ccef_chess_unresolved_parent"
    assert n4.validation_status == "valid"
    assert n4.san_candidate == "c5"
    assert n4.uci_candidate == "c7c5"
    assert n4.fen_before == AFTER_E4_FEN
    assert n4.fen_after == "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"


def test_input_package_is_never_mutated_for_mixed_outcomes() -> None:
    payload = _package_payload(
        [
            _sequence_payload(
                {"kind": "fen", "fen": AMBIGUOUS_FEN},
                [_node("m1", None, 0, "Ne5")],
            )
        ]
    )
    package = ExtractionPackage.model_validate(payload)
    before = copy.deepcopy(package)
    normalize_chess_moves(package)
    assert package.model_dump() == before.model_dump()
