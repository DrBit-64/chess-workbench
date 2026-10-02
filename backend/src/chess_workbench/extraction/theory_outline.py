"""Source-linked outline hints for long, numbered theory sections.

The outline describes where the author discusses a branch. It never supplies
chess parent edges: the relation model must still cite those explicitly.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .prompting import CcefPromptContext

# A chapter may use A, A1, D41, or AA2. A printed move after the marker keeps
# ordinary prose labels out of this small structural index.
_LABEL = re.compile(r"^\s*([A-Z]{1,2}\d{0,3})\s*[:.)]\s*([1-9]\d{0,2}(?:\s*\.{1,3})?\s*\S.*)$")


@dataclass(frozen=True)
class TheoryHeading:
    label: str
    source_ref: str
    page: int
    order: int
    text: str


@dataclass(frozen=True)
class TheorySection:
    label: str
    parent_label: str | None
    source_ref: str | None
    page: int
    order: int
    preview_refs: tuple[str, ...]
    opening_text: str

    def as_input(self) -> dict[str, object]:
        return {
            "label": self.label,
            "parent_label": self.parent_label,
            "body_source_ref": self.source_ref,
            "preview_source_refs": list(self.preview_refs),
            "page": self.page,
            "opening_text": self.opening_text,
        }


@dataclass(frozen=True)
class TheoryOutline:
    sections: tuple[TheorySection, ...]
    headings: tuple[TheoryHeading, ...]
    first_label_ref: str

    def as_input(self) -> list[dict[str, object]]:
        return [section.as_input() for section in self.sections]


def build_theory_outline(context: CcefPromptContext) -> TheoryOutline | None:
    return build_theory_outline_from_fragments(
        (page.physical_page, entry.order, entry.fragment.text, entry.fragment.origin)
        for page in context.pages
        for entry in page.fragments
    )


def build_theory_outline_from_fragments(
    fragments: Iterable[tuple[int, int, str, str]],
) -> TheoryOutline | None:
    """Index recurring numbered branch headings in source order.

    Repeated labels normally mean a contents list followed by a body heading.
    The final occurrence is the body start. This is a prompt hint, never an
    authority for assigning a move to a position.
    """
    headings: list[TheoryHeading] = []
    pages: set[int] = set()
    heading_runs: list[list[TheoryHeading]] = []
    current_run: list[TheoryHeading] = []
    for page, order, text, origin in fragments:
        pages.add(page)
        match = _LABEL.match(text.strip()) if origin != "diagram" else None
        if match is None:
            if current_run:
                heading_runs.append(current_run)
                current_run = []
            continue
        heading = TheoryHeading(
            label=match.group(1),
            source_ref=f"s{page}_{order}",
            page=page,
            order=order,
            text=match.group(2).strip(),
        )
        if current_run and (current_run[-1].page != page or current_run[-1].order + 1 != order):
            heading_runs.append(current_run)
            current_run = []
        current_run.append(heading)
        headings.append(heading)
    if current_run:
        heading_runs.append(current_run)
    if not headings:
        return None
    labels = set(heading.label for heading in headings)
    # One or two numbered score labels occur in ordinary examples; require a
    # real nested outline before changing the established game workflow.
    nested = sum(
        any(label.startswith(parent) and label != parent for parent in labels) for label in labels
    )
    if len(labels) < 7 or nested < 2 or len(pages) < 5:
        return None
    catalogue_refs = {
        heading.source_ref for run in heading_runs if len(run) >= 3 for heading in run
    }
    grouped: dict[str, list[TheoryHeading]] = {}
    for heading in headings:
        grouped.setdefault(heading.label, []).append(heading)
    sections: list[TheorySection] = []
    for label, occurrences in grouped.items():
        body = (
            occurrences[-1]
            if len(occurrences) > 1
            else next(
                (heading for heading in occurrences if heading.source_ref not in catalogue_refs),
                None,
            )
        )
        heading = body or occurrences[0]
        parent = max(
            (
                label
                for label in labels
                if heading.label != label and heading.label.startswith(label)
            ),
            key=len,
            default=None,
        )
        previews = tuple(
            occurrence.source_ref for occurrence in occurrences if occurrence is not body
        )
        sections.append(
            TheorySection(
                label=heading.label,
                parent_label=parent,
                source_ref=body.source_ref if body else None,
                page=heading.page,
                order=heading.order,
                preview_refs=previews,
                opening_text=heading.text,
            )
        )
    sections.sort(key=lambda section: (section.page, section.order))
    return TheoryOutline(
        sections=tuple(sections), headings=tuple(headings), first_label_ref=headings[0].source_ref
    )
