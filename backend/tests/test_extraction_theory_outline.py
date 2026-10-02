"""A numbered theory contents list must not become a second chess line."""

import json
from datetime import UTC, datetime
from uuid import UUID

from chess_workbench.extraction.chunks import _theory_owned_windows
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
from chess_workbench.extraction.relations import (
    RelationState,
    build_relation_request,
    source_tokens,
)
from chess_workbench.extraction.theory_outline import (
    build_theory_outline,
    build_theory_outline_from_fragments,
)


def _context(lines: list[list[str]]) -> CcefPromptContext:
    pages = []
    box = NormalizedBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    for page_number, texts in enumerate(lines, start=1):
        fragments = []
        for order, text in enumerate(texts):
            fragments.append(
                PromptEvidenceFragment(
                    order=order,
                    fragment=SourceEvidenceFragment(
                        physical_page=page_number,
                        box=box,
                        text=text,
                        origin="embedded_text",
                        engine_name="test",
                        engine_version="1",
                        fragment_sha256=source_fragment_sha256(
                            page_number, box, text, "embedded_text", "test", "1"
                        ),
                    ),
                )
            )
        pages.append(PromptEvidencePage(physical_page=page_number, fragments=fragments))
    return CcefPromptContext(
        package_id=UUID(int=1),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref="fixture",
        media_type="application/pdf",
        first_page=1,
        last_page=len(lines),
        pages=pages,
        max_output_tokens=48_000,
        max_prompt_chars=100_000,
    )


def test_nested_theory_index_keeps_catalogue_heads_read_only() -> None:
    context = _context(
        [
            ["Theory", "1 e4 d5 2 exd5 Nf6"],
            ["A: 3 d4", "B: 3 Nf3", "D: 3 c4", "A is examined first.", "A: 3 d4 c6"],
            ["A1: 4 c4", "A2: 4 Nf3", "A3: 4 Bb5+", "Here are the branches.", "A1: 4 c4 e6"],
            ["A2: 4 Nf3 g6", "A3: 4 Bb5+ Bd7"],
            ["B: 3 Nf3 Bg4", "D: 3 c4 e6"],
            ["D1: 4 Nc3", "D2: 4 Nf3", "D1: 4 Nc3 Bb4"],
            ["D2: 4 Nf3 c6"],
        ]
    )
    outline = build_theory_outline(context)
    assert outline is not None
    sections = {section.label: section for section in outline.sections}
    assert sections["A1"].parent_label == "A"
    assert sections["D2"].parent_label == "D"
    assert sections["A1"].preview_refs == ("s3_0",)
    assert sections["D2"].source_ref == "s7_0"

    windows = _theory_owned_windows(context, outline)
    owned = {ref for window in windows for ref in window}
    assert "s3_0" not in owned  # contents list, not a second 4.c4
    assert "s3_4" in owned
    assert "s7_0" in owned
    request = build_relation_request(
        context, source_tokens(context), RelationState(), windows[0], theory_outline=outline
    )
    payload = json.loads(request.messages[1].content)
    assert next(entry for entry in payload["theory_sections"] if entry["label"] == "A1")[
        "preview_source_refs"
    ] == ["s3_0"]
    assert "s3_0" in payload["window"]["context_span_refs"]


def test_short_example_keeps_existing_window_mode() -> None:
    assert build_theory_outline(_context([["1 e4 e5 2 Nf3 Nc6"]])) is None


def test_catalogue_can_name_branches_whose_body_is_in_a_later_append() -> None:
    outline = build_theory_outline_from_fragments(
        [
            (1, 0, "Theory", "embedded_text"),
            (2, 0, "A: 6 f3", "embedded_text"),
            (2, 1, "B: 6 Bxc6+", "embedded_text"),
            (2, 2, "C: 6 Ne2", "embedded_text"),
            (2, 3, "D: 6 Nf3", "embedded_text"),
            (3, 0, "A: 6 f3 Bf5", "embedded_text"),
            (4, 0, "A1: 7 c4", "embedded_text"),
            (4, 1, "A2: 7 Nc3", "embedded_text"),
            (4, 2, "A3: 7 Ne2", "embedded_text"),
            (5, 0, "A1: 7 c4 e5", "embedded_text"),
        ]
    )
    assert outline is not None
    sections = {section.label: section for section in outline.sections}
    assert sections["B"].source_ref is None
    assert sections["B"].preview_refs == ("s2_1",)
    assert sections["A1"].source_ref == "s5_0"
    assert sections["A1"].preview_refs == ("s4_0",)
