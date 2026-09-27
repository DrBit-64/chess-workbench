"""Explicit source relationships, including a branch and mainline return."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from chess_workbench.extraction.chunks import generate_relation_chunks
from chess_workbench.extraction.contracts import MoveSequenceItemV1_1
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    TextStyleRun,
    source_fragment_sha256,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.provider import (
    ScriptedStructuredGenerationProvider,
    StructuredGenerationResponse,
)
from chess_workbench.extraction.relations import (
    RelationPatchResponse,
    RelationState,
    apply_relation_patches,
    apply_relations,
    compile_relations,
    formal_score_note_issues,
    localize_invalid_relation_subtrees,
    parse_relation_response,
    recover_completed_relation_prefix,
    source_tokens,
    validation_relation_issues,
)


def _context(text: str) -> CcefPromptContext:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=text,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "test", "1"),
    )
    return CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000001"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="source",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[
            PromptEvidencePage(
                physical_page=1,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        ],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )


def test_explicit_branch_and_return_keep_same_san_occurrences_distinct() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6 (2...d6 3 Bb5) 3 Bb5")
    tokens = source_tokens(context)
    by_raw: dict[str, list[str]] = {}
    for token in tokens:
        by_raw.setdefault(token.raw, []).append(token.id)
    e4, e5, nf3, nc6 = (by_raw[value][0] for value in ("e4", "e5", "Nf3", "Nc6"))
    d6 = by_raw["d6"][0]
    branch_bb5, main_bb5 = by_raw["Bb5"]
    data = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "main_open",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": [e4, e5, nf3, nc6],
                "evidence_refs": ["s1_0"],
            },
            {
                "id": "branch",
                "game_ref": "game",
                "line_ref": "d6_line",
                "entry": {
                    "kind": "alternative_to",
                    "target_line_ref": "main",
                    "target_move_ref": nc6,
                },
                "move_refs": [d6, branch_bb5],
                "evidence_refs": ["s1_0"],
            },
            {
                "id": "return",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "continue", "after_move_ref": nc6},
                "move_refs": [main_bb5],
                "evidence_refs": ["s1_0"],
            },
        ],
        "notes": [],
        "unresolved": [],
    }
    response = parse_relation_response(__import__("json").dumps(data))
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert state.parent[d6] == nf3
    assert state.parent[branch_bb5] == d6
    assert state.parent[main_bb5] == nc6
    assert state.lines[("game", "main")][1]["kind"] == "root"
    assert next(event for event in state.events if event.get("id") == main_bb5)["mainline"]
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    nodes = {node.evidence[0].start_offset: node for node in sequence.nodes}
    assert (
        nodes[next(t.start for t in tokens if t.id == branch_bb5)].parent_id
        != nodes[next(t.start for t in tokens if t.id == main_bb5)].parent_id
    )
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_same_line_name_is_scoped_to_its_game() -> None:
    context = _context("1 e4 e5; 1 d4 d5")
    by_raw = {token.raw: token.id for token in source_tokens(context)}
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": game, "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                    for game in ("first", "second")
                ],
                "segments": [
                    {
                        "id": game,
                        "game_ref": game,
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw[white], by_raw[black]],
                        "evidence_refs": ["s1_0"],
                    }
                    for game, white, black in (("first", "e4", "e5"), ("second", "d4", "d5"))
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, source_tokens(context), {"s1_0"}, state)
    assert set(state.lines) == {("first", "main"), ("second", "main")}
    package = compile_relations(context, state)
    sequences = [item for item in package.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(sequences) == 2
    assert all(node.validation_status == "valid" for item in sequences for node in item.nodes)


def test_note_covered_ambiguous_mention_is_not_a_duplicate_issue() -> None:
    context = _context("The queen defends the c4-pawn")
    token = next(token for token in source_tokens(context) if token.raw == "c4")
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [
                    {
                        "id": "queen_plan",
                        "kind": "plan",
                        "source_refs": ["s1_0"],
                        "anchor": None,
                    }
                ],
                "unresolved": [
                    {
                        "id": "c4_mention",
                        "source_refs": ["s1_0"],
                        "move_refs": [token.id],
                        "reason": "ambiguous_relation",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, [token], {"s1_0"}, state)
    assert state.problems == []
    package = compile_relations(context, state)
    assert any(item.kind == "prose" and "c4-pawn" in item.text for item in package.items)


def test_one_missing_context_declaration_spanning_paragraphs_is_one_issue() -> None:
    context = _context("23...exf5")
    second = _context("24.Nf7+ Kh8").pages[0].fragments[0].fragment
    context = context.model_copy(
        update={
            "pages": [
                PromptEvidencePage(
                    physical_page=1,
                    fragments=[
                        context.pages[0].fragments[0],
                        PromptEvidenceFragment(order=1, fragment=second),
                    ],
                )
            ]
        }
    )
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "prior_game",
                        "source_refs": ["s1_0", "s1_1"],
                        "move_refs": [token.id for token in tokens],
                        "reason": "missing_context",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0", "s1_1"}, state)
    assert len(state.problems) == 1
    package = compile_relations(context, state)
    assert sum(item.kind == "unresolved" for item in package.items) == 1
    assert any(item.kind == "prose" and "Nf7" in item.text for item in package.items)


def test_illegal_branch_descendants_become_one_review_issue_and_prose() -> None:
    context = _context("1.e4 e5 2.Nf3 (2.Qxe5 Nc6 3.Nf3)")
    tokens = source_tokens(context)
    e4, e5, main_nf3, qxe5, nc6, branch_nf3 = (token.id for token in tokens)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [e4, e5, main_nf3],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "bad_branch",
                        "game_ref": "game",
                        "line_ref": "branch",
                        "entry": {
                            "kind": "alternative_to",
                            "target_line_ref": "main",
                            "target_move_ref": main_nf3,
                        },
                        "move_refs": [qxe5, nc6, branch_nf3],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    candidate = compile_relations(context, state)
    assert (
        sum(
            node.validation_status != "valid"
            for item in candidate.items
            if isinstance(item, MoveSequenceItemV1_1)
            for node in item.nodes
        )
        >= 1
    )
    localized = localize_invalid_relation_subtrees(context, state, candidate)
    sequence = next(item for item in localized.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.move_text for node in sequence.nodes] == ["e4", "e5", "Nf3"]
    assert sum(item.kind == "unresolved" for item in localized.items) == 1
    assert any(item.kind == "prose" and "Nc6" in item.text for item in localized.items)


def test_single_move_fragment_citation_resolves_to_its_source_token() -> None:
    context = _context("1.e4 e5")
    second = _context("2.Nf3").pages[0].fragments[0].fragment
    context = context.model_copy(
        update={
            "pages": [
                PromptEvidencePage(
                    physical_page=1,
                    fragments=[
                        context.pages[0].fragments[0],
                        PromptEvidenceFragment(order=1, fragment=second),
                    ],
                )
            ]
        }
    )
    tokens = source_tokens(context)
    e4, e5, nf3 = (token.id for token in tokens)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [e4, e5],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "next",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "continue", "after_move_ref": e5},
                        "move_refs": [nf3.rsplit("_", 1)[0]],
                        "evidence_refs": ["s1_1"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0", "s1_1"}, state)
    assert state.problems == []
    assert state.parent[nf3] == e5
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.validation_status for node in sequence.nodes] == ["valid"] * 3


def test_unique_repeated_printed_move_can_anchor_a_continuation() -> None:
    context = _context("1.e4 e5. The game returned to 1...e5 2.Nf3")
    tokens = source_tokens(context)
    e4, first_e5, repeated_e5, nf3 = (token.id for token in tokens)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [e4, first_e5],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "resumed",
                        "game_ref": "game",
                        "line_ref": "resumed_main",
                        "entry": {"kind": "continue", "after_move_ref": repeated_e5},
                        "move_refs": [nf3],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert state.problems == []
    assert state.parent[nf3] == first_e5
    assert repeated_e5 not in state.parent
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.validation_status for node in sequence.nodes] == ["valid"] * 3


def test_operational_diagram_span_is_an_unambiguous_game_seed_alias() -> None:
    context = _context("1 e4")
    marker = json.dumps(
        {
            "kind": "chess_diagram",
            "operational_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1",
            "next_formal_move": {"move_number": 1, "side_to_move": "w"},
        }
    )
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    diagram = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=marker,
        origin="diagram",
        confidence=0.9,
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, marker, "diagram", "test", "1"),
    )
    score = context.pages[0].fragments[0].fragment
    context = context.model_copy(
        update={
            "pages": [
                PromptEvidencePage(
                    physical_page=1,
                    fragments=[
                        PromptEvidenceFragment(order=0, fragment=diagram),
                        PromptEvidenceFragment(order=1, fragment=score),
                    ],
                )
            ]
        }
    )
    token = source_tokens(context)[0]
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {
                        "id": "figure_game",
                        "kind": "diagram_line",
                        "source_refs": ["s1_0"],
                        "seed_ref": "s1_0",
                    }
                ],
                "segments": [
                    {
                        "id": "line",
                        "game_ref": "figure_game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [token.id],
                        "evidence_refs": ["s1_1"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, [token], {"s1_0", "s1_1"}, state)
    assert state.problems == []
    assert state.games["figure_game"].seed_ref == "diagram_1_0"
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 1
    assert sequence.nodes[0].validation_status == "valid"


def test_missing_diagram_seed_reports_one_root_issue_for_dependent_score() -> None:
    context = _context("23...exf5 24 Nxf5 Rxf5 25 Bxf5")
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {
                        "id": "diagram_game",
                        "kind": "game",
                        "source_refs": ["s1_0"],
                        "seed_ref": "diagram_1_1",
                    }
                ],
                "segments": [
                    {
                        "id": "first",
                        "game_ref": "diagram_game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw["exf5"], by_raw["Nxf5"]],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "second",
                        "game_ref": "diagram_game",
                        "line_ref": "main",
                        "entry": {"kind": "continue", "after_move_ref": by_raw["Nxf5"]},
                        "move_refs": [by_raw["Rxf5"], by_raw["Bxf5"]],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert len(state.problems) == 1
    assert state.problems[0]["issue_code"] == "missing_context"
    package = compile_relations(context, state)
    assert sum(item.kind == "unresolved" for item in package.items) == 1
    assert not any(isinstance(item, MoveSequenceItemV1_1) for item in package.items)
    assert any(item.kind == "prose" and "Rxf5" in item.text for item in package.items)


def test_future_game_heading_without_score_stays_readable_prose() -> None:
    context = _context("Game 3")
    tokens = source_tokens(context)
    assert tokens == []
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {
                        "id": "future",
                        "kind": "game",
                        "source_refs": ["s1_0"],
                        "seed_ref": None,
                    }
                ],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "future_start",
                        "source_refs": ["s1_0"],
                        "move_refs": [],
                        "reason": "missing_context",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert state.problems == []
    package = compile_relations(context, state)
    assert any(item.kind == "prose" and item.text == "Game 3" for item in package.items)
    assert not any(item.kind == "unresolved" for item in package.items)


def test_repeated_shared_tail_keeps_unique_alternative_prefix() -> None:
    context = _context("1 e4 e5 2 Nf3 (2 Nc3)")
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw["e4"], by_raw["e5"], by_raw["Nf3"]],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "alternative",
                        "game_ref": "game",
                        "line_ref": "alt",
                        "entry": {
                            "kind": "alternative_to",
                            "target_line_ref": "main",
                            "target_move_ref": by_raw["Nf3"],
                        },
                        "move_refs": [by_raw["Nc3"], by_raw["Nf3"]],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert state.problems == []
    assert state.parent[by_raw["Nc3"]] == state.parent[by_raw["Nf3"]]
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 4
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_later_resolved_source_move_clears_prior_exact_unresolved() -> None:
    context = _context("1 e4 e5")
    tokens = source_tokens(context)
    e4, e5 = (token.id for token in tokens)
    unresolved = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "later",
                        "source_refs": ["s1_0"],
                        "move_refs": [e4],
                        "reason": "missing_context",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    resolved = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [e4, e5],
                        "evidence_refs": ["s1_0"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, unresolved, tokens, {"s1_0"}, state)
    assert len(state.problems) == 1
    apply_relations(context, resolved, tokens, {"s1_0"}, state)
    assert state.problems == []
    package = compile_relations(context, state)
    assert all(item.kind != "unresolved" for item in package.items)


def test_inline_two_move_alternative_can_be_added_from_unused_source_tokens() -> None:
    context = _context("Now 28.Bxg5? Rg6 is wrong, so play 28.Rg7+ Kh8")
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    primary = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [
                    {
                        "id": "played",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw["Rg7+"], by_raw["Kh8"]],
                        "evidence_refs": ["s1_0"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    issues = formal_score_note_issues(context, tokens, [primary])
    assert issues == [
        {
            "issue_kind": "inline_score_gap",
            "page": 1,
            "source_ref": "s1_0",
            "move_refs": [by_raw["Bxg5?"], by_raw["Rg6"]],
            "source_text": context.pages[0].fragments[0].fragment.text,
        }
    ]
    patch = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "additions": [
                {
                    "id": "alternative",
                    "game_ref": "game",
                    "line_ref": "alt",
                    "entry": {
                        "kind": "alternative_to",
                        "target_line_ref": "main",
                        "target_move_ref": by_raw["Rg7+"],
                    },
                    "move_refs": [by_raw["Bxg5?"], by_raw["Rg6"]],
                    "evidence_refs": ["s1_0"],
                }
            ],
        }
    )
    revised = apply_relation_patches([primary], patch)
    assert [segment.id for segment in revised[0].segments] == ["played", "alternative"]
    assert primary.segments[0].move_refs == [by_raw["Rg7+"], by_raw["Kh8"]]


def test_numbered_alternative_inside_prose_note_requests_local_review() -> None:
    context = _context("Later we examine 6...c5 7.d5 e6 (7...b5) 8.Bd3 exd5")
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [
                    {
                        "id": "alternative_as_prose",
                        "kind": "prose",
                        "source_refs": ["s1_0"],
                        "anchor": None,
                    }
                ],
                "unresolved": [],
            }
        )
    )
    issues = formal_score_note_issues(context, tokens, [response])
    assert len(issues) == 1
    assert issues[0]["issue_kind"] == "embedded_score_note"
    assert issues[0]["note_id"] == "alternative_as_prose"
    assert issues[0]["move_refs"] == [token.id for token in tokens]


def test_unclaimed_numbered_move_order_is_not_silently_copied_as_prose() -> None:
    context = _context("runs: 3.Nc3 Bg7 4.e4 d6 5.h3 O-O 6.Be3")
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    issues = formal_score_note_issues(context, tokens, [response])
    assert len(issues) == 1
    assert issues[0]["issue_kind"] == "unclaimed_score_span"
    assert issues[0]["move_refs"] == [token.id for token in tokens]


def test_declared_missing_context_score_does_not_trigger_a_second_omission_issue() -> None:
    context = _context("23...exf5 24.Nf7+ Kh8 25.Qg6")
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "prior_game",
                        "source_refs": ["s1_0"],
                        "move_refs": [token.id for token in tokens],
                        "reason": "missing_context",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    assert formal_score_note_issues(context, tokens, [response]) == []


def test_reused_prefix_with_new_suffix_stays_reviewable_and_can_branch() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6 3 Bb5 a6; 3 Bc4 Bc5")
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    main_refs = [by_raw[move] for move in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6")]
    alt_refs = [by_raw[move] for move in ("Bc4", "Bc5")]
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": game, "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                    for game in ("main_game", "wrong_example")
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "main_game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": main_refs,
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "lost_example",
                        "game_ref": "wrong_example",
                        "line_ref": "example",
                        "entry": {"kind": "root"},
                        "move_refs": [*main_refs[:4], *alt_refs],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    candidate = compile_relations(context, state)
    assert sum(item.kind == "unresolved" for item in candidate.items) == 1
    assert any(
        issue["issue_kind"] == "uncompiled_segment"
        for issue in validation_relation_issues(candidate, state, [response], tokens)
    )
    patch = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "replacements": [
                {
                    "segment_id": "lost_example",
                    "source_refs": ["s1_0"],
                    "segments": [
                        {
                            "id": "real_alt",
                            "game_ref": "main_game",
                            "line_ref": "alt",
                            "entry": {
                                "kind": "alternative_to",
                                "target_line_ref": "main",
                                "target_move_ref": by_raw["Bb5"],
                            },
                            "move_refs": alt_refs,
                            "evidence_refs": ["s1_0"],
                        }
                    ],
                }
            ],
        }
    )
    repaired = apply_relation_patches([response], patch)
    state = RelationState()
    apply_relations(context, repaired[0], tokens, {"s1_0"}, state)
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 8
    assert not any(item.kind == "unresolved" for item in package.items)
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_cited_previous_ply_normalizes_alternative_entry_to_branch_after() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6 3 Bb5 a6; 3 Bc4")
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {
                        "id": "game",
                        "kind": "game",
                        "source_refs": ["s1_0"],
                        "seed_ref": "start",
                    }
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw[x] for x in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6")],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "alternative",
                        "game_ref": "game",
                        "line_ref": "alt",
                        "entry": {
                            "kind": "alternative_to",
                            "target_line_ref": "main",
                            "target_move_ref": by_raw["Nc6"],
                        },
                        "move_refs": [by_raw["Bc4"]],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    assert state.parent[by_raw["Bc4"]] == by_raw["Nc6"]
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_repeated_score_and_same_ply_choices_do_not_trigger_omission_patch() -> None:
    context = _context("1.e4 e5; again 1.e4 e5. Choose 9...dxe4, 9...Na6")
    tokens = source_tokens(context)
    e4 = [token.id for token in tokens if token.raw == "e4"]
    e5 = [token.id for token in tokens if token.raw == "e5"]
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [e4[0], e5[0]],
                        "evidence_refs": ["s1_0"],
                    }
                ],
                "notes": [
                    {"id": "repeated", "kind": "mention", "source_refs": ["s1_0"], "anchor": None}
                ],
                "unresolved": [],
            }
        )
    )
    assert formal_score_note_issues(context, tokens, [response]) == []


def test_patch_can_add_independent_complete_move_order_example() -> None:
    context = _context("1.e4 g6 2.d4 Bg7")
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [
                    {
                        "id": "transposition",
                        "kind": "mention",
                        "source_refs": ["s1_0"],
                        "anchor": None,
                    }
                ],
                "unresolved": [],
            }
        )
    )
    patch = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "games": [
                {
                    "id": "move_order_example",
                    "kind": "example",
                    "source_refs": ["s1_0"],
                    "seed_ref": "start",
                }
            ],
            "additions": [
                {
                    "id": "example_score",
                    "game_ref": "move_order_example",
                    "line_ref": "main",
                    "entry": {"kind": "root"},
                    "move_refs": [token.id for token in tokens],
                    "evidence_refs": ["s1_0"],
                }
            ],
        }
    )
    revised = apply_relation_patches([response], patch)
    state = RelationState()
    apply_relations(context, revised[0], tokens, {"s1_0"}, state)
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 4
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_descriptive_board_squares_remain_prose_not_false_review_issues() -> None:
    for source, raw in (
        ("The h6-bishop is protected.", "h6"),
        ("The d5-square is weak.", "d5"),
        ("The g2-bishop is active.", "g2"),
        ("This retreat weakens f5!", "f5!"),
    ):
        context = _context(source)
        tokens = source_tokens(context)
        token = next(token for token in tokens if token.raw == raw)
        response = parse_relation_response(
            json.dumps(
                {
                    "schema_version": "chess-source-relations/1",
                    "games": [],
                    "segments": [],
                    "notes": [],
                    "unresolved": [
                        {
                            "id": "false_square",
                            "source_refs": ["s1_0"],
                            "move_refs": [token.id],
                            "reason": "unparsed_notation",
                            "candidates": [],
                        }
                    ],
                }
            )
        )
        state = RelationState()
        apply_relations(context, response, tokens, {"s1_0"}, state)
        assert state.problems == []
        package = compile_relations(context, state)
        assert not any(item.kind == "unresolved" for item in package.items)
        assert any(item.kind == "prose" and item.text == source for item in package.items)

    score = _context("1.d5")
    score_token = source_tokens(score)[0]
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "actual_score",
                        "source_refs": ["s1_0"],
                        "move_refs": [score_token.id],
                        "reason": "unparsed_notation",
                        "candidates": [],
                    }
                ],
            }
        )
    )
    state = RelationState()
    apply_relations(score, response, [score_token], {"s1_0"}, state)
    assert len(state.problems) == 1


def test_joined_printed_score_retains_every_move_and_exact_offsets() -> None:
    source = "12...Rc8 13Qd1Qc7 14 Nf1Qc2 15QXc2"
    tokens = source_tokens(_context(source))
    assert [(token.raw, source[token.start : token.end]) for token in tokens] == [
        ("Rc8", "Rc8"),
        ("Qd1", "Qd1"),
        ("Qc7", "Qc7"),
        ("Nf1", "Nf1"),
        ("Qc2", "Qc2"),
        ("QXc2", "QXc2"),
    ]
    continuation = "RXb7 16 c6 Rc7 17 RXd7 RXd7 18 BXg5QXg5"
    assert [token.raw for token in source_tokens(_context(continuation))][-2:] == ["BXg5", "QXg5"]


def test_bare_back_rank_square_in_prose_is_not_a_move_token() -> None:
    tokens = source_tokens(_context("if the king moves to h8, but 1...Kh8 or h7-h8=Q"))
    assert "h8" not in [token.raw for token in tokens]
    assert "Kh8" in [token.raw for token in tokens]


def test_one_source_cited_relation_clarification_repairs_branch_and_resumption() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6 (2...d6) 3 Bb5")
    by_raw = {token.raw: token.id for token in source_tokens(context)}
    initial = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "opening",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": [by_raw[value] for value in ("e4", "e5", "Nf3", "Nc6")],
                "evidence_refs": ["s1_0"],
            },
            {
                "id": "wrong_branch",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "continue", "after_move_ref": by_raw["Nc6"]},
                "move_refs": [by_raw["d6"]],
                "evidence_refs": ["s1_0"],
            },
            {
                "id": "wrong_return",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "continue", "after_move_ref": by_raw["d6"]},
                "move_refs": [by_raw["Bb5"]],
                "evidence_refs": ["s1_0"],
            },
        ],
        "notes": [],
        "unresolved": [],
    }
    correction = {
        "schema_version": "chess-source-relation-patch/1",
        "patches": [
            {
                "segment_id": "wrong_branch",
                "line_ref": "var_d6",
                "entry": {
                    "kind": "alternative_to",
                    "target_line_ref": "main",
                    "target_move_ref": by_raw["Nc6"],
                },
                "source_refs": ["s1_0"],
            },
            {
                "segment_id": "wrong_return",
                "line_ref": "main",
                "entry": {"kind": "continue", "after_move_ref": by_raw["Nc6"]},
                "source_refs": ["s1_0"],
            },
        ],
    }
    correction["replacements"] = [
        {
            "segment_id": "opening",
            "source_refs": ["s1_0"],
            "segments": [
                {
                    **initial["segments"][0],
                    "move_refs": [by_raw["e4"], by_raw["e4"]],
                }
            ],
        }
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(value),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
            for value in (initial, correction)
        ]
    )
    result = asyncio.run(generate_relation_chunks(context, provider))
    assert len(result.chunks) == 2
    assert result.chunks[-1].applied is True
    assert result.chunks[-1].applied_patch is not None
    assert json.loads(result.chunks[-1].applied_patch)["replacements"] == []
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 6
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    by_move = {node.move_text: node for node in sequence.nodes}
    assert by_move["d6"].parent_id == by_move["Nf3"].id
    assert by_move["Bb5"].parent_id == by_move["Nc6"].id


def test_source_cited_demotion_keeps_prose_without_false_move() -> None:
    context = _context("1 e4 e5; if the king moves to h6 then 2 Bg7#")
    by_raw = {token.raw: token.id for token in source_tokens(context)}
    primary = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "main",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw["e4"], by_raw["e5"]],
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "false_square",
                        "game_ref": "game",
                        "line_ref": "false_square",
                        "entry": {
                            "kind": "branch_after",
                            "target_line_ref": "main",
                            "target_move_ref": by_raw["e5"],
                        },
                        "move_refs": [by_raw["h6"]],
                        "evidence_refs": ["s1_0"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    correction = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "demotions": [{"segment_id": "false_square", "source_refs": ["s1_0"]}],
        }
    )
    response = apply_relation_patches([primary], correction)[0]
    state = RelationState()
    apply_relations(context, response, source_tokens(context), {"s1_0"}, state)
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.move_text for node in sequence.nodes] == ["e4", "e5"]
    assert any(item.kind == "prose" and "king moves to h6" in item.text for item in package.items)


def test_formal_score_note_is_reviewed_and_can_be_promoted_to_variation() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6")
    box = NormalizedBox(x0=0.1, y0=0.3, x1=0.9, y1=0.4)
    text = "2...d6"
    context.pages[0].fragments.append(
        PromptEvidenceFragment(
            order=1,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=text,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "test", "1"),
                style_runs=[TextStyleRun(start=0, end=len(text), color="#000080", bold=True)],
            ),
        )
    )
    by_raw = {token.raw: token.id for token in source_tokens(context)}
    initial = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "main",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": [by_raw[value] for value in ("e4", "e5", "Nf3", "Nc6")],
                "evidence_refs": ["s1_0"],
            }
        ],
        "notes": [{"id": "note_d6", "kind": "annotation", "source_refs": ["s1_1"], "anchor": None}],
        "unresolved": [],
    }
    correction = {
        "schema_version": "chess-source-relation-patch/1",
        "patches": [],
        "promotions": [
            {
                "note_id": "note_d6",
                "source_refs": ["s1_1"],
                "segment": {
                    "id": "var_d6",
                    "game_ref": "game",
                    "line_ref": "var_d6",
                    "entry": {
                        "kind": "alternative_to",
                        "target_line_ref": "main",
                        "target_move_ref": by_raw["Nc6"],
                    },
                    "move_refs": [by_raw["d6"]],
                    "evidence_refs": ["s1_1"],
                },
            }
        ],
    }
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(value), provider="scripted", model="test", finish_reason="stop"
            )
            for value in (initial, correction)
        ]
    )
    result = asyncio.run(generate_relation_chunks(context, provider))
    assert len(result.chunks) == 2
    assert result.chunks[-1].applied is True
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 5
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    d6 = next(node for node in sequence.nodes if node.move_text == "d6")
    nf3 = next(node for node in sequence.nodes if node.move_text == "Nf3")
    assert d6.parent_id == nf3.id


def test_diagram_next_move_hint_is_not_a_duplicate_source_move() -> None:
    context = _context("1 e4 e5")
    box = NormalizedBox(x0=0.1, y0=0.3, x1=0.9, y1=0.4)
    diagram_text = '{"next_formal_move":{"source_token":"Nf3"}}'
    diagram_hash = source_fragment_sha256(1, box, diagram_text, "diagram", "test", "1")
    diagram = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=diagram_text,
        origin="diagram",
        engine_name="test",
        engine_version="1",
        fragment_sha256=diagram_hash,
        confidence=1.0,
    )
    score_text = "2 Nf3"
    score_box = NormalizedBox(x0=0.1, y0=0.5, x1=0.9, y1=0.6)
    score = SourceEvidenceFragment(
        physical_page=1,
        box=score_box,
        text=score_text,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(
            1, score_box, score_text, "embedded_text", "test", "1"
        ),
    )
    context.pages[0].fragments.extend(
        [
            PromptEvidenceFragment(order=1, fragment=diagram),
            PromptEvidenceFragment(order=2, fragment=score),
        ]
    )
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "before",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [
                            by_raw["e4"],
                            by_raw["e5"],
                            {"fragment_ref": diagram_hash, "quote": "Nf3", "occurrence": 0},
                        ],
                        "evidence_refs": ["s1_0", "s1_1"],
                    },
                    {
                        "id": "after",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "continue", "after_move_ref": by_raw["e5"]},
                        "move_refs": [by_raw["Nf3"]],
                        "evidence_refs": ["s1_2"],
                    },
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0", "s1_1", "s1_2"}, state)
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.move_text for node in sequence.nodes] == ["e4", "e5", "Nf3"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_one_ambiguous_line_is_one_review_issue_with_its_candidate() -> None:
    context = _context("1 e4 e5 2 Nf3")
    tokens = source_tokens(context)
    response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [],
                "notes": [],
                "unresolved": [
                    {
                        "id": "uncertain_line",
                        "source_refs": ["s1_0"],
                        "move_refs": [token.id for token in tokens],
                        "reason": "ambiguous_relation",
                        "candidates": [
                            {
                                "game_ref": "game",
                                "line_ref": "main",
                                "entry": {"kind": "root"},
                            }
                        ],
                    }
                ],
            }
        )
    )
    state = RelationState()
    apply_relations(context, response, tokens, {"s1_0"}, state)
    package = compile_relations(context, state)
    unresolved = [item for item in package.items if item.kind == "unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].reason_code == "ambiguous_relation"
    assert unresolved[0].raw_text == "e4 e5 2 Nf3"
    assert '"game_ref":"game"' in (unresolved[0].details or "")


def test_local_replacement_skips_repeated_source_move_and_keeps_analysis_line() -> None:
    context = _context("1 e4 e5 2 Nf3 Nc6 3 Bb5 (3 Bb5 a6)")
    by_raw: dict[str, list[str]] = {}
    for token in source_tokens(context):
        by_raw.setdefault(token.raw, []).append(token.id)
    first = [by_raw[move][0] for move in ("e4", "e5", "Nf3", "Nc6", "Bb5")]
    repeated = by_raw["Bb5"][1]
    a6 = by_raw["a6"][0]
    initial = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "mixed",
                "game_ref": "game",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": [*first, repeated, a6],
                "evidence_refs": ["s1_0"],
            }
        ],
        "notes": [],
        "unresolved": [],
    }
    replacement = {
        "schema_version": "chess-source-relation-patch/1",
        "patches": [],
        "replacements": [
            {
                "segment_id": "mixed",
                "source_refs": ["s1_0"],
                "segments": [
                    {
                        "id": "opening",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": first,
                        "evidence_refs": ["s1_0"],
                    },
                    {
                        "id": "analysis",
                        "game_ref": "game",
                        "line_ref": "analysis",
                        "entry": {
                            "kind": "branch_after",
                            "target_line_ref": "main",
                            "target_move_ref": first[-1],
                        },
                        "move_refs": [a6],
                        "evidence_refs": ["s1_0"],
                    },
                ],
            }
        ],
    }
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(value), provider="scripted", model="test", finish_reason="stop"
            )
            for value in (initial, replacement)
        ]
    )
    result = asyncio.run(generate_relation_chunks(context, provider))
    assert result.chunks[-1].applied is True
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.move_text for node in sequence.nodes] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert any(item.kind == "prose" and "Bb5" in item.text for item in result.package.items)


def test_truncated_trailing_notes_keep_complete_relationships() -> None:
    full = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "g", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "opening",
                "game_ref": "g",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": ["t1_0_2"],
                "evidence_refs": ["s1_0"],
            }
        ],
        "notes": [],
        "unresolved": [],
    }
    complete_moves = json.dumps(full, separators=(",", ":"))
    cut_in_notes = complete_moves.replace(
        '"notes":[],"unresolved":[]}', '"notes":[{"id":"unfinished'
    )
    recovered = recover_completed_relation_prefix(cut_in_notes)
    assert recovered is not None
    assert [segment.id for segment in recovered.segments] == ["opening"]
    assert recovered.notes == []
    cut_in_moves = complete_moves[: complete_moves.index('"notes":') - 6]
    assert recover_completed_relation_prefix(cut_in_moves) is None


def test_styled_score_detects_legal_wrong_parent_and_accepts_cited_patch() -> None:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    pages = []
    for page_number, lines in (
        (1, [("1.e4", True), ("1.d4", False), ("1...e5", True), ("2.Nf3", True)]),
        (2, [("2...Nc6", True), ("3.g3", True)]),
    ):
        entries = []
        for order, (source, bold) in enumerate(lines):
            fragment = SourceEvidenceFragment(
                physical_page=page_number,
                box=box,
                text=source,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(
                    page_number, box, source, "embedded_text", "test", "1"
                ),
                style_runs=[
                    TextStyleRun(
                        start=0,
                        end=len(source),
                        font_family="Test",
                        font_size=12.0,
                        bold=bold,
                        color="#000000",
                    )
                ],
            )
            entries.append(PromptEvidenceFragment(order=order, fragment=fragment))
        pages.append(PromptEvidencePage(physical_page=page_number, fragments=entries))
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000031"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="source",
        media_type="application/pdf",
        first_page=1,
        last_page=2,
        pages=pages,
        max_output_tokens=1000,
        max_prompt_chars=30000,
    )
    refs = {token.raw: token.id for token in source_tokens(context)}
    relation = {
        "schema_version": "chess-source-relations/1",
        "games": [{"id": "g", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}],
        "segments": [
            {
                "id": "main",
                "game_ref": "g",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": [refs["e4"]],
                "evidence_refs": ["s1_0"],
            },
            {
                "id": "other_white",
                "game_ref": "g",
                "line_ref": "other",
                "entry": {
                    "kind": "alternative_to",
                    "target_line_ref": "main",
                    "target_move_ref": refs["e4"],
                },
                "move_refs": [refs["d4"]],
                "evidence_refs": ["s1_1"],
            },
            {
                "id": "reply",
                "game_ref": "g",
                "line_ref": "other",
                "entry": {"kind": "continue", "after_move_ref": refs["d4"]},
                "move_refs": [refs["e5"]],
                "evidence_refs": ["s1_2"],
            },
        ],
        "notes": [],
        "unresolved": [],
    }
    patch = {
        "schema_version": "chess-source-relation-patch/1",
        "patches": [
            {
                "segment_id": "reply",
                "line_ref": "main",
                "entry": {"kind": "continue", "after_move_ref": refs["e4"]},
                "source_refs": ["s1_2"],
            }
        ],
    }
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(relation),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
        ]
    )
    patch_provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(patch),
                provider="scripted",
                model="patch-test",
                finish_reason="stop",
            )
        ]
    )
    result = asyncio.run(generate_relation_chunks(context, provider, patch_provider=patch_provider))
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    moves = {node.san_candidate: node for node in sequence.nodes}
    assert len(provider.calls) == 1
    assert len(patch_provider.calls) == 1
    assert result.chunks[1].response.model == "patch-test"
    assert result.chunks[1].applied is True
    assert moves["e5"].parent_id == moves["e4"].id
    assert all(node.validation_status == "valid" for node in sequence.nodes)

    unchanged = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(value),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
            for value in (
                relation,
                {"schema_version": "chess-source-relation-patch/1", "patches": []},
            )
        ]
    )
    still_ambiguous = asyncio.run(generate_relation_chunks(context, unchanged))
    assert any(
        item.kind == "unresolved" and item.reason_code == "ambiguous_relation"
        for item in still_ambiguous.package.items
    )


def test_later_window_reuses_read_only_score_prefix_as_anchor() -> None:
    """A model may repeat known source moves before its newly owned continuation."""
    context = _context("1 e4 e5")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    text = "2 Nf3 Nc6"
    second = SourceEvidenceFragment(
        physical_page=2,
        box=box,
        text=text,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(2, box, text, "embedded_text", "test", "1"),
    )
    context = context.model_copy(
        update={
            "last_page": 2,
            "pages": [
                *context.pages,
                PromptEvidencePage(
                    physical_page=2,
                    fragments=[PromptEvidenceFragment(order=0, fragment=second)],
                ),
            ],
        }
    )
    tokens = source_tokens(context)
    by_raw = {token.raw: token.id for token in tokens}
    first = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "game", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "first",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": [by_raw["e4"], by_raw["e5"]],
                        "evidence_refs": ["s1_0"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    second_response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [],
                "segments": [
                    {
                        "id": "second",
                        "game_ref": "game",
                        "line_ref": "main",
                        "entry": {"kind": "continue", "after_move_ref": by_raw["e5"]},
                        "move_refs": [
                            by_raw["e4"],
                            by_raw["e5"],
                            by_raw["Nf3"],
                            by_raw["Nc6"],
                        ],
                        "evidence_refs": ["s1_0", "s2_0"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(context, first, tokens, {"s1_0"}, state)
    apply_relations(context, second_response, tokens, {"s2_0"}, state)
    assert state.parent[by_raw["Nf3"]] == by_raw["e5"]
    assert state.parent[by_raw["Nc6"]] == by_raw["Nf3"]
    package = compile_relations(context, state)
    sequence = next(item for item in package.items if isinstance(item, MoveSequenceItemV1_1))
    assert len(sequence.nodes) == 4
    assert all(node.validation_status == "valid" for node in sequence.nodes)
