"""One cross-page score with an alternative and one independent new game."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from chess_workbench.extraction.chunks import generate_semantic_page_chunks
from chess_workbench.extraction.contracts import MoveSequenceItemV1_1
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
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


def test_page_chunks_continue_branch_and_keep_new_game_separate() -> None:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    pages = []
    for page_number, source in (
        (1, "1.e4 e5 2.Nf3 Nc6 (2...d6)"),
        (2, "3.Bb5 a6 New game: 1.d4 d5"),
    ):
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
        )
        pages.append(
            PromptEvidencePage(
                physical_page=page_number,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000021"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=2,
        pages=pages,
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )

    def move(event_id: str, page: int, quote: str, sequence: str, parent: str | None):
        return {
            "id": event_id,
            "kind": "move",
            "source": {"page": page, "order": 0, "quote": quote},
            "sequence": sequence,
            "parent": parent,
        }

    responses = [
        [
            move("m1", 1, "e4", "game", None),
            move("m2", 1, "e5", "game", "m1"),
            move("m3", 1, "Nf3", "game", "m2"),
            move("m4", 1, "Nc6", "game", "m3"),
            move("m5", 1, "d6", "game", "m3"),
        ],
        [
            move("m1", 2, "Bb5", "game", "c1_m4"),
            move("m2", 2, "a6", "game", "m1"),
            move("m3", 2, "d4", "new_game", None),
            move("m4", 2, "d5", "new_game", "m3"),
        ],
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps({"events": events}),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
            for events in responses
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    sequences = [item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(result.chunks) == 2
    assert len(sequences) == 2
    assert [[node.move_text for node in item.nodes] for item in sequences] == [
        ["e4", "e5", "Nf3", "Nc6", "d6", "Bb5", "a6"],
        ["d4", "d5"],
    ]
    assert all(node.validation_status == "valid" for item in sequences for node in item.nodes)
    assert sequences[0].nodes[5].parent_id == sequences[0].nodes[3].id
    assert sequences[0].nodes[4].parent_id == sequences[0].nodes[3].parent_id
    assert sequences[1].nodes[0].parent_id is None
    second_request = json.loads(provider.calls[1].messages[1].content)
    assert [page["page"] for page in second_request["pages"]] == [2]
    assert any(move["event_id"] == "c1_m4" for move in second_request["prior_moves"])
    assert (
        next(move for move in second_request["prior_moves"] if move["event_id"] == "c1_m5")[
            "mainline"
        ]
        == "false"
    )


def test_external_document_anchor_composes_with_independent_new_game() -> None:
    import hashlib

    from chess_workbench.extraction.contracts import PageRange
    from chess_workbench.extraction.incremental import (
        _canonical_package_bytes,
        build_ccef_continuation_context,
        compose_incremental_ccef,
    )
    from chess_workbench.extraction.source_compiler import compile_semantic_events

    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)

    def context(page_number: int, source: str, package_id: str) -> CcefPromptContext:
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
        )
        return CcefPromptContext(
            package_id=UUID(package_id),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_ref="test-pdf",
            media_type="application/pdf",
            first_page=page_number,
            last_page=page_number,
            pages=[
                PromptEvidencePage(
                    physical_page=page_number,
                    fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
                )
            ],
            max_output_tokens=1000,
            max_prompt_chars=10000,
        )

    base_context = context(1, "1.e4 e5", "00000000-0000-0000-0000-000000000031")
    base = compile_semantic_events(
        base_context,
        [
            {
                "id": event_id,
                "kind": "move",
                "sequence": "game",
                "parent": parent,
                "source": {"page": 1, "order": 0, "start": start, "end": end},
            }
            for event_id, parent, start, end in (
                ("e4", None, 2, 4),
                ("e5", "e4", 5, 7),
            )
        ],
    )
    base_sha = hashlib.sha256(_canonical_package_bytes(base)).hexdigest()
    continuation = build_ccef_continuation_context(
        base,
        base_normalized_ccef_sha256=base_sha,
        next_page_range=PageRange(start_page=2, end_page=2),
    )
    anchor = next(
        anchor
        for sequence in continuation.sequences
        for anchor in sequence.anchors
        if anchor.after_node_id is not None and anchor.position_fen.split()[1] == "w"
    )
    next_context = context(2, "2.Nf3 Nc6 New game 1.d4 d5", "00000000-0000-0000-0000-000000000032")
    response = {
        "events": [
            {
                "id": "m1",
                "kind": "move",
                "sequence": "continued",
                "parent": None,
                "continuation_anchor": anchor.id,
                "source": {"page": 2, "order": 0, "quote": "Nf3"},
            },
            {
                "id": "m2",
                "kind": "move",
                "sequence": "continued",
                "parent": "m1",
                "source": {"page": 2, "order": 0, "quote": "Nc6"},
            },
            {
                "id": "new1",
                "kind": "move",
                "sequence": "other",
                "parent": None,
                "source": {"page": 2, "order": 0, "quote": "d4"},
            },
            {
                "id": "new2",
                "kind": "move",
                "sequence": "other",
                "parent": "new1",
                "source": {"page": 2, "order": 0, "quote": "d5"},
            },
        ]
    }
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(response),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
        ]
    )
    generated = asyncio.run(
        generate_semantic_page_chunks(
            next_context,
            provider,
            external_anchors=[
                {"event_id": anchor.id, "fen_after": anchor.position_fen, "external": "true"}
            ],
            external_base_sha256=base_sha,
        )
    )
    aggregate = compose_incremental_ccef(
        base,
        generated.package,
        context=continuation,
        document_id=UUID("00000000-0000-0000-0000-000000000033"),
    )
    sequences = [item for item in aggregate.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(sequences) == 2
    assert [[node.move_text for node in item.nodes] for item in sequences] == [
        ["e4", "e5", "Nf3", "Nc6"],
        ["d4", "d5"],
    ]
    assert all(node.validation_status == "valid" for item in sequences for node in item.nodes)
    request = json.loads(provider.calls[0].messages[1].content)
    assert request["prior_moves"][0]["event_id"] == anchor.id


def test_bad_second_chunk_preserves_first_score_and_local_source() -> None:
    from chess_workbench.extraction.contracts import UnresolvedItem

    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    pages = []
    for page_number, source in ((1, "1.e4 e5"), (2, "2.Nf3 Nc6")):
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
        )
        pages.append(
            PromptEvidencePage(
                physical_page=page_number,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000041"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=2,
        pages=pages,
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(
                    {
                        "events": [
                            {
                                "id": "a",
                                "kind": "move",
                                "sequence": "game",
                                "parent": None,
                                "source": {"page": 1, "order": 0, "quote": "e4"},
                            },
                            {
                                "id": "b",
                                "kind": "move",
                                "sequence": "game",
                                "parent": "a",
                                "source": {"page": 1, "order": 0, "quote": "e5"},
                            },
                        ]
                    }
                ),
                provider="scripted",
                model="test",
                finish_reason="stop",
            ),
            StructuredGenerationResponse(
                content="{bad json", provider="scripted", model="test", finish_reason="stop"
            ),
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    unresolved = next(item for item in result.package.items if isinstance(item, UnresolvedItem))
    assert [node.validation_status for node in sequence.nodes] == ["valid", "valid"]
    assert unresolved.reason_code == "semantic_chunk_failed"
    assert unresolved.raw_text == "2.Nf3 Nc6"
    assert unresolved.evidence[0].page == 2


def test_long_single_page_uses_semantic_boundary_and_original_source_orders() -> None:
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    texts = ["1.e4 e5", "Chapter 2", "1.d4 d5"]
    fragments = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=value,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, value, "embedded_text", "test", "1"),
            ),
        )
        for order, value in enumerate(texts)
    ]
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000041"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=fragments)],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    responses = [
        {
            "events": [
                {
                    "id": "m1",
                    "kind": "move",
                    "sequence": "old",
                    "parent": None,
                    "source": {"page": 1, "order": 0, "quote": "e4"},
                },
                {
                    "id": "m2",
                    "kind": "move",
                    "sequence": "old",
                    "parent": "m1",
                    "source": {"page": 1, "order": 0, "quote": "e5"},
                },
            ]
        },
        {
            "events": [
                {
                    "id": "h1",
                    "kind": "heading",
                    "source": {"page": 1, "order": 0, "quote": "Chapter 2"},
                },
                {
                    "id": "m1",
                    "kind": "move",
                    "sequence": "new",
                    "parent": None,
                    "source": {"page": 1, "order": 1, "quote": "d4"},
                },
                {
                    "id": "m2",
                    "kind": "move",
                    "sequence": "new",
                    "parent": "m1",
                    "source": {"page": 1, "order": 1, "quote": "d5"},
                },
            ]
        },
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps(response),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
            for response in responses
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    assert len(result.chunks) == 2
    sequences = [item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1)]
    assert len(sequences) == 2
    assert all(node.validation_status == "valid" for item in sequences for node in item.nodes)
    assert (
        sequences[1].nodes[0].evidence[0].fragment_sha256 == fragments[2].fragment.fragment_sha256
    )
    assert result.package.items[1].kind == "heading"


def test_prior_moves_follow_printed_source_across_illustrative_score() -> None:
    """Catalan: a left-column example must not become the next page's tail."""
    from chess_workbench.extraction.chunks import _prior_moves
    from chess_workbench.extraction.source_compiler import compile_semantic_events

    texts = ("1 d4", "1 c4 e6", "1... d5 2 c4")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.4, y1=0.2)
    fragments = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=text,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, text, "embedded_text", "test", "1"),
            ),
        )
        for order, text in enumerate(texts)
    ]
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000051"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=fragments)],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    specs = [
        ("game_start", 0, "d4", "game", None),
        ("example_start", 1, "c4", "example", None),
        ("example_reply", 1, "e6", "example", "example_start"),
        ("game_reply", 2, "d5", "resumed", None),
        ("game_next", 2, "c4", "resumed", "game_reply"),
    ]
    events = []
    cursors = [0, 0, 0]
    for event_id, order, quote, sequence, parent in specs:
        start = texts[order].index(quote, cursors[order])
        cursors[order] = start + len(quote)
        events.append(
            {
                "id": event_id,
                "kind": "move",
                "sequence": sequence,
                "parent": parent,
                "source": {
                    "page": 1,
                    "order": order,
                    "start": start,
                    "end": cursors[order],
                },
            }
        )
    package = compile_semantic_events(context, events)
    prior = _prior_moves(package, events)
    assert [hint["event_id"] for hint in prior] == [
        "game_start",
        "example_start",
        "example_reply",
        "game_reply",
        "game_next",
    ]
    assert prior[-1]["parent_event_id"] == "game_reply"
    assert prior[-1]["sequence_id"] == prior[-2]["sequence_id"]


def test_move_run_keeps_unnumbered_token_after_line_wrap() -> None:
    from chess_workbench.extraction.draft import (
        find_move_runs,
        find_numbered_move_hints,
        find_wrapped_moves,
    )
    from chess_workbench.extraction.interpretation import resolve_semantic_response

    lines = (
        "13 Ng5 Qg6 14 Qc4",
        "Rd5! 15 f4 a6",
        "6 0-0 0-0-0 7 c4?",
        "8 ... e5!",
        "7 c4 (7 Nc3 Qf5) 7...Qf5 8 Nc3",
        "8...e5 9",
        "h3",
    )
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=line,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, line, "embedded_text", "test", "1"),
            ),
        )
        for order, line in enumerate(lines)
    ]
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000025"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=entries)],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    runs = find_move_runs(context)
    wrapped = next(run for run in runs if run.order == 1 and run.start == 0)
    assert wrapped.tokens == ("Rd5!", "f4", "a6")
    assert next(run for run in runs if run.order == 2).tokens == ("0-0", "0-0-0", "c4?")
    assert any(hint.quote == "8 ... e5!" for hint in find_numbered_move_hints(context))
    nested = next(run for run in runs if run.order == 4 and run.tokens[0] == "Nc3")
    assert nested.paren_depth == 1
    outer = next(run for run in runs if run.order == 4 and run.tokens[0] == "Qf5")
    assert outer.paren_depth == 0
    assert find_wrapped_moves(context)[-1].move_text == "h3"
    resolved = resolve_semantic_response(
        context,
        json.dumps(
            {
                "events": [
                    {
                        "id": "wrapped",
                        "kind": "move",
                        "sequence": "game",
                        "source": {"page": 1, "order": 5, "quote": "9"},
                    }
                ]
            }
        ),
    )
    assert resolved[0]["source"] == {"page": 1, "order": 6, "start": 0, "end": 2}


def test_missing_printed_moves_are_recovered_only_across_legal_neighbors() -> None:
    source = "1 e4 e5 2 Nf3 2...Nc6"
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=source,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, source, "embedded_text", "test", "1"),
    )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000026"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
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
    for included in (("e4", "e5", "Nc6"), ("e4", "Nc6")):
        events = [
            {
                "id": f"m{index}",
                "kind": "move",
                "sequence": "game",
                "parent": f"m{index - 1}" if index else None,
                "source": {"page": 1, "order": 0, "quote": move},
            }
            for index, move in enumerate(included)
        ]
        provider = ScriptedStructuredGenerationProvider(
            [
                StructuredGenerationResponse(
                    content=json.dumps({"events": events}),
                    provider="scripted",
                    model="test",
                    finish_reason="stop",
                )
            ]
        )
        result = asyncio.run(generate_semantic_page_chunks(context, provider))
        sequence = next(
            item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1)
        )
        assert [node.san_candidate for node in sequence.nodes] == ["e4", "e5", "Nf3", "Nc6"]
        assert all(node.validation_status == "valid" for node in sequence.nodes)
        assert any(node.move_text == "Nf3" for node in sequence.nodes)


def test_invalid_move_mention_between_prose_stays_readable_text() -> None:
    texts = ("1.e4 e5", "on the 2 ... Qxd5 Scandinavian.")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=value,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, value, "embedded_text", "test", "1"),
            ),
        )
        for order, value in enumerate(texts)
    ]
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000027"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=entries)],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    events = [
        {
            "id": "m1",
            "kind": "move",
            "sequence": "game",
            "source": {"page": 1, "order": 0, "quote": "e4"},
        },
        {
            "id": "m2",
            "kind": "move",
            "sequence": "game",
            "parent": "m1",
            "source": {"page": 1, "order": 0, "quote": "e5"},
        },
        {"id": "before", "kind": "prose", "source": {"page": 1, "order": 1, "quote": "on the"}},
        {
            "id": "mention",
            "kind": "move",
            "sequence": "game",
            "parent": "m2",
            "source": {"page": 1, "order": 1, "quote": "2 ... Qxd5"},
        },
        {
            "id": "after",
            "kind": "prose",
            "source": {"page": 1, "order": 1, "quote": "Scandinavian."},
        },
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps({"events": events}),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    sequences = [item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1)]
    assert [node.san_candidate for node in sequences[0].nodes] == ["e4", "e5"]
    assert all(node.validation_status == "valid" for node in sequences[0].nodes)
    assert any(item.kind == "prose" and item.text == "2 ... Qxd5" for item in result.package.items)


def test_numbered_move_only_heading_joins_unique_legal_parent() -> None:
    texts = ("1.e4 e5", "2.Nf3")
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    entries = [
        PromptEvidenceFragment(
            order=order,
            fragment=SourceEvidenceFragment(
                physical_page=1,
                box=box,
                text=value,
                origin="embedded_text",
                engine_name="test",
                engine_version="1",
                fragment_sha256=source_fragment_sha256(1, box, value, "embedded_text", "test", "1"),
            ),
        )
        for order, value in enumerate(texts)
    ]
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000028"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=1,
        pages=[PromptEvidencePage(physical_page=1, fragments=entries)],
        max_output_tokens=1000,
        max_prompt_chars=10000,
    )
    events = [
        {
            "id": "m1",
            "kind": "move",
            "sequence": "game",
            "source": {"page": 1, "order": 0, "quote": "e4"},
        },
        {
            "id": "m2",
            "kind": "move",
            "sequence": "game",
            "parent": "m1",
            "source": {"page": 1, "order": 0, "quote": "e5"},
        },
        {
            "id": "wrong_heading",
            "kind": "heading",
            "source": {"page": 1, "order": 1, "quote": "2.Nf3"},
        },
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps({"events": events}),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.san_candidate for node in sequence.nodes] == ["e4", "e5", "Nf3"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)


def test_forward_parent_event_in_same_chunk_compiles_full_score() -> None:
    source = "1.e4 e5 2.Nf3 Nc6"
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    fragment = SourceEvidenceFragment(
        physical_page=1,
        box=box,
        text=source,
        origin="embedded_text",
        engine_name="test",
        engine_version="1",
        fragment_sha256=source_fragment_sha256(1, box, source, "embedded_text", "test", "1"),
    )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000029"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
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
    events = [
        {
            "id": "e4",
            "kind": "move",
            "sequence": "game",
            "source": {"page": 1, "order": 0, "quote": "e4"},
        },
        {
            "id": "e5",
            "kind": "move",
            "sequence": "game",
            "parent": "e4",
            "source": {"page": 1, "order": 0, "quote": "e5"},
        },
        {
            "id": "Nc6",
            "kind": "move",
            "sequence": "game",
            "parent": "Nf3",
            "source": {"page": 1, "order": 0, "quote": "Nc6"},
        },
        {
            "id": "Nf3",
            "kind": "move",
            "sequence": "game",
            "parent": "e5",
            "source": {"page": 1, "order": 0, "quote": "Nf3"},
        },
    ]
    provider = ScriptedStructuredGenerationProvider(
        [
            StructuredGenerationResponse(
                content=json.dumps({"events": events}),
                provider="scripted",
                model="test",
                finish_reason="stop",
            )
        ]
    )
    result = asyncio.run(generate_semantic_page_chunks(context, provider))
    sequence = next(item for item in result.package.items if isinstance(item, MoveSequenceItemV1_1))
    assert [node.san_candidate for node in sequence.nodes] == ["e4", "e5", "Nf3", "Nc6"]
    assert all(node.validation_status == "valid" for node in sequence.nodes)
    assert not any(item.kind == "unresolved" for item in result.package.items)


def test_relation_owned_groups_limit_output_without_narrowing_reading_context() -> None:
    from chess_workbench.extraction.chunks import _relation_owned_windows

    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    pages = []
    for page_number in range(1, 6):
        source = " ".join(f"{number}.e4 e5" for number in range(1, 17))
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
        )
        pages.append(
            PromptEvidencePage(
                physical_page=page_number,
                fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
            )
        )
    context = CcefPromptContext(
        package_id=UUID("00000000-0000-0000-0000-000000000030"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="test-pdf",
        media_type="application/pdf",
        first_page=1,
        last_page=5,
        pages=pages,
        max_output_tokens=48000,
        max_prompt_chars=100000,
    )
    assert _relation_owned_windows(context) == [
        ["s1_0", "s2_0", "s3_0"],
        ["s4_0", "s5_0"],
    ]
