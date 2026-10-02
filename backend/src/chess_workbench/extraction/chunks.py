"""Sequential page-owned semantic chunks with verified chess continuation hints."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import chess
from pydantic import ValidationError

from .contracts import ExtractionPackageV1_1, MoveNode, MoveSequenceItemV1_1
from .draft import find_move_runs, find_numbered_move_hints, find_wrapped_moves
from .interpretation import build_semantic_request, resolve_semantic_response
from .prompting import CcefPromptContext, PromptEvidenceFragment, PromptEvidencePage
from .provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
)
from .source_compiler import _printed_move_context, compile_semantic_events
from .validation import _clean_move_token


@dataclass(frozen=True)
class SemanticChunkResult:
    first_page: int
    last_page: int
    request: StructuredGenerationRequest
    response: StructuredGenerationResponse
    event_count: int
    applied: bool | None = None
    applied_patch: str | None = None


@dataclass(frozen=True)
class ChunkedGenerationResult:
    package: ExtractionPackageV1_1
    chunks: tuple[SemanticChunkResult, ...]


def _page_context(context: CcefPromptContext, pages: list[PromptEvidencePage]) -> CcefPromptContext:
    return CcefPromptContext.model_validate(
        context.model_copy(
            update={
                "first_page": pages[0].physical_page,
                "last_page": pages[-1].physical_page,
                "pages": pages,
            }
        ).model_dump(mode="python")
    )


def _prior_moves(
    package: ExtractionPackageV1_1, events: list[dict[str, Any]]
) -> list[dict[str, str]]:
    by_node_id = {
        f"move{index + 1}": event
        for index, event in enumerate(events)
        if event.get("kind") == "move"
    }
    located_moves: list[tuple[tuple[int, int, int], dict[str, str]]] = []
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        item_nodes = {node.id: node for node in item.nodes}

        def on_mainline(node_id: str, nodes: dict[str, MoveNode] = item_nodes) -> bool:
            current = nodes[node_id]
            while True:
                if current.parent_id is None:
                    return True
                valid_siblings = [
                    candidate
                    for candidate in nodes.values()
                    if candidate.parent_id == current.parent_id
                    and candidate.validation_status == "valid"
                ]
                if (
                    not valid_siblings
                    or min(valid_siblings, key=lambda candidate: candidate.sibling_order).id
                    != current.id
                ):
                    return False
                current = nodes[current.parent_id]

        for node in item.nodes:
            event = by_node_id.get(node.id)
            if node.validation_status != "valid" or event is None:
                continue
            event_id = event.get("id")
            source = event.get("source")
            if not isinstance(event_id, str) or not isinstance(source, dict):
                continue
            page, order, start = (
                source.get("page"),
                source.get("order"),
                source.get("start"),
            )
            if (
                not isinstance(page, int)
                or not isinstance(order, int)
                or not isinstance(start, int)
            ):
                continue
            assert node.fen_after is not None
            hint = {
                "event_id": event_id,
                "san": node.san_candidate or node.move_text,
                "fen_after": node.fen_after,
                "sequence_id": item.id,
                "source_page": str(page),
                "source_order": str(order),
                "mainline": "true" if on_mainline(node.id) else "false",
            }
            if node.parent_id is not None:
                parent_event = by_node_id.get(node.parent_id)
                if parent_event is not None and isinstance(parent_event.get("id"), str):
                    hint["parent_event_id"] = parent_event["id"]
            located_moves.append(((page, order, start), hint))
    located_moves.sort(key=lambda entry: entry[0])
    return [hint for _, hint in located_moves[-16:]]


def _recover_formal_singleton(
    context: CcefPromptContext,
    events: list[dict[str, Any]],
    package: ExtractionPackageV1_1,
) -> bool:
    """A move-only numbered line misclassified as heading has one legal parent."""
    fragments = {
        (page.physical_page, entry.order): entry.fragment.text
        for page in context.pages
        for entry in page.fragments
    }
    formal = {
        (hint.page, hint.order)
        for hint in find_numbered_move_hints(context)
        if hint.quote.strip() == fragments[(hint.page, hint.order)].strip()
    }
    valid_nodes = [
        node
        for item in package.items
        if isinstance(item, MoveSequenceItemV1_1)
        for node in item.nodes
        if node.validation_status == "valid" and node.fen_after is not None
    ]
    for event in events:
        if event.get("kind") != "heading":
            continue
        source = event.get("source")
        if not isinstance(source, dict):
            continue
        page, order = source.get("page"), source.get("order")
        if not isinstance(page, int) or not isinstance(order, int) or (page, order) not in formal:
            continue
        value = fragments[(page, order)]
        number, side = _printed_move_context(value, 0, value)
        token = _clean_move_token(value)
        if number is None or side is None or token is None:
            continue
        candidates = []
        for node in valid_nodes:
            ref = node.evidence[0]
            if ref.page > page:
                continue
            board = chess.Board(node.fen_after)
            if board.fullmove_number != number or board.turn != (side == "w"):
                continue
            try:
                board.parse_san(token)
            except ValueError:
                continue
            candidates.append(node)
        if len(candidates) != 1:
            continue
        parent = candidates[0]
        parent_index = int(parent.id.removeprefix("move")) - 1
        if not (0 <= parent_index < len(events)):
            continue
        parent_event = events[parent_index]
        if not isinstance(parent_event.get("id"), str):
            continue
        event["kind"] = "move"
        event["sequence"] = parent_event.get("sequence")
        event["parent"] = parent_event["id"]
        event["mainline"] = True
        event.pop("level", None)
        return True
    return False


def _recover_one_printed_move_gap(
    context: CcefPromptContext,
    events: list[dict[str, Any]],
    package: ExtractionPackageV1_1,
) -> bool:
    """Insert one omitted printed move only when both adjacent moves prove it."""
    fragments = {
        (page.physical_page, entry.order): entry.fragment.text
        for page in context.pages
        for entry in page.fragments
    }
    candidates: list[tuple[int, int, int, int, str]] = []
    for run in find_move_runs(context):
        source = fragments[(run.page, run.order)]
        cursor = run.start
        for token in run.tokens:
            start = source.find(token, cursor, run.end)
            if start < 0:
                break
            end = start + len(token)
            candidates.append((run.page, run.order, start, end, token))
            cursor = end
    for hint in find_wrapped_moves(context):
        candidates.append((hint.page, hint.move_order, 0, len(hint.move_text), hint.move_text))
    node_by_id = {
        node.id: node
        for item in package.items
        if isinstance(item, MoveSequenceItemV1_1)
        for node in item.nodes
    }
    present_spans = [
        source
        for event in events
        if event.get("kind") == "move"
        for source in [event.get("source")]
        if isinstance(source, dict)
    ]
    for index, event in enumerate(events):
        if event.get("kind") != "move":
            continue
        node = node_by_id.get(f"move{index + 1}")
        if node is None or node.validation_status != "invalid" or node.parent_id is None:
            continue
        parent = node_by_id.get(node.parent_id)
        if parent is None or parent.validation_status != "valid" or parent.fen_after is None:
            continue
        next_source = event.get("source")
        if not isinstance(next_source, dict):
            continue
        page, order, next_start = (
            next_source.get("page"),
            next_source.get("order"),
            next_source.get("start"),
        )
        if not all(isinstance(value, int) for value in (page, order, next_start)):
            continue
        next_place = (page, order, next_start)
        parent_event_index = int(parent.id.removeprefix("move")) - 1
        if not (0 <= parent_event_index < len(events)):
            continue
        parent_event = events[parent_event_index]
        parent_source = parent_event.get("source")
        parent_event_id = parent_event.get("id")
        if not isinstance(parent_source, dict) or not isinstance(parent_event_id, str):
            continue
        parent_place = (
            parent_source.get("page"),
            parent_source.get("order"),
            parent_source.get("end"),
        )
        if not all(isinstance(value, int) for value in parent_place):
            continue
        next_token = _clean_move_token(node.move_text)
        if next_token is None:
            continue
        available = []
        for candidate in candidates:
            candidate_page, candidate_order, candidate_start, candidate_end, raw_token = candidate
            place = (candidate_page, candidate_order, candidate_start)
            if not (parent_place <= place < next_place):
                continue
            if any(
                source.get("page") == candidate_page
                and source.get("order") == candidate_order
                and source.get("start", -1) < candidate_end
                and source.get("end", -1) > candidate_start
                for source in present_spans
            ):
                continue
            if _clean_move_token(raw_token) is not None:
                available.append(candidate)
        available = sorted(set(available), key=lambda gap: gap[:3])
        single_paths = []
        for gap in available:
            gap_token = _clean_move_token(gap[4])
            assert gap_token is not None
            board = chess.Board(parent.fen_after)
            try:
                board.push_san(gap_token)
                board.parse_san(next_token)
            except ValueError:
                continue
            single_paths.append((gap,))
        chosen: tuple[tuple[int, int, int, int, str], ...]
        if len(single_paths) == 1:
            chosen = single_paths[0]
        elif single_paths:
            continue
        else:
            pair_paths = []
            for first, second in combinations(available, 2):
                if first[:3] >= second[:3]:
                    continue
                first_token = _clean_move_token(first[4])
                second_token = _clean_move_token(second[4])
                assert first_token is not None and second_token is not None
                board = chess.Board(parent.fen_after)
                try:
                    board.push_san(first_token)
                    board.push_san(second_token)
                    board.parse_san(next_token)
                except ValueError:
                    continue
                pair_paths.append((first, second))
            if len(pair_paths) != 1:
                continue
            chosen = pair_paths[0]
        preceding_id = parent_event_id
        for offset, gap in enumerate(chosen):
            gap_page, gap_order, gap_start, gap_end, _ = gap
            gap_id = f"source_gap_{len(events)}_{gap_page}_{gap_order}_{gap_start}"
            events.insert(
                index + offset,
                {
                    "id": gap_id,
                    "kind": "move",
                    "sequence": event.get("sequence"),
                    "parent": preceding_id,
                    "mainline": event.get("mainline"),
                    "source": {
                        "page": gap_page,
                        "order": gap_order,
                        "start": gap_start,
                        "end": gap_end,
                    },
                },
            )
            preceding_id = gap_id
        event["parent"] = preceding_id
        return True
    return False


def _retain_invalid_embedded_mentions_as_prose(
    events: list[dict[str, Any]], package: ExtractionPackageV1_1
) -> bool:
    """Keep an illegal token as text when it is bracketed by prose on one source line."""
    invalid_ids = {
        node.id
        for item in package.items
        if isinstance(item, MoveSequenceItemV1_1)
        for node in item.nodes
        if node.validation_status == "invalid"
    }
    for index, event in enumerate(events):
        if event.get("kind") != "move" or f"move{index + 1}" not in invalid_ids:
            continue
        event_id = event.get("id")
        if any(
            other.get("parent") == event_id or other.get("anchor") == event_id for other in events
        ):
            continue
        source = event.get("source")
        if not isinstance(source, dict):
            continue
        page, order, start, end = (
            source.get("page"),
            source.get("order"),
            source.get("start"),
            source.get("end"),
        )
        if not all(isinstance(value, int) for value in (page, order, start, end)):
            continue
        adjacent: list[dict[str, Any]] = []
        for other in events:
            part = other.get("source")
            if other.get("kind") == "prose" and isinstance(part, dict):
                adjacent.append(part)
        before = any(
            part.get("page") == page
            and part.get("order") == order
            and isinstance(part.get("end"), int)
            and part["end"] <= start
            for part in adjacent
        )
        after = any(
            part.get("page") == page
            and part.get("order") == order
            and isinstance(part.get("start"), int)
            and part["start"] >= end
            for part in adjacent
        )
        if not (before and after):
            continue
        event["kind"] = "prose"
        for field in ("sequence", "parent", "mainline", "continuation_anchor"):
            event.pop(field, None)
        return True
    return False


def _order_local_dependencies(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Let a later-emitted parent compile before its dependent source event."""
    by_id = {
        event["id"]: index for index, event in enumerate(events) if isinstance(event.get("id"), str)
    }
    ordered: list[dict[str, Any]] = []
    visiting: set[int] = set()
    completed: set[int] = set()

    def append_after_dependencies(index: int) -> None:
        if index in completed or index in visiting:
            return
        visiting.add(index)
        event = events[index]
        for field in ("parent", "anchor"):
            dependency = event.get(field)
            if isinstance(dependency, str) and dependency in by_id:
                append_after_dependencies(by_id[dependency])
        visiting.remove(index)
        completed.add(index)
        ordered.append(event)

    for index in range(len(events)):
        append_after_dependencies(index)
    return ordered


def _namespace_events(events: list[dict[str, Any]], chunk_number: int) -> list[dict[str, Any]]:
    prefix = f"c{chunk_number}_"
    current_ids = {event.get("id") for event in events if isinstance(event.get("id"), str)}
    result = []
    for event in events:
        copy = event.copy()
        if isinstance(copy.get("id"), str):
            copy["id"] = prefix + copy["id"]
        for field in ("parent", "anchor"):
            if copy.get(field) in current_ids:
                copy[field] = prefix + copy[field]
        if isinstance(copy.get("sequence"), str):
            copy["sequence"] = prefix + copy["sequence"]
        result.append(copy)
    return result


_HEADING = re.compile(
    r"^(?:chapter|part|section|game\s+\d+|第[一二三四五六七八九十百0-9]+[章节篇])\b",
    re.IGNORECASE,
)


def _owned_windows(
    context: CcefPromptContext,
    pages_per_chunk: int,
    max_chunk_chars: int,
    max_chunk_semantic_units: int,
) -> list[tuple[list[PromptEvidencePage], dict[tuple[int, int], int]]]:
    """Cut at visible section starts and paragraph budget; preserve original order."""
    groups: list[list[tuple[int, PromptEvidenceFragment]]] = []
    current: list[tuple[int, PromptEvidenceFragment]] = []
    current_pages: set[int] = set()
    chars = 0
    units = 0
    move_tokens: dict[tuple[int, int], int] = {}
    for run in find_move_runs(context):
        key = (run.page, run.order)
        move_tokens[key] = move_tokens.get(key, 0) + len(run.tokens)
    for page in context.pages:
        if current and len(current_pages) >= pages_per_chunk:
            groups.append(current)
            current, current_pages, chars, units = [], set(), 0, 0
        if not page.fragments:
            if current:
                groups.append(current)
                current, current_pages, chars, units = [], set(), 0, 0
            groups.append([])
            continue
        for entry in page.fragments:
            value = entry.fragment.text.strip()
            heading = len(value) <= 120 and bool(_HEADING.match(value))
            fragment_units = 1 + 2 * move_tokens.get((page.physical_page, entry.order), 0)
            if current and (
                heading
                or chars + len(value) > max_chunk_chars
                or units + fragment_units > max_chunk_semantic_units
            ):
                groups.append(current)
                current, current_pages, chars, units = [], set(), 0, 0
            current.append((page.physical_page, entry))
            current_pages.add(page.physical_page)
            chars += len(value)
            units += fragment_units
    if current:
        groups.append(current)
    windows: list[tuple[list[PromptEvidencePage], dict[tuple[int, int], int]]] = []
    empty_page_numbers = iter(page.physical_page for page in context.pages if not page.fragments)
    for group in groups:
        if not group:
            page_number = next(empty_page_numbers)
            windows.append(([PromptEvidencePage(physical_page=page_number, fragments=[])], {}))
            continue
        by_page: dict[int, list[PromptEvidenceFragment]] = {}
        order_map: dict[tuple[int, int], int] = {}
        for page_number, original in group:
            entries = by_page.setdefault(page_number, [])
            local_order = len(entries)
            entries.append(PromptEvidenceFragment(order=local_order, fragment=original.fragment))
            order_map[(page_number, local_order)] = original.order
        windows.append(
            (
                [
                    PromptEvidencePage(physical_page=number, fragments=entries)
                    for number, entries in by_page.items()
                ],
                order_map,
            )
        )
    return windows


async def generate_semantic_page_chunks(
    context: CcefPromptContext,
    provider: StructuredGenerationProvider,
    *,
    pages_per_chunk: int = 1,
    max_chunk_chars: int = 12_000,
    max_chunk_semantic_units: int = 136,
    sequence_initial_fens: dict[str, str | None] | None = None,
    on_response: Callable[
        [int, StructuredGenerationRequest, StructuredGenerationResponse], Awaitable[None]
    ]
    | None = None,
    external_anchors: list[dict[str, str]] | None = None,
    external_base_sha256: str | None = None,
) -> ChunkedGenerationResult:
    """Interpret adjacent owned page groups; compile all source events together.

    The prior-move hint is derived only from the currently valid CCEF candidate.
    It gives the next model stable parent event IDs and positions. Independent
    new roots remain independent, and no earlier page is regenerated.
    """
    if pages_per_chunk < 1 or max_chunk_chars < 1 or max_chunk_semantic_units < 1:
        raise ValueError("chunk limits must be positive")
    events: list[dict[str, Any]] = []
    chunks: list[SemanticChunkResult] = []
    seeds: dict[str, str | None] = {}
    bindings: dict[str, tuple[str, str]] = {}
    trusted_anchors = {
        anchor["event_id"]: anchor["fen_after"] for anchor in (external_anchors or [])
    }
    package: ExtractionPackageV1_1 | None = None
    for pages, source_orders in _owned_windows(
        context, pages_per_chunk, max_chunk_chars, max_chunk_semantic_units
    ):
        chunk_number = len(chunks) + 1
        owned = _page_context(context, pages)
        request = build_semantic_request(
            owned,
            prior_moves=(external_anchors or [])
            + ([] if package is None else _prior_moves(package, events)),
        )
        response = await provider.generate(request)
        if on_response is not None:
            await on_response(chunk_number, request, response)
        try:
            if response.finish_reason == "length":
                raise ValueError("semantic response was truncated")
            raw_events = resolve_semantic_response(owned, response.content)
        except ValueError:
            # Only the unreadable chunk is uncertain; prior legal score survives.
            raw_events = [
                {
                    "id": f"unreadable_{page.physical_page}_{entry.order}",
                    "kind": "unresolved",
                    "issue_code": "semantic_chunk_failed",
                    "source": {
                        "page": page.physical_page,
                        "order": entry.order,
                        "start": 0,
                        "end": len(entry.fragment.text),
                    },
                }
                for page in owned.pages
                for entry in page.fragments
                if entry.fragment.origin != "diagram" and entry.fragment.text.strip()
            ]
        for event in raw_events:
            source = event.get("source")
            if isinstance(source, dict):
                source_key = (source.get("page"), source.get("order"))
                if source_key in source_orders:
                    source["order"] = source_orders[source_key]
        namespaced = _namespace_events(_order_local_dependencies(raw_events), chunk_number)
        events.extend(namespaced)
        for event in namespaced:
            if (
                event.get("kind") == "move"
                and event.get("parent") is None
                and isinstance(event.get("sequence"), str)
                and isinstance(event.get("continuation_anchor"), str)
                and event["continuation_anchor"] in trusted_anchors
                and external_base_sha256 is not None
            ):
                anchor_id = event["continuation_anchor"]
                seeds[event["sequence"]] = trusted_anchors[anchor_id]
                bindings[event["sequence"]] = (external_base_sha256, anchor_id)
        for key, fen in (sequence_initial_fens or {}).items():
            seeds[f"c{chunk_number}_{key}"] = fen
        package = compile_semantic_events(
            context, events, sequence_initial_fens=seeds, sequence_bindings=bindings
        )
        while _recover_formal_singleton(context, events, package) or _recover_one_printed_move_gap(
            context, events, package
        ):
            package = compile_semantic_events(
                context, events, sequence_initial_fens=seeds, sequence_bindings=bindings
            )
        chunks.append(
            SemanticChunkResult(
                first_page=pages[0].physical_page,
                last_page=pages[-1].physical_page,
                request=request,
                response=response,
                event_count=len(namespaced),
            )
        )
    assert package is not None
    while _retain_invalid_embedded_mentions_as_prose(events, package):
        package = compile_semantic_events(
            context, events, sequence_initial_fens=seeds, sequence_bindings=bindings
        )
    return ChunkedGenerationResult(package=package, chunks=tuple(chunks))


def _relation_owned_windows(context: CcefPromptContext) -> list[list[str]]:
    """Prefer complete multi-page readings; split only the generated portion."""
    from .draft import is_board_glyph_line
    from .relations import source_tokens

    token_counts: dict[int, int] = {}
    for token in source_tokens(context):
        token_counts[token.page] = token_counts.get(token.page, 0) + 1
    groups: list[list[str]] = []
    current: list[str] = []
    chars = 0
    tokens = 0
    pages = 0
    for page in context.pages:
        page_chars = sum(len(entry.fragment.text) for entry in page.fragments)
        page_tokens = token_counts.get(page.physical_page, 0)
        # A 130-token, four-page score exhausted a 48k output budget before
        # producing complete JSON. Keep the broad reading range, but bound
        # each generated group so the model can finish its relationships.
        if current and (chars + page_chars > 35_000 or tokens + page_tokens > 100 or pages >= 4):
            groups.append(current)
            current, chars, tokens, pages = [], 0, 0, 0
        current.extend(
            f"s{page.physical_page}_{entry.order}"
            for entry in page.fragments
            if entry.fragment.origin == "diagram" or not is_board_glyph_line(entry.fragment.text)
        )
        chars += page_chars
        tokens += page_tokens
        pages += 1
    if current:
        groups.append(current)
    return groups


def _theory_owned_windows(context: CcefPromptContext, outline: Any) -> list[list[str]]:
    """Keep complete numbered branches together when output limits permit."""
    from .draft import is_board_glyph_line
    from .relations import source_tokens

    token_counts: dict[str, int] = {}
    for token in source_tokens(context):
        token_counts[token.span_ref] = token_counts.get(token.span_ref, 0) + 1
    body_refs = {
        section.source_ref for section in outline.sections if section.source_ref is not None
    }
    preview_refs = {ref for section in outline.sections for ref in section.preview_refs}
    units: list[list[tuple[str, int, int]]] = []
    current_unit: list[tuple[str, int, int]] = []
    for page in context.pages:
        for entry in page.fragments:
            if entry.fragment.origin != "diagram" and is_board_glyph_line(entry.fragment.text):
                continue
            ref = f"s{page.physical_page}_{entry.order}"
            if ref in preview_refs:
                continue
            if ref in body_refs and current_unit:
                units.append(current_unit)
                current_unit = []
            current_unit.append((ref, page.physical_page, len(entry.fragment.text)))
    if current_unit:
        units.append(current_unit)

    groups: list[list[str]] = []
    current: list[str] = []
    chars = 0
    tokens = 0
    first_page = 0
    for unit in units:
        unit_chars = sum(size for _, _, size in unit)
        unit_tokens = sum(token_counts.get(ref, 0) for ref, _, _ in unit)
        unit_last = unit[-1][1]
        if current and (
            chars + unit_chars > 35_000 or tokens + unit_tokens > 100 or unit_last - first_page >= 4
        ):
            groups.append(current)
            current, chars, tokens, first_page = [], 0, 0, 0
        # A single long section still needs bounded output. Prefer a page
        # boundary; only an unusually dense page requires a fragment split.
        for ref, physical_page, size in unit:
            if current and (
                chars + size > 35_000
                or tokens + token_counts.get(ref, 0) > 100
                or physical_page - first_page >= 4
            ):
                groups.append(current)
                current, chars, tokens, first_page = [], 0, 0, 0
            if not current:
                first_page = physical_page
            current.append(ref)
            chars += size
            tokens += token_counts.get(ref, 0)
    if current:
        groups.append(current)
    return groups


async def generate_relation_chunks(
    context: CcefPromptContext,
    provider: StructuredGenerationProvider,
    *,
    patch_provider: StructuredGenerationProvider | None = None,
    predecessor_context: CcefPromptContext | None = None,
    continuation_anchors: list[dict[str, Any]] | None = None,
    base_sha256: str | None = None,
    on_response: Callable[
        [int, StructuredGenerationRequest, StructuredGenerationResponse], Awaitable[None]
    ]
    | None = None,
) -> ChunkedGenerationResult:
    """Read the entire selected range; emit explicit relations in bounded groups."""
    from .relations import (
        QuoteRef,
        RelationPatchResponse,
        RelationState,
        _problem_for_refs,
        _resolve_quote,
        apply_relation_patches,
        apply_relations,
        build_relation_patch_request,
        build_relation_request,
        canonicalize_continuation_games,
        compile_relations,
        formal_score_note_issues,
        localize_invalid_relation_subtrees,
        parse_relation_response,
        reconcile_continuation_seed,
        recover_completed_relation_prefix,
        source_tokens,
        style_continuity_issues,
        validation_relation_issues,
    )
    from .theory_outline import build_theory_outline

    if predecessor_context is not None and predecessor_context.last_page + 1 == context.first_page:
        outline_context = CcefPromptContext.model_validate(
            context.model_copy(
                update={
                    "first_page": predecessor_context.first_page,
                    "pages": [*predecessor_context.pages, *context.pages],
                }
            ).model_dump(mode="python")
        )
    else:
        outline_context = context
    theory_outline = build_theory_outline(outline_context)
    tokens = source_tokens(context)
    token_index = {token.id: token for token in tokens}
    trusted_anchors = {
        anchor["id"]: (base_sha256, anchor["position_fen"])
        for anchor in (continuation_anchors or [])
        if base_sha256 is not None
    }
    state = RelationState(external_anchors=trusted_anchors)
    chunks: list[SemanticChunkResult] = []
    parsed_windows: list[tuple[Any, set[str]]] = []
    owned_windows = (
        _theory_owned_windows(context, theory_outline)
        if theory_outline is not None
        else _relation_owned_windows(context)
    )
    for owned in owned_windows:
        request = build_relation_request(
            context,
            tokens,
            state,
            owned,
            predecessor_context=predecessor_context,
            continuation_anchors=continuation_anchors,
            theory_outline=theory_outline,
        )
        response = await provider.generate(request)
        if on_response is not None:
            await on_response(len(chunks) + 1, request, response)
        if response.finish_reason == "length":
            parsed = recover_completed_relation_prefix(response.content)
        else:
            try:
                parsed = parse_relation_response(response.content)
            except ValueError:
                parsed = None
        if parsed is not None and continuation_anchors:
            source_request = json.loads(request.messages[1].content)
            parsed = reconcile_continuation_seed(
                parsed,
                tokens,
                continuation_anchors,
                predecessor_tokens=source_request.get("predecessor_move_tokens"),
                predecessor_spans=source_request.get("predecessor_source_spans"),
            )
            parsed = canonicalize_continuation_games(
                [*[response for response, _ in parsed_windows], parsed]
            )[-1]
        if parsed is None:
            state.problems.extend(
                _problem_for_refs(context, owned, token_index, [], len(state.problems))
            )
        else:
            apply_relations(context, parsed, tokens, set(owned), state)
            parsed_windows.append((parsed, set(owned)))
        pages = [int(ref.split("_")[0][1:]) for ref in owned]
        chunks.append(
            SemanticChunkResult(
                first_page=min(pages),
                last_page=max(pages),
                request=request,
                response=response,
                event_count=len(state.events),
            )
        )
    package = compile_relations(context, state)
    parsed_responses = [parsed for parsed, _ in parsed_windows]
    style_issues = style_continuity_issues(context, package, state, parsed_responses, tokens)
    issues = style_issues + validation_relation_issues(package, state, parsed_responses, tokens)
    preview_refs = (
        {ref for section in theory_outline.sections for ref in section.preview_refs}
        if theory_outline is not None
        else set()
    )
    issues.extend(
        formal_score_note_issues(
            context, tokens, parsed_responses, ignored_source_refs=preview_refs
        )
    )
    if issues and len(parsed_windows) == len(chunks):
        # One bounded clarification is triggered only by an observed invalid
        # relation root; ordinary successful segments cost no extra call.
        request = build_relation_patch_request(context, tokens, parsed_responses, issues[:4])
        try:
            patch_response = await (patch_provider or provider).generate(request)
        except StructuredGenerationProviderError:
            # A clarification is optional; keep the first reviewable candidate.
            patch_response = None
        if patch_response is not None and on_response is not None:
            await on_response(len(chunks) + 1, request, patch_response)
        applied = False
        applied_patch = None
        if patch_response is not None and patch_response.finish_reason != "length":
            try:
                patch = RelationPatchResponse.model_validate_json(patch_response.content)
            except (ValueError, ValidationError):
                pass
            else:
                # An invalid optional replacement must not discard independently
                # valid relationship corrections from the same paid response.
                patch_options = [patch]
                if patch.replacements or patch.promotions or patch.additions or patch.games:
                    patch_options.append(
                        patch.model_copy(
                            update={
                                "replacements": [],
                                "promotions": [],
                                "additions": [],
                                "games": [],
                            }
                        )
                    )
                if patch.demotions:
                    patch_options.append(
                        patch.model_copy(
                            update={
                                "replacements": [],
                                "promotions": [],
                                "additions": [],
                                "games": [],
                                "demotions": [],
                            }
                        )
                    )
                if len(patch.patches) > 1:
                    patch_options.extend(
                        patch.model_copy(
                            update={
                                "patches": [change],
                                "replacements": [],
                                "promotions": [],
                                "additions": [],
                                "games": [],
                                "demotions": [],
                            }
                        )
                        for change in patch.patches
                    )
                fragment_hashes = {
                    (page.physical_page, entry.order): entry.fragment.fragment_sha256
                    for page in context.pages
                    for entry in page.fragments
                }
                valid_citations = {
                    (ref.fragment_sha256, ref.start_offset, ref.end_offset)
                    for item in package.items
                    if isinstance(item, MoveSequenceItemV1_1)
                    for node in item.nodes
                    if node.validation_status == "valid"
                    for ref in node.evidence
                }
                playable_segments = {
                    segment.id
                    for response in parsed_responses
                    for segment in response.segments
                    if any(
                        (
                            fragment_hashes.get((token.page, token.order)),
                            token.start,
                            token.end,
                        )
                        in valid_citations
                        for move_ref in segment.move_refs
                        if (
                            token := (
                                token_index.get(move_ref)
                                if isinstance(move_ref, str)
                                else _resolve_quote(move_ref, context)
                                if isinstance(move_ref, QuoteRef)
                                else None
                            )
                        )
                        is not None
                    )
                }
                for accepted_patch in patch_options:
                    # A clarification cannot make a legal, source-cited score
                    # disappear merely because prose classification reduces issues.
                    if any(
                        demotion.segment_id in playable_segments
                        for demotion in accepted_patch.demotions
                    ):
                        continue
                    try:
                        revised = apply_relation_patches(
                            parsed_responses,
                            accepted_patch,
                            [owned for _, owned in parsed_windows],
                        )
                    except (ValueError, ValidationError):
                        continue
                    trial = RelationState(external_anchors=trusted_anchors)
                    for parsed, (_, owned_set) in zip(revised, parsed_windows, strict=True):
                        apply_relations(context, parsed, tokens, owned_set, trial)
                    trial_package = compile_relations(context, trial)
                    # Compare reviewable candidates. One local illegal plan may
                    # become an issue while a repaired entry restores an entire
                    # otherwise blocked, source-cited score group.
                    trial_package = localize_invalid_relation_subtrees(
                        context, trial, trial_package
                    )
                    old_invalid = sum(
                        node.validation_status != "valid"
                        for item in package.items
                        if isinstance(item, MoveSequenceItemV1_1)
                        for node in item.nodes
                    )
                    new_invalid = sum(
                        node.validation_status != "valid"
                        for item in trial_package.items
                        if isinstance(item, MoveSequenceItemV1_1)
                        for node in item.nodes
                    )
                    old_moves = sum(
                        len(item.nodes)
                        for item in package.items
                        if isinstance(item, MoveSequenceItemV1_1)
                    )
                    new_moves = sum(
                        len(item.nodes)
                        for item in trial_package.items
                        if isinstance(item, MoveSequenceItemV1_1)
                    )
                    new_style_issues = style_continuity_issues(
                        context, trial_package, trial, revised, tokens
                    )
                    original_segments = {
                        segment.id: segment
                        for original in parsed_responses
                        for segment in original.segments
                    }
                    omitted_moves = sum(
                        len(original_segments[replacement.segment_id].move_refs)
                        - sum(len(segment.move_refs) for segment in replacement.segments)
                        for replacement in accepted_patch.replacements
                    ) + sum(
                        len(original_segments[demotion.segment_id].move_refs)
                        for demotion in accepted_patch.demotions
                    )
                    if (
                        (
                            new_invalid < old_invalid
                            or len(new_style_issues) < len(style_issues)
                            or (new_invalid == old_invalid and new_moves > old_moves)
                        )
                        and new_invalid <= old_invalid
                        and len(new_style_issues) <= len(style_issues)
                        and new_moves >= old_moves - omitted_moves
                        and len(trial.problems) <= len(state.problems)
                    ):
                        package = trial_package
                        state = trial
                        style_issues = new_style_issues
                        parsed_responses = revised
                        applied = True
                        applied_patch = accepted_patch.model_dump_json()
                        break
        if patch_response is not None:
            chunks.append(
                SemanticChunkResult(
                    first_page=min(issue["page"] for issue in issues[:4]),
                    last_page=max(issue["page"] for issue in issues[:4]),
                    request=request,
                    response=patch_response,
                    event_count=len(state.events),
                    applied=applied,
                    applied_patch=applied_patch,
                )
            )
    # A legal but source-suspicious mainline relationship remains reviewable
    # if the optional model clarification did not resolve it.
    for issue in style_continuity_issues(context, package, state, parsed_responses, tokens):
        state.problems.extend(
            _problem_for_refs(
                context,
                [issue["source_ref"]],
                token_index,
                [issue["move_ref"]],
                len(state.problems),
                reason="ambiguous_relation",
                details="Numbered score style may resume an earlier line; compare source parents.",
            )
        )
    if state.problems:
        package = compile_relations(context, state)
    package = localize_invalid_relation_subtrees(context, state, package)
    return ChunkedGenerationResult(package=package, chunks=tuple(chunks))
