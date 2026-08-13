from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from chess_workbench.extraction.consolidation import consolidate_move_sequences
from chess_workbench.extraction.contracts import (
    CCEF_VERSION,
    ExtractionPackage,
    MoveSequenceItem,
    ProseItem,
    UnresolvedItem,
)
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import PromptEvidenceFragment, PromptEvidencePage


def _node(
    node_id: str,
    parent_id: str | None,
    sibling_order: int,
    move_text: str,
    *,
    page: int = 1,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_id": parent_id,
        "sibling_order": sibling_order,
        "move_text": move_text,
        "evidence": [{"page": page, "fragment_sha256": f"{page:064x}"}],
    }


def _sequence(sequence_id: str, moves: list[str], *, page: int = 1) -> dict[str, Any]:
    nodes = []
    parent_id = None
    for index, move in enumerate(moves, start=1):
        node_id = f"{sequence_id}_n{index}"
        nodes.append(_node(node_id, parent_id, 0, move, page=page))
        parent_id = node_id
    return {
        "kind": "move_sequence",
        "id": sequence_id,
        "evidence": [{"page": page, "fragment_sha256": f"{page:064x}"}],
        "initial_position": {"kind": "startpos"},
        "nodes": nodes,
    }


def _package(
    items: list[dict[str, Any]], diagnostics: list[dict[str, Any]] | None = None
) -> ExtractionPackage:
    return ExtractionPackage.model_validate(
        {
            "schema_version": CCEF_VERSION,
            "package_id": str(UUID("11111111-1111-4111-8111-111111111111")),
            "source": {
                "source_ref": "fixture",
                "media_type": "application/pdf",
                "language": "en",
                "page_range": {"start_page": 1, "end_page": 9},
            },
            "items": items,
            "diagnostics": diagnostics or [],
            "provenance": {
                "created_at": datetime(2026, 8, 13, tzinfo=UTC),
                "adapter_name": "test",
                "adapter_version": "1",
                "provider": None,
                "model": None,
                "request_sha256": None,
                "response_sha256": None,
            },
            "extensions": {},
        }
    )


def _sequences(package: ExtractionPackage) -> list[MoveSequenceItem]:
    return [item for item in package.items if isinstance(item, MoveSequenceItem)]


def _fragment(page: int, text: str) -> SourceEvidenceFragment:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    return SourceEvidenceFragment(
        physical_page=page,
        box=box,
        text=text,
        origin="embedded_text",
        confidence=None,
        engine_name="pdfium",
        engine_version="test",
        fragment_sha256=source_fragment_sha256(page, box, text, "embedded_text", "pdfium", "test"),
    )


def test_merges_duplicate_paths_and_prefixes_only_within_heading_scope() -> None:
    package = _package(
        [
            {
                "kind": "heading",
                "id": "intro",
                "level": 2,
                "text": "Intro",
                "evidence": [{"page": 1}],
            },
            _sequence("intro_line", ["e4", "e5"], page=1),
            {"kind": "prose", "id": "p1", "text": "Narrative Nc6 plan.", "evidence": [{"page": 2}]},
            {
                "kind": "heading",
                "id": "game",
                "level": 3,
                "text": "Game",
                "evidence": [{"page": 3}],
            },
            _sequence("line_a", ["e4", "e5", "Nf3!"], page=4),
            _sequence("line_b", ["e4", "e5", "Nf3", "Nc6"], page=5),
            _sequence("line_c", ["e4", "e5", "Bc4"], page=6),
        ]
    )

    result = consolidate_move_sequences(package)

    sequences = _sequences(result)
    assert [sequence.id for sequence in sequences] == ["intro_line", "line_a"]
    assert [len(sequence.nodes) for sequence in sequences] == [2, 5]
    game = sequences[1]
    assert [(node.move_text, node.parent_id, node.sibling_order) for node in game.nodes] == [
        ("e4", None, 0),
        ("e5", "n1", 0),
        ("Nf3", "n2", 0),
        ("Nc6", "n3", 0),
        ("Bc4", "n2", 1),
    ]
    assert game.nodes[2].nags == [1]
    assert {ref.page for ref in game.nodes[0].evidence} == {4, 5, 6}
    assert all(
        node.validation_status == "valid" for sequence in sequences for node in sequence.nodes
    )
    prose = next(item for item in result.items if isinstance(item, ProseItem))
    assert prose.text == "Narrative Nc6 plan."


def test_covered_illegal_fragment_stays_in_prose_and_not_in_playable_tree() -> None:
    sequence = _sequence("line", ["e4", "Ke5"], page=2)
    package = _package(
        [
            {"kind": "heading", "id": "h", "level": 1, "text": "H", "evidence": [{"page": 1}]},
            {
                "kind": "prose",
                "id": "p",
                "text": "The illustrative text says Ke5.",
                "evidence": [{"page": 2, "fragment_sha256": f"{2:064x}"}],
            },
            sequence,
        ]
    )

    result = consolidate_move_sequences(package)

    assert [node.move_text for node in _sequences(result)[0].nodes] == ["e4"]
    assert not any(isinstance(item, UnresolvedItem) for item in result.items)
    assert next(item for item in result.items if isinstance(item, ProseItem)).text.endswith("Ke5.")


def test_uncovered_illegal_fragment_becomes_unresolved_instead_of_a_move() -> None:
    package = _package(
        [
            {"kind": "heading", "id": "h", "level": 1, "text": "H", "evidence": [{"page": 1}]},
            _sequence("line", ["e4", "Ke5", "e5"], page=2),
        ],
        diagnostics=[
            {
                "severity": "warning",
                "code": "source_note",
                "message": "The rejected fragment needs review.",
                "item_id": "line",
                "node_id": "line_n2",
            }
        ],
    )

    result = consolidate_move_sequences(package)

    assert [node.move_text for node in _sequences(result)[0].nodes] == ["e4"]
    unresolved = next(item for item in result.items if isinstance(item, UnresolvedItem))
    assert unresolved.raw_text == "Ke5 e5"
    assert unresolved.reason_code == "move_tree_unresolved"
    assert {ref.page for ref in unresolved.evidence} == {2}
    assert result.diagnostics[0].item_id == "line"
    assert result.diagnostics[0].node_id is None


def test_diagnostic_becomes_global_when_its_entire_sequence_is_removed() -> None:
    package = _package(
        [_sequence("line", ["Ke5"], page=2)],
        diagnostics=[
            {
                "severity": "warning",
                "code": "source_note",
                "message": "The rejected sequence needs review.",
                "item_id": "line",
                "node_id": "line_n1",
            }
        ],
    )

    result = consolidate_move_sequences(package)

    assert not _sequences(result)
    assert any(isinstance(item, UnresolvedItem) for item in result.items)
    assert result.diagnostics[0].item_id is None
    assert result.diagnostics[0].node_id is None


def test_move_anchors_and_diagnostics_remap_to_merged_ids() -> None:
    package = _package(
        [
            {"kind": "heading", "id": "h", "level": 1, "text": "H", "evidence": [{"page": 1}]},
            _sequence("a", ["e4", "e5"], page=2),
            _sequence("b", ["e4", "e5", "Nf3"], page=3),
            {
                "kind": "prose",
                "id": "p",
                "text": "At Nf3.",
                "anchor": {"kind": "move_node", "sequence_id": "b", "node_id": "b_n3"},
                "evidence": [{"page": 3}],
            },
        ],
        diagnostics=[
            {
                "severity": "info",
                "code": "note",
                "message": "note",
                "item_id": "b",
                "node_id": "b_n3",
            }
        ],
    )

    result = consolidate_move_sequences(package)

    prose = next(item for item in result.items if isinstance(item, ProseItem))
    assert prose.anchor is not None
    assert prose.anchor.sequence_id == "a"
    assert prose.anchor.node_id == "n3"
    assert result.diagnostics[0].item_id == "a"
    assert result.diagnostics[0].node_id == "n3"


def test_is_deterministic_and_does_not_mutate_input() -> None:
    package = _package([_sequence("a", ["e4", "e5"], page=1), _sequence("b", ["e4", "e5"], page=2)])
    snapshot = copy.deepcopy(package.model_dump(mode="json"))

    first = consolidate_move_sequences(package)
    second = consolidate_move_sequences(package)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert package.model_dump(mode="json") == snapshot


def test_evidence_aware_mode_uses_only_standalone_notation_for_playable_line() -> None:
    heading_fragment = _fragment(1, "Game")
    first_line = _fragment(1, "1 e4 e5 2 Nf3 Nc6")
    narrative = _fragment(
        1,
        "The plan may also occur via 3 Nf3 Bg4 4 d4, with ... e7-e5 later.",
    )
    second_line = _fragment(1, "3 Bb5 a6")
    page = PromptEvidencePage(
        physical_page=1,
        fragments=[
            PromptEvidenceFragment(order=0, fragment=heading_fragment),
            PromptEvidenceFragment(order=1, fragment=first_line),
            PromptEvidenceFragment(order=2, fragment=narrative),
            PromptEvidenceFragment(order=3, fragment=second_line),
        ],
    )
    model_line = _sequence("model_line", ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"], page=1)
    model_line["nodes"].append(
        {
            **_node("model_line_n7", "model_line_n6", 0, "Ke7", page=1),
            "evidence": [{"page": 1, "fragment_sha256": second_line.fragment_sha256}],
        }
    )
    package = _package(
        [
            {
                "kind": "heading",
                "id": "game",
                "level": 1,
                "text": "Game",
                "evidence": [{"page": 1, "fragment_sha256": heading_fragment.fragment_sha256}],
            },
            {
                "kind": "prose",
                "id": "p",
                "text": narrative.text,
                "evidence": [{"page": 1, "fragment_sha256": narrative.fragment_sha256}],
            },
            model_line,
        ]
    )

    result = consolidate_move_sequences(package, [page])

    sequence = _sequences(result)[0]
    assert [item.id for item in result.items] == ["game", "model_line", "p"]
    assert [node.move_text for node in sequence.nodes] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    move_hashes = {ref.fragment_sha256 for node in sequence.nodes for ref in node.evidence}
    assert move_hashes == {first_line.fragment_sha256, second_line.fragment_sha256}
    assert narrative.fragment_sha256 not in move_hashes
    prose = next(item for item in result.items if isinstance(item, ProseItem))
    assert prose.text == narrative.text
    assert not any(isinstance(item, UnresolvedItem) for item in result.items)


def test_evidence_aware_mode_supports_titled_sequences_from_explicit_fen() -> None:
    heading_fragment = _fragment(1, "Position study")
    formal_line = _fragment(1, "1...e5 2.Nf3")
    page = PromptEvidencePage(
        physical_page=1,
        fragments=[
            PromptEvidenceFragment(order=0, fragment=heading_fragment),
            PromptEvidenceFragment(order=1, fragment=formal_line),
        ],
    )
    model_line = _sequence("line", ["e5", "Nf3"], page=1)
    model_line["title"] = "Illustration"
    model_line["initial_position"] = {
        "kind": "fen",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    }
    package = _package(
        [
            {
                "kind": "heading",
                "id": "study",
                "level": 1,
                "text": "Position study",
                "evidence": [{"page": 1, "fragment_sha256": heading_fragment.fragment_sha256}],
            },
            model_line,
        ]
    )

    result = consolidate_move_sequences(package, [page])

    sequence = _sequences(result)[0]
    assert sequence.title == "Illustration"
    assert sequence.initial_position.kind == "fen"
    assert [node.move_text for node in sequence.nodes] == ["e5", "Nf3"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_evidence_aware_mode_preserves_discarded_legal_inline_branch_as_prose() -> None:
    heading_fragment = _fragment(1, "Game")
    formal_line = _fragment(1, "1 e4 e5 2 Nf3")
    inline_branch = _fragment(1, "A quieter alternative is 2 Bc4, followed by normal play.")
    page = PromptEvidencePage(
        physical_page=1,
        fragments=[
            PromptEvidenceFragment(order=0, fragment=heading_fragment),
            PromptEvidenceFragment(order=1, fragment=formal_line),
            PromptEvidenceFragment(order=2, fragment=inline_branch),
        ],
    )
    model_line = _sequence("line", ["e4", "e5", "Nf3"], page=1)
    model_line["nodes"].append(
        {
            **_node("line_n4", "line_n2", 1, "Bc4", page=1),
            "evidence": [{"page": 1, "fragment_sha256": inline_branch.fragment_sha256}],
        }
    )
    package = _package(
        [
            {
                "kind": "heading",
                "id": "game",
                "level": 1,
                "text": "Game",
                "evidence": [{"page": 1, "fragment_sha256": heading_fragment.fragment_sha256}],
            },
            model_line,
        ]
    )

    result = consolidate_move_sequences(package, [page])

    assert [node.move_text for node in _sequences(result)[0].nodes] == ["e4", "e5", "Nf3"]
    recovered = [item for item in result.items if isinstance(item, ProseItem)]
    assert [item.text for item in recovered] == [inline_branch.text]
    assert recovered[0].evidence[0].fragment_sha256 == inline_branch.fragment_sha256
