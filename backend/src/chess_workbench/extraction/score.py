"""Non-blocking source-coverage report for a compiled CCEF candidate."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ExtractionPackageV1_1, MoveSequenceItemV1_1
from .draft import is_board_glyph_line
from .prompting import CcefPromptContext


@dataclass(frozen=True)
class CandidateCoverage:
    total_fragments: int
    represented_fragments: int
    unrepresented_fragments: tuple[tuple[int, int], ...]
    invalid_moves: int
    unresolved_items: int


def score_candidate(
    context: CcefPromptContext, package: ExtractionPackageV1_1
) -> CandidateCoverage:
    """Report missing source fragments and unresolved chess without gating review."""
    represented = set()
    invalid_moves = 0
    for item in package.items:
        for ref in item.evidence:
            if ref.fragment_sha256:
                represented.add(ref.fragment_sha256)
        if isinstance(item, MoveSequenceItemV1_1):
            invalid_moves += sum(node.validation_status != "valid" for node in item.nodes)
            for node in item.nodes:
                represented.update(
                    ref.fragment_sha256 for ref in node.evidence if ref.fragment_sha256
                )
            for annotation in item.annotations:
                represented.update(
                    ref.fragment_sha256 for ref in annotation.evidence if ref.fragment_sha256
                )
    gaps = tuple(
        (page.physical_page, entry.order)
        for page in context.pages
        for entry in page.fragments
        if entry.fragment.fragment_sha256 not in represented
        and not is_board_glyph_line(entry.fragment.text)
    )
    total = sum(
        not is_board_glyph_line(entry.fragment.text)
        for page in context.pages
        for entry in page.fragments
    )
    return CandidateCoverage(
        total_fragments=total,
        represented_fragments=total - len(gaps),
        unrepresented_fragments=gaps,
        invalid_moves=invalid_moves,
        unresolved_items=sum(item.kind == "unresolved" for item in package.items),
    )
