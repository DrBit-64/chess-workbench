"""Focused regression tests for incremental extraction candidate binding."""

from uuid import UUID

from chess_workbench.extraction.contracts import ExtractionPackageV1_1, PageRange
from chess_workbench.extraction.incremental import (
    CCEF_CONTINUATION_CONTEXT_VERSION,
    CcefContinuationContext,
    ContinuationAnchor,
    ContinuationSequence,
)
from chess_workbench.services.pdf_legacy_incremental import _bind_continuations


def test_independent_diagram_started_score_does_not_require_continuation_binding() -> None:
    package = ExtractionPackageV1_1.model_validate(
        {
            "schema_version": "chess-content-extraction/1.1",
            "package_id": "fe51f17f-e4e8-44b4-aa62-431bd19ec83a",
            "source": {
                "source_ref": "synthetic-book",
                "media_type": "application/pdf",
                "page_range": {"start_page": 3, "end_page": 4},
            },
            "items": [
                {
                    "kind": "move_sequence",
                    "id": "new-game",
                    "title": "New diagram-started game",
                    "initial_position": {
                        "kind": "fen",
                        "fen": "8/8/8/4k3/8/8/8/4K3 w - - 0 1",
                    },
                    "nodes": [
                        {
                            "id": "new-game-1",
                            "sibling_order": 0,
                            "move_text": "Kd2",
                            "evidence": [{"page": 3}],
                        }
                    ],
                    "annotations": [],
                    "reading_flow": [{"kind": "move", "node_id": "new-game-1"}],
                    "evidence": [{"page": 3}],
                }
            ],
            "provenance": {
                "created_at": "2026-09-02T00:00:00Z",
                "adapter_name": "test-adapter",
                "adapter_version": "1.1",
            },
        }
    )
    context = CcefContinuationContext(
        schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
        base_package_id=UUID("21e3025d-c31a-44a8-a116-ebc4e37e9e18"),
        base_normalized_ccef_sha256="a" * 64,
        source_ref="synthetic-book",
        base_page_range=PageRange(start_page=1, end_page=2),
        next_page_range=PageRange(start_page=3, end_page=4),
        sequences=[
            ContinuationSequence(
                sequence_id="old-game",
                title="Previous independent game",
                anchors=[
                    ContinuationAnchor(
                        id="anchor-1",
                        sequence_id="old-game",
                        after_node_id=None,
                        position_fen="8/8/8/8/4k3/8/8/4K3 w - - 0 1",
                        path_tail=[],
                    )
                ],
            )
        ],
    )

    bound = _bind_continuations(package, context)

    assert bound.model_dump(mode="json") == package.model_dump(mode="json")


def test_v8_relation_append_continues_old_game_and_starts_new_game_mid_page() -> None:
    import asyncio
    import hashlib
    import json
    from datetime import UTC, datetime

    from chess_workbench.extraction.chunks import generate_relation_chunks
    from chess_workbench.extraction.evidence import (
        NormalizedBox,
        SourceEvidenceFragment,
        source_fragment_sha256,
    )
    from chess_workbench.extraction.incremental import (
        build_ccef_continuation_context,
        compose_incremental_ccef,
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
        RelationState,
        apply_relations,
        compile_relations,
        parse_relation_response,
        source_tokens,
    )
    from chess_workbench.services.pdf_incremental_extraction import _continuation_catalog

    def page_context(number: int, text: str) -> CcefPromptContext:
        box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
        fragment = SourceEvidenceFragment(
            physical_page=number,
            box=box,
            text=text,
            origin="embedded_text",
            engine_name="test",
            engine_version="1",
            fragment_sha256=source_fragment_sha256(number, box, text, "embedded_text", "test", "1"),
        )
        return CcefPromptContext(
            package_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            source_ref="book",
            media_type="application/pdf",
            first_page=number,
            last_page=number,
            pages=[
                PromptEvidencePage(
                    physical_page=number,
                    fragments=[PromptEvidenceFragment(order=0, fragment=fragment)],
                )
            ],
            max_output_tokens=1000,
            max_prompt_chars=100_000,
        )

    predecessor = page_context(1, "1 e4 e5 2 Nf3")
    first_refs = [token.id for token in source_tokens(predecessor)]
    first_response = parse_relation_response(
        json.dumps(
            {
                "schema_version": "chess-source-relations/1",
                "games": [
                    {"id": "old", "kind": "game", "source_refs": ["s1_0"], "seed_ref": "start"}
                ],
                "segments": [
                    {
                        "id": "opening",
                        "game_ref": "old",
                        "line_ref": "main",
                        "entry": {"kind": "root"},
                        "move_refs": first_refs,
                        "evidence_refs": ["s1_0"],
                    }
                ],
                "notes": [],
                "unresolved": [],
            }
        )
    )
    state = RelationState()
    apply_relations(predecessor, first_response, source_tokens(predecessor), {"s1_0"}, state)
    base = compile_relations(predecessor, state)
    base_hash = hashlib.sha256(
        json.dumps(
            base.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    ).hexdigest()
    continuation = build_ccef_continuation_context(
        base,
        base_normalized_ccef_sha256=base_hash,
        next_page_range=PageRange(start_page=2, end_page=2),
    )
    anchor = next(
        anchor
        for anchor in continuation.sequences[0].anchors
        if anchor.path_tail and anchor.path_tail[-1].san == "Nf3"
    )
    current = page_context(2, "2...Nc6 3 Bb5 a6 1 d4 d5")
    refs = [token.id for token in source_tokens(current)]
    assert len(refs) == 5
    response = {
        "schema_version": "chess-source-relations/1",
        "games": [
            {
                "id": "old_tail",
                "kind": "continuation",
                "source_refs": ["s2_0"],
                "seed_ref": anchor.id,
            },
            {"id": "new", "kind": "game", "source_refs": ["s2_0"], "seed_ref": "start"},
        ],
        "segments": [
            {
                "id": "tail",
                "game_ref": "old_tail",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": refs[:3],
                "evidence_refs": ["s2_0"],
            },
            {
                "id": "next",
                "game_ref": "new",
                "line_ref": "main",
                "entry": {"kind": "root"},
                "move_refs": refs[3:],
                "evidence_refs": ["s2_0"],
            },
        ],
        "notes": [],
        "unresolved": [],
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
    catalog = _continuation_catalog(base, continuation)
    generated = asyncio.run(
        generate_relation_chunks(
            current,
            provider,
            predecessor_context=predecessor,
            continuation_anchors=catalog,
            base_sha256=base_hash,
        )
    )
    prompt = json.loads(provider.calls[0].messages[-1].content)
    assert prompt["predecessor_source_spans"][0]["text"] == "1 e4 e5 2 Nf3"
    assert anchor.id in {entry["id"] for entry in prompt["prior_structure"]["continuation_anchors"]}
    aggregate = compose_incremental_ccef(
        base,
        generated.package,
        context=continuation,
        document_id=UUID("00000000-0000-0000-0000-000000000010"),
    )
    games = [item for item in aggregate.items if item.kind == "move_sequence"]
    assert [[node.san_candidate for node in game.nodes] for game in games] == [
        ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
        ["d4", "d5"],
    ]
    assert games[0].nodes[3].parent_id == games[0].nodes[2].id
