"""Locate missing annotation evidence using surrounding source-bound flow moves."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from .decoder import _parse_payload
from .prompting import CcefPromptContext
from .provider import StructuredGenerationResponse

LOCALIZATION_VERSION = "chess-workbench/annotation-evidence-windows/1.0"
_MOVE = re.compile(
    r"(?<![A-Za-z])(?:[O0]-[O0](?:-[O0])?|[KQRBN]?[a-h]?[1-8]?[xX]?[a-h][1-8](?:=?[QRBN])?[+#?!]*)(?![A-Za-z0-9])"
)
_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,}(?![A-Za-z0-9])")
_BOARD_ROW = re.compile(r"^[1-8]\s+[A-Za-z0-9]{8}$")


@dataclass(frozen=True)
class AnnotationWindow:
    sequence_id: str
    annotation_id: str
    flow_index: int
    previous_node_id: str | None
    next_node_id: str | None
    relation: str
    candidate_fragment_ids: tuple[str, ...]
    deterministic_fragment_ids: tuple[str, ...] = ()


def _score_only(text: str) -> bool:
    residual = _MOVE.sub("", text)
    return bool(_MOVE.search(text)) and not re.sub(r"[\d\s.?!+\-–—,:;()\[\]/]", "", residual)


def _noise(text: str) -> bool:
    value = text.strip()
    return (
        not value
        or value.isdigit()
        or bool(_BOARD_ROW.fullmatch(value))
        or value.replace(" ", "") == "abcdefgh"
    )


def locate_annotation_windows(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
) -> tuple[AnnotationWindow, ...]:
    """Return bounded candidates; auto-copy only one unambiguous prose interval.

    Source order and chess ancestry are distinct. A backwards source jump, a branch
    transition, shared boundary fragment or consecutive notes never becomes an automatic
    prose assignment. No missing identity is inferred from its spelling or numeric suffix.
    """
    payload = _parse_payload(response)
    entries = [
        (f"p{page.physical_page}-f{entry.order}", entry.fragment)
        for page in context.pages
        for entry in page.fragments
    ]
    source_indices = {(f.physical_page, f.fragment_sha256): i for i, (_, f) in enumerate(entries)}

    def indices(owner: dict[str, Any]) -> tuple[int, ...]:
        refs = owner.get("evidence")
        if not isinstance(refs, list):
            return ()
        return tuple(
            sorted(
                {
                    source_indices[(ref["page"], ref["fragment_sha256"])]
                    for ref in refs
                    if isinstance(ref, dict)
                    and type(ref.get("page")) is int
                    and isinstance(ref.get("fragment_sha256"), str)
                    and (ref["page"], ref["fragment_sha256"]) in source_indices
                }
            )
        )

    windows: list[AnnotationWindow] = []
    items = payload.get("items", [])
    reserved: set[int] = set()
    for item in items:
        if item.get("kind") in {"prose", "heading"}:
            reserved.update(indices(item))
        for annotation in item.get("annotations", []):
            reserved.update(indices(annotation))
    for item in items:
        if item.get("kind") != "move_sequence":
            continue
        nodes = {n["id"]: n for n in item["nodes"]}
        present = {a["id"] for a in item.get("annotations", [])}
        flow = item["reading_flow"]
        previous: str | None = None
        following: list[str | None] = [None] * len(flow)
        next_id: str | None = None
        for i in range(len(flow) - 1, -1, -1):
            following[i] = next_id
            if flow[i]["kind"] == "move":
                next_id = flow[i]["node_id"]
        groups: Counter[tuple[str | None, str | None]] = Counter()
        positions: list[tuple[int, str, str | None, str | None]] = []
        for i, entry in enumerate(flow):
            if entry["kind"] == "move":
                previous = entry["node_id"]
                continue
            groups[(previous, following[i])] += 1
            if entry["annotation_id"] not in present:
                positions.append((i, entry["annotation_id"], previous, following[i]))
        for i, identity, before, after in positions:
            left = indices(nodes[before]) if before in nodes else ()
            right = indices(nodes[after]) if after in nodes else ()
            candidate: set[int] = set()
            relation = "unanchored"
            ordered = bool(left and right and max(left) < min(right))
            if ordered and min(right) - max(left) <= 64:
                candidate.update(range(max(left), min(right) + 1))
                relation = "forward_source_interval"
            else:
                # At boundaries and source/branch jumps, supply only nearby evidence,
                # never all pages between distant or reversed anchors.
                for anchor in (*left, *right):
                    candidate.update(range(max(0, anchor - 3), min(len(entries), anchor + 9)))
                relation = "anchor_neighborhood" if candidate else "unanchored"
            if len(candidate) > 64:
                candidate.clear()
                relation = "evidence_window_too_large"
            deterministic: tuple[str, ...] = ()
            direct = after in nodes and nodes[after].get("parent_id") == before
            if (
                ordered
                and len(left) == len(right) == 1
                and direct
                and groups[(before, after)] == 1
                and min(right) - max(left) <= 32
                and entries[right[0]][1].physical_page - entries[left[0]][1].physical_page <= 1
                and _score_only(entries[left[0]][1].text)
                and _score_only(entries[right[0]][1].text)
            ):
                interior = [
                    j for j in range(left[0] + 1, right[0]) if not _noise(entries[j][1].text)
                ]
                if (
                    interior
                    and not (set(interior) & reserved)
                    and all(
                        _WORD.search(entries[j][1].text)
                        or re.search(r"[\u4e00-\u9fff]", entries[j][1].text)
                        for j in interior
                    )
                    and not any(_score_only(entries[j][1].text) for j in interior)
                ):
                    deterministic = tuple(entries[j][0] for j in interior)
            if after in nodes and not direct:
                relation += ":branch_transition"
            if groups[(before, after)] > 1:
                relation += ":multiple_annotations"
            windows.append(
                AnnotationWindow(
                    item["id"],
                    identity,
                    i,
                    before,
                    after,
                    relation,
                    tuple(entries[j][0] for j in sorted(candidate)),
                    deterministic,
                )
            )
    # Another missing annotation may claim the same interval. Leave that choice to
    # the bounded model instead of accepting whichever identity happens to come first.
    claims = Counter(fragment for window in windows for fragment in window.candidate_fragment_ids)
    return tuple(
        replace(window, deterministic_fragment_ids=())
        if any(claims[fragment] > 1 for fragment in window.deterministic_fragment_ids)
        else window
        for window in windows
    )
