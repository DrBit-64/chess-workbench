"""Deterministic consolidation of model-produced CCEF move sequences.

This is a consumer-side transformation defined by ADR 0015. It never repairs
chess by guessing a different parent. It keeps only locally validated paths in
playable trees, merges duplicate UCI paths inside the same heading scope, and
leaves source prose untouched.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import chess

from .contracts import (
    AnnotationFlowRef,
    Diagnostic,
    EvidenceRef,
    ExtractionPackage,
    ExtractionPackageV1_1,
    ExtractionWarning,
    HeadingItem,
    MoveFlowRef,
    MoveNode,
    MoveNodeAnchor,
    MoveNodeAnnotationAnchor,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PositionAnchor,
    PositionAnnotationAnchor,
    ProseItem,
    SequenceAnnotation,
    SequenceFlowEntry,
    UnresolvedItem,
)
from .prompting import PromptEvidencePage
from .validation import normalize_chess_moves, normalize_chess_moves_v1_1

_VALIDATOR_WARNING_PREFIX = "ccef_chess_"
_ANNOTATION_SUFFIX = re.compile(r"\s*(!!|\?\?|!\?|\?!|!|\?)$")
_ANNOTATION_NAGS = {"!": 1, "?": 2, "!!": 3, "??": 4, "!?": 5, "?!": 6}
_MOVE_NUMBER = re.compile(r"^(\d+)(\.{1,3})?$")
_ATTACHED_MOVE_NUMBER = re.compile(r"^(\d+)(\.{1,3})(.+)$")
_SAN_TOKEN = re.compile(
    r"^(?:O-O(?:-O)?|0-0(?:-0)?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?)[!?]{0,2}$"
)
_UNRESOLVED_DETAILS = (
    "Move fragment could not be attached to a uniquely legal source line during deterministic "
    "consolidation."
)
_ANNOTATION_ANCHOR_UNRESOLVED_CODE = "ccef_annotation_anchor_unresolved"
_ANNOTATION_ANCHOR_UNRESOLVED_MESSAGE = (
    "The source annotation anchor was removed with an unplayable move fragment."
)


def _json_key(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _model_key(value: Any) -> str:
    return _json_key(value.model_dump(mode="json"))


def _stable_union(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = _model_key(value)
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(value))
    return result


def _annotation_nags(move_text: str) -> list[int]:
    nags: list[int] = []
    remaining = move_text
    while match := _ANNOTATION_SUFFIX.search(remaining):
        nags.append(_ANNOTATION_NAGS[match.group(1)])
        remaining = remaining[: match.start()]
    return nags


@dataclass
class _TrieNode:
    uci: str
    parent: _TrieNode | None
    path: tuple[str, ...]
    sources: list[MoveNode] = field(default_factory=list)
    children: dict[str, _TrieNode] = field(default_factory=dict)
    output_id: str | None = None


@dataclass
class _SequenceGroup:
    sequences: list[MoveSequenceItem | MoveSequenceItemV1_1] = field(default_factory=list)
    roots: dict[str, _TrieNode] = field(default_factory=dict)
    creation_order: list[_TrieNode] = field(default_factory=list)


def _group_key(
    heading_scope: str | None, sequence: MoveSequenceItem | MoveSequenceItemV1_1
) -> tuple[str | None, str, str | None, str]:
    return (
        heading_scope,
        _model_key(sequence.initial_position),
        sequence.title,
        _json_key(sequence.extensions),
    )


def _collect_groups(
    package: ExtractionPackage | ExtractionPackageV1_1,
) -> tuple[
    dict[tuple[str | None, str, str | None, str], _SequenceGroup],
    dict[str, tuple[str | None, str, str | None, str]],
]:
    groups: dict[tuple[str | None, str, str | None, str], _SequenceGroup] = {}
    sequence_keys: dict[str, tuple[str | None, str, str | None, str]] = {}
    heading_scope: str | None = None
    for item in package.items:
        if isinstance(item, HeadingItem):
            heading_scope = item.id
        elif isinstance(item, (MoveSequenceItem, MoveSequenceItemV1_1)):
            key = _group_key(heading_scope, item)
            groups.setdefault(key, _SequenceGroup()).sequences.append(item)
            sequence_keys[item.id] = key
    return groups, sequence_keys


def _insert_valid_paths(
    group: _SequenceGroup,
    node_refs: dict[tuple[str, str], _TrieNode | None],
    omitted: dict[str, list[MoveNode]],
) -> None:
    for sequence in group.sequences:
        paths: dict[str, tuple[str, ...]] = {}
        for node in sequence.nodes:
            parent_path = () if node.parent_id is None else paths.get(node.parent_id)
            if (
                node.validation_status != "valid"
                or node.uci_candidate is None
                or parent_path is None
            ):
                node_refs[(sequence.id, node.id)] = None
                omitted.setdefault(sequence.id, []).append(node)
                continue
            path = parent_path + (node.uci_candidate,)
            paths[node.id] = path
            children = group.roots
            parent: _TrieNode | None = None
            for uci in path:
                trie_node = children.get(uci)
                if trie_node is None:
                    parent_path_value = parent.path if parent is not None else ()
                    trie_node = _TrieNode(
                        uci=uci,
                        parent=parent,
                        path=parent_path_value + (uci,),
                    )
                    children[uci] = trie_node
                    group.creation_order.append(trie_node)
                parent = trie_node
                children = trie_node.children
            if parent is None:
                raise AssertionError("a valid move path cannot be empty")
            parent.sources.append(node)
            node_refs[(sequence.id, node.id)] = parent


def _build_node(trie_node: _TrieNode, root_orders: dict[str, int]) -> MoveNode:
    first = trie_node.sources[0]
    if first.san_candidate is None or first.fen_before is None or first.fen_after is None:
        raise AssertionError("consolidation received a non-normalized valid node")
    board = chess.Board(first.fen_before, chess960=False)
    if trie_node.parent is None:
        sibling_order = root_orders[trie_node.uci]
    else:
        siblings = trie_node.parent.children
        sibling_order = list(siblings).index(trie_node.uci)
    evidence = _stable_union([ref for node in trie_node.sources for ref in node.evidence])
    warnings = _stable_union(
        [
            warning
            for node in trie_node.sources
            for warning in node.warnings
            if not warning.code.startswith(_VALIDATOR_WARNING_PREFIX)
        ]
    )
    nags = sorted(
        {
            nag
            for node in trie_node.sources
            for nag in [*node.nags, *_annotation_nags(node.move_text)]
        }
    )
    confidence_values = [
        node.confidence for node in trie_node.sources if node.confidence is not None
    ]
    return MoveNode(
        id=trie_node.output_id or "unassigned",
        parent_id=trie_node.parent.output_id if trie_node.parent is not None else None,
        sibling_order=sibling_order,
        move_text=first.san_candidate,
        move_number=board.fullmove_number,
        side_to_move="w" if board.turn else "b",
        san_candidate=first.san_candidate,
        uci_candidate=first.uci_candidate,
        nags=nags,
        validation_status="valid",
        fen_before=first.fen_before,
        fen_after=first.fen_after,
        evidence=evidence,
        confidence=max(confidence_values) if confidence_values else None,
        warnings=warnings,
        extensions=copy.deepcopy(first.extensions),
    )


def _build_merged_sequence(group: _SequenceGroup) -> MoveSequenceItem | None:
    if not group.creation_order:
        return None
    for index, trie_node in enumerate(group.creation_order, start=1):
        trie_node.output_id = f"n{index}"
    root_orders = {uci: order for order, uci in enumerate(group.roots)}
    nodes: list[MoveNode] = []
    for trie_node in group.creation_order:
        nodes.append(_build_node(trie_node, root_orders))
    first = group.sequences[0]
    evidence = _stable_union([ref for sequence in group.sequences for ref in sequence.evidence])
    warnings = _stable_union(
        [warning for sequence in group.sequences for warning in sequence.warnings]
    )
    confidences = [
        sequence.confidence for sequence in group.sequences if sequence.confidence is not None
    ]
    return MoveSequenceItem(
        id=first.id,
        evidence=evidence,
        confidence=max(confidences) if confidences else None,
        warnings=warnings,
        extensions=copy.deepcopy(first.extensions),
        kind="move_sequence",
        title=first.title,
        initial_position=copy.deepcopy(first.initial_position),
        nodes=nodes,
    )


@dataclass(frozen=True)
class _FormalSequence:
    sequence: MoveSequenceItem
    path_ids: dict[tuple[str, ...], str]


def _notation_tokens(text: str) -> list[str] | None:
    tokens: list[str] = []
    for token in text.split():
        attached = _ATTACHED_MOVE_NUMBER.fullmatch(token)
        if attached is None:
            tokens.append(token)
        else:
            tokens.extend((f"{attached.group(1)}{attached.group(2)}", attached.group(3)))
    if not tokens or _MOVE_NUMBER.fullmatch(tokens[0]) is None:
        return None
    saw_move = False
    for token in tokens:
        if token == "..." or _MOVE_NUMBER.fullmatch(token):
            continue
        if _SAN_TOKEN.fullmatch(token) is None:
            return None
        saw_move = True
    return tokens if saw_move else None


def _evidence_ref_for_fragment(page: PromptEvidencePage, order: int) -> EvidenceRef:
    fragment = page.fragments[order].fragment
    return EvidenceRef(
        page=fragment.physical_page,
        bbox=[fragment.box.x0, fragment.box.y0, fragment.box.x1, fragment.box.y1],
        fragment_sha256=fragment.fragment_sha256,
    )


def _parse_formal_fragment(
    board: chess.Board,
    tokens: list[str],
    parent_id: str | None,
    next_index: int,
    evidence: EvidenceRef,
) -> tuple[chess.Board, list[MoveNode]] | None:
    candidate_board = board.copy()
    candidate_parent = parent_id
    nodes: list[MoveNode] = []
    declared_number: int | None = None
    declared_side: str | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        number_match = _MOVE_NUMBER.fullmatch(token)
        if number_match is not None:
            declared_number = int(number_match.group(1))
            dots = number_match.group(2)
            declared_side = "b" if dots == "..." else "w"
            if index + 1 < len(tokens) and tokens[index + 1] == "...":
                declared_side = "b"
                index += 1
            index += 1
            continue
        if token == "...":
            return None
        expected_side: Literal["w", "b"] = "w" if candidate_board.turn else "b"
        if declared_number is not None and declared_number != candidate_board.fullmove_number:
            return None
        if declared_side is not None and declared_side != expected_side:
            return None
        annotation_match = _ANNOTATION_SUFFIX.search(token)
        parse_token = token[: annotation_match.start()] if annotation_match is not None else token
        try:
            move = candidate_board.parse_san(parse_token)
        except ValueError:
            return None
        san = candidate_board.san(move)
        node_id = f"n{next_index + len(nodes)}"
        nodes.append(
            MoveNode(
                id=node_id,
                parent_id=candidate_parent,
                sibling_order=0,
                move_text=san,
                move_number=candidate_board.fullmove_number,
                side_to_move=expected_side,
                nags=_annotation_nags(token),
                evidence=[copy.deepcopy(evidence)],
            )
        )
        candidate_board.push(move)
        candidate_parent = node_id
        declared_number = None
        declared_side = None
        index += 1
    return candidate_board, nodes


def _extract_formal_sequences(
    package: ExtractionPackage,
    pages: list[PromptEvidencePage],
    groups: dict[tuple[str | None, str, str | None, str], _SequenceGroup],
) -> dict[tuple[str | None, str, str | None, str], _FormalSequence]:
    heading_by_fragment = {
        ref.fragment_sha256: item.id
        for item in package.items
        if isinstance(item, HeadingItem)
        for ref in item.evidence
        if ref.fragment_sha256 is not None
    }
    keys_by_scope: dict[str | None, list[tuple[str | None, str, str | None, str]]] = {}
    for key, group in groups.items():
        if group.sequences:
            keys_by_scope.setdefault(key[0], []).append(key)

    state: dict[
        tuple[str | None, str, str | None, str],
        tuple[chess.Board, list[MoveNode], list[EvidenceRef]],
    ] = {}
    heading_scope: str | None = None
    for page in pages:
        for order, entry in enumerate(page.fragments):
            fragment = entry.fragment
            heading_scope = heading_by_fragment.get(fragment.fragment_sha256, heading_scope)
            tokens = _notation_tokens(fragment.text)
            scope_keys = keys_by_scope.get(heading_scope, [])
            if tokens is None or len(scope_keys) != 1:
                continue
            key = scope_keys[0]
            current = state.get(key)
            if current is None:
                initial = groups[key].sequences[0].initial_position
                try:
                    initial_board = (
                        chess.Board()
                        if initial.kind == "startpos"
                        else chess.Board(initial.fen, chess960=False)
                    )
                except ValueError:
                    continue
                if not initial_board.is_valid():
                    continue
                current_board = initial_board
                current_nodes: list[MoveNode] = []
                sequence_evidence: list[EvidenceRef] = []
            else:
                current_board, current_nodes, sequence_evidence = current
            evidence = _evidence_ref_for_fragment(page, order)
            parsed = _parse_formal_fragment(
                current_board,
                tokens,
                current_nodes[-1].id if current_nodes else None,
                len(current_nodes) + 1,
                evidence,
            )
            if parsed is None:
                continue
            next_board, next_nodes = parsed
            state[key] = (
                next_board,
                [*current_nodes, *next_nodes],
                _stable_union([*sequence_evidence, evidence]),
            )

    result: dict[tuple[str | None, str, str | None, str], _FormalSequence] = {}
    for key, (_, nodes, sequence_refs) in state.items():
        if not nodes:
            continue
        first = groups[key].sequences[0]
        sequence = MoveSequenceItem(
            id=first.id,
            evidence=sequence_refs,
            confidence=first.confidence,
            warnings=copy.deepcopy(first.warnings),
            extensions=copy.deepcopy(first.extensions),
            kind="move_sequence",
            title=first.title,
            initial_position=copy.deepcopy(first.initial_position),
            nodes=nodes,
        )
        initial = first.initial_position
        board = (
            chess.Board()
            if initial.kind == "startpos"
            else chess.Board(initial.fen, chess960=False)
        )
        path: tuple[str, ...] = ()
        path_ids: dict[tuple[str, ...], str] = {}
        for node in nodes:
            move = board.parse_san(node.move_text)
            path += (move.uci(),)
            path_ids[path] = node.id
            board.push(move)
        result[key] = _FormalSequence(sequence=sequence, path_ids=path_ids)
    return result


def _coverage_key(ref: EvidenceRef) -> str | None:
    return ref.fragment_sha256


def _next_fallback_id(existing: set[str], counter: int, *, kind: str) -> tuple[str, int]:
    while True:
        candidate = f"consolidation_{kind}_{counter}"
        counter += 1
        if candidate not in existing:
            existing.add(candidate)
            return candidate, counter


def _unresolved_fallbacks(
    package: ExtractionPackage | ExtractionPackageV1_1,
    omitted: dict[str, list[MoveNode]],
    additional_covered: set[str] | None = None,
    evidence_text: dict[str, str] | None = None,
) -> dict[str, ProseItem | UnresolvedItem]:
    covered = {
        ref.fragment_sha256
        for item in package.items
        if not isinstance(item, (MoveSequenceItem, MoveSequenceItemV1_1))
        for ref in item.evidence
        if ref.fragment_sha256 is not None
    }
    covered.update(additional_covered or set())
    existing_ids = {item.id for item in package.items}
    counter = 1
    result: dict[str, ProseItem | UnresolvedItem] = {}
    seen: set[str] = set()
    for sequence_id, nodes in omitted.items():
        evidence = _stable_union(
            [
                ref
                for node in nodes
                for ref in node.evidence
                if (key := _coverage_key(ref)) is None or key not in covered
            ]
        )
        if not evidence:
            continue
        source_text = [
            evidence_text[ref.fragment_sha256]
            for ref in evidence
            if evidence_text is not None
            and ref.fragment_sha256 is not None
            and ref.fragment_sha256 in evidence_text
        ]
        raw_text = " ".join(dict.fromkeys(source_text)) or " ".join(
            node.move_text for node in nodes if any(ref in evidence for ref in node.evidence)
        )
        signature = _json_key(
            {"raw_text": raw_text, "evidence": [ref.model_dump(mode="json") for ref in evidence]}
        )
        if signature in seen:
            continue
        seen.add(signature)
        source_is_prose = bool(source_text) and any(
            _notation_tokens(text) is None for text in source_text
        )
        item_id, counter = _next_fallback_id(
            existing_ids,
            counter,
            kind="prose" if source_is_prose else "unresolved",
        )
        if source_is_prose:
            result[sequence_id] = ProseItem(
                id=item_id,
                evidence=evidence,
                kind="prose",
                text=raw_text,
            )
        else:
            result[sequence_id] = UnresolvedItem(
                id=item_id,
                evidence=evidence,
                kind="unresolved",
                unresolved_type="text",
                reason_code="move_tree_unresolved",
                raw_text=raw_text,
                details=_UNRESOLVED_DETAILS,
            )
    return result


def _remap_references(
    items: list[Any],
    diagnostics: list[Diagnostic],
    sequence_ids: dict[str, str],
    source_sequence_ids: set[str],
    node_refs: dict[tuple[str, str], _TrieNode | None],
) -> tuple[list[Any], list[Diagnostic]]:
    for item in items:
        if not isinstance(item, ProseItem) or not isinstance(item.anchor, MoveNodeAnchor):
            continue
        old = (item.anchor.sequence_id, item.anchor.node_id)
        mapped = node_refs.get(old)
        if mapped is not None and mapped.output_id is not None:
            item.anchor = MoveNodeAnchor(
                kind="move_node",
                sequence_id=sequence_ids[item.anchor.sequence_id],
                node_id=mapped.output_id,
            )
        else:
            item.anchor = None
            item.warnings.append(
                ExtractionWarning(
                    code="ccef_anchor_unresolved",
                    message="The source anchor was removed with an unplayable move fragment.",
                    evidence=copy.deepcopy(item.evidence),
                )
            )

    remapped_diagnostics = copy.deepcopy(diagnostics)
    for diagnostic in remapped_diagnostics:
        if diagnostic.item_id not in source_sequence_ids:
            continue
        old_sequence_id = diagnostic.item_id
        if old_sequence_id not in sequence_ids:
            diagnostic.item_id = None
            diagnostic.node_id = None
            continue
        diagnostic.item_id = sequence_ids[old_sequence_id]
        if diagnostic.node_id is None:
            continue
        mapped = node_refs.get((old_sequence_id, diagnostic.node_id))
        diagnostic.node_id = mapped.output_id if mapped is not None else None
    return items, remapped_diagnostics


def _sort_items_by_evidence(
    items: list[Any], evidence_pages: list[PromptEvidencePage]
) -> list[Any]:
    evidence_order = {
        entry.fragment.fragment_sha256: position
        for position, entry in enumerate(
            entry for page in evidence_pages for entry in page.fragments
        )
    }

    def sort_key(indexed_item: tuple[int, Any]) -> tuple[int, int]:
        original_index, item = indexed_item
        positions = [
            evidence_order[ref.fragment_sha256]
            for ref in item.evidence
            if ref.fragment_sha256 in evidence_order
        ]
        return (
            min(positions) if positions else len(evidence_order) + original_index,
            original_index,
        )

    return [item for _, item in sorted(enumerate(items), key=sort_key)]


def consolidate_move_sequences(
    package: ExtractionPackage,
    evidence_pages: list[PromptEvidencePage] | None = None,
) -> ExtractionPackage:
    """Return a fresh CCEF package with deterministic playable move trees.

    The input may contain unvalidated or previously normalized nodes. It is
    never mutated. All output move nodes are revalidated after consolidation.
    """
    if type(package) is not ExtractionPackage:
        raise TypeError("package must be ExtractionPackage")
    if evidence_pages is not None and not all(
        type(page) is PromptEvidencePage for page in evidence_pages
    ):
        raise TypeError("evidence_pages must contain PromptEvidencePage values")
    validated = normalize_chess_moves(package)
    groups, sequence_keys = _collect_groups(validated)
    formal_sequences = (
        _extract_formal_sequences(validated, evidence_pages, groups)
        if evidence_pages is not None
        else {}
    )
    node_refs: dict[tuple[str, str], _TrieNode | None] = {}
    omitted: dict[str, list[MoveNode]] = {}
    merged_by_key: dict[tuple[str | None, str, str | None, str], MoveSequenceItem | None] = {}
    sequence_ids: dict[str, str] = {}
    for key, group in groups.items():
        _insert_valid_paths(group, node_refs, omitted)
        merged = _build_merged_sequence(group)
        formal = formal_sequences.get(key)
        if formal is not None:
            merged = formal.sequence
            for trie_node in group.creation_order:
                trie_node.output_id = formal.path_ids.get(trie_node.path)
            for sequence in group.sequences:
                for node in sequence.nodes:
                    mapped_trie = node_refs.get((sequence.id, node.id))
                    if mapped_trie is not None and mapped_trie.path not in formal.path_ids:
                        omitted.setdefault(sequence.id, []).append(node)
        merged_by_key[key] = merged
        if merged is not None:
            sequence_ids.update({sequence.id: merged.id for sequence in group.sequences})

    formal_covered = {
        ref.fragment_sha256
        for formal in formal_sequences.values()
        for node in formal.sequence.nodes
        for ref in node.evidence
        if ref.fragment_sha256 is not None
    }
    evidence_text = {
        entry.fragment.fragment_sha256: entry.fragment.text
        for page in evidence_pages or []
        for entry in page.fragments
    }
    fallbacks = _unresolved_fallbacks(
        validated,
        omitted,
        formal_covered,
        evidence_text,
    )
    emitted: set[tuple[str | None, str, str | None, str]] = set()
    output_items: list[Any] = []
    for item in validated.items:
        if not isinstance(item, MoveSequenceItem):
            output_items.append(copy.deepcopy(item))
            continue
        key = sequence_keys[item.id]
        if key not in emitted:
            emitted.add(key)
            merged = merged_by_key[key]
            if merged is not None:
                output_items.append(merged)
        fallback = fallbacks.get(item.id)
        if fallback is not None:
            output_items.append(fallback)

    output_items, diagnostics = _remap_references(
        output_items,
        validated.diagnostics,
        sequence_ids,
        set(sequence_keys),
        node_refs,
    )
    if evidence_pages is not None:
        output_items = _sort_items_by_evidence(output_items, evidence_pages)
    result_data = validated.model_dump(mode="json")
    result_data["items"] = [item.model_dump(mode="json") for item in output_items]
    result_data["diagnostics"] = [item.model_dump(mode="json") for item in diagnostics]
    consolidated = ExtractionPackage.model_validate(result_data)
    return normalize_chess_moves(consolidated)


# ---------------------------------------------------------------------------
# CCEF 1.1 annotated-score consolidation (ADR 0017)
# ---------------------------------------------------------------------------


def _build_annotations_and_flow(
    group: _SequenceGroup,
    node_refs: dict[tuple[str, str], _TrieNode | None],
) -> tuple[list[SequenceAnnotation], list[SequenceFlowEntry]]:
    """Rebuild annotations and exact-cover flow from the source reading flows.

    Annotations are deep-copied exactly once each and never deduplicated by
    text, anchor or evidence. Move entries resolve through the merged trie:
    duplicate-path occurrences and omitted nodes are skipped, so the move
    projection equals the merged node ids in array order.
    """
    merged_node_ids = {
        trie_node.output_id for trie_node in group.creation_order if trie_node.output_id is not None
    }
    annotations: list[SequenceAnnotation] = []
    flow: list[SequenceFlowEntry] = []
    emitted_moves: set[str] = set()
    retained_annotation_ids: set[str] = set()
    next_annotation_counter = 1

    def free_annotation_id() -> str:
        nonlocal next_annotation_counter
        while True:
            candidate = f"a{next_annotation_counter}"
            next_annotation_counter += 1
            if candidate not in merged_node_ids and candidate not in retained_annotation_ids:
                return candidate

    for sequence in group.sequences:
        if not isinstance(sequence, MoveSequenceItemV1_1):
            continue
        for entry in sequence.reading_flow:
            if entry.kind == "move":
                trie_node = node_refs.get((sequence.id, entry.node_id))
                if trie_node is None or trie_node.output_id is None:
                    continue
                if trie_node.output_id in emitted_moves:
                    continue
                emitted_moves.add(trie_node.output_id)
                flow.append(MoveFlowRef(kind="move", node_id=trie_node.output_id))
                continue
            source_annotation = next(
                (
                    annotation
                    for annotation in sequence.annotations
                    if annotation.id == entry.annotation_id
                ),
                None,
            )
            if source_annotation is None:
                continue
            annotation = copy.deepcopy(source_annotation)
            if annotation.id in merged_node_ids or annotation.id in retained_annotation_ids:
                annotation.id = free_annotation_id()
            if isinstance(annotation.anchor, MoveNodeAnnotationAnchor):
                trie_node = node_refs.get((sequence.id, annotation.anchor.node_id))
                if trie_node is not None and trie_node.output_id is not None:
                    annotation.anchor = MoveNodeAnnotationAnchor(
                        kind="move_node",
                        node_id=trie_node.output_id,
                        relation=annotation.anchor.relation,
                    )
                else:
                    annotation.anchor = None
                    if not any(
                        warning.code == _ANNOTATION_ANCHOR_UNRESOLVED_CODE
                        for warning in annotation.warnings
                    ):
                        annotation.warnings.append(
                            ExtractionWarning(
                                code=_ANNOTATION_ANCHOR_UNRESOLVED_CODE,
                                message=_ANNOTATION_ANCHOR_UNRESOLVED_MESSAGE,
                                evidence=copy.deepcopy(annotation.evidence),
                            )
                        )
            retained_annotation_ids.add(annotation.id)
            annotations.append(annotation)
            flow.append(AnnotationFlowRef(kind="annotation", annotation_id=annotation.id))
    return annotations, flow


def _annotation_covered_fragments(
    groups: dict[tuple[str | None, str, str | None, str], _SequenceGroup],
) -> set[str]:
    return {
        ref.fragment_sha256
        for group in groups.values()
        for sequence in group.sequences
        if isinstance(sequence, MoveSequenceItemV1_1)
        for annotation in sequence.annotations
        for ref in annotation.evidence
        if ref.fragment_sha256 is not None
    }


def _annotation_prose_fallbacks(
    groups: dict[tuple[str | None, str, str | None, str], _SequenceGroup],
    existing_ids: set[str],
) -> dict[str, list[ProseItem]]:
    """Convert all-unplayable-group annotations into deterministic prose items."""
    result: dict[str, list[ProseItem]] = {}
    counter = 1
    for group in groups.values():
        for sequence in group.sequences:
            if not isinstance(sequence, MoveSequenceItemV1_1):
                continue
            for annotation in sequence.annotations:
                anchor = annotation.anchor
                warnings = copy.deepcopy(annotation.warnings)
                if isinstance(anchor, PositionAnnotationAnchor):
                    # Position anchors become the equivalent top-level
                    # PositionAnchor with their existing warnings unchanged.
                    prose_anchor: PositionAnchor | None = PositionAnchor(
                        kind="position", fen=anchor.fen
                    )
                elif anchor is None:
                    # Null anchors stay null with their warnings unchanged.
                    prose_anchor = None
                else:
                    # Only a removed MoveNodeAnnotationAnchor generates the
                    # one-time unresolved-anchor warning.
                    prose_anchor = None
                    if not any(
                        warning.code == _ANNOTATION_ANCHOR_UNRESOLVED_CODE for warning in warnings
                    ):
                        warnings.append(
                            ExtractionWarning(
                                code=_ANNOTATION_ANCHOR_UNRESOLVED_CODE,
                                message=_ANNOTATION_ANCHOR_UNRESOLVED_MESSAGE,
                                evidence=copy.deepcopy(annotation.evidence),
                            )
                        )
                item_id, counter = _next_fallback_id(existing_ids, counter, kind="annotation")
                item = ProseItem(
                    id=item_id,
                    kind="prose",
                    text=annotation.text,
                    text_format=annotation.text_format,
                    anchor=prose_anchor,
                    evidence=copy.deepcopy(annotation.evidence),
                    confidence=annotation.confidence,
                    warnings=warnings,
                    extensions=copy.deepcopy(annotation.extensions),
                )
                result.setdefault(sequence.id, []).append(item)
    return result


def _build_merged_sequence_v1_1(
    group: _SequenceGroup,
    annotations: list[SequenceAnnotation],
    reading_flow: list[SequenceFlowEntry],
) -> MoveSequenceItemV1_1 | None:
    if not group.creation_order:
        return None
    root_orders = {uci: order for order, uci in enumerate(group.roots)}
    nodes: list[MoveNode] = []
    for trie_node in group.creation_order:
        nodes.append(_build_node(trie_node, root_orders))
    first = group.sequences[0]
    evidence = _stable_union([ref for sequence in group.sequences for ref in sequence.evidence])
    warnings = _stable_union(
        [warning for sequence in group.sequences for warning in sequence.warnings]
    )
    confidences = [
        sequence.confidence for sequence in group.sequences if sequence.confidence is not None
    ]
    return MoveSequenceItemV1_1(
        id=first.id,
        evidence=evidence,
        confidence=max(confidences) if confidences else None,
        warnings=warnings,
        extensions=copy.deepcopy(first.extensions),
        kind="move_sequence",
        title=first.title,
        initial_position=copy.deepcopy(first.initial_position),
        nodes=nodes,
        annotations=annotations,
        reading_flow=reading_flow,
    )


def consolidate_move_sequences_v1_1(
    package: ExtractionPackageV1_1,
    evidence_pages: list[PromptEvidencePage] | None = None,
) -> ExtractionPackageV1_1:
    """Return a fresh CCEF 1.1 package with one shared playable annotated tree.

    Merges duplicate legal UCI paths inside the same heading/title/initial-
    position scope using ``parent_id`` topology only; ``reading_flow`` is a
    source-presentation order that never defines parentage. Every source
    annotation is deep-copied exactly once with its evidence; anchors and flow
    references are remapped through the merged trie. Unlike the v1 entry, this
    path never rebuilds a linear fragment-only score from ``evidence_pages``,
    so inline variations and mainline continuation around annotations survive.
    """
    if type(package) is not ExtractionPackageV1_1:
        raise TypeError("package must be ExtractionPackageV1_1")
    if evidence_pages is not None and not all(
        type(page) is PromptEvidencePage for page in evidence_pages
    ):
        raise TypeError("evidence_pages must contain PromptEvidencePage values")
    validated = normalize_chess_moves_v1_1(package)
    groups, sequence_keys = _collect_groups(validated)
    node_refs: dict[tuple[str, str], _TrieNode | None] = {}
    omitted: dict[str, list[MoveNode]] = {}
    merged_by_key: dict[tuple[str | None, str, str | None, str], MoveSequenceItemV1_1 | None] = {}
    sequence_ids: dict[str, str] = {}
    for key, group in groups.items():
        _insert_valid_paths(group, node_refs, omitted)
        if not group.creation_order:
            merged_by_key[key] = None
            continue
        for index, trie_node in enumerate(group.creation_order, start=1):
            trie_node.output_id = f"n{index}"
        annotations, flow = _build_annotations_and_flow(group, node_refs)
        merged = _build_merged_sequence_v1_1(group, annotations, flow)
        merged_by_key[key] = merged
        if merged is not None:
            sequence_ids.update({sequence.id: merged.id for sequence in group.sequences})

    evidence_text = {
        entry.fragment.fragment_sha256: entry.fragment.text
        for page in evidence_pages or []
        for entry in page.fragments
    }
    fallbacks = _unresolved_fallbacks(
        validated,
        omitted,
        _annotation_covered_fragments(groups),
        evidence_text,
    )
    existing_ids = {item.id for item in validated.items}
    existing_ids.update(fallback.id for fallback in fallbacks.values())
    annotation_prose = _annotation_prose_fallbacks(groups, existing_ids)

    emitted: set[tuple[str | None, str, str | None, str]] = set()
    output_items: list[Any] = []
    for item in validated.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            output_items.append(copy.deepcopy(item))
            continue
        key = sequence_keys[item.id]
        if key not in emitted:
            emitted.add(key)
            merged = merged_by_key[key]
            if merged is not None:
                output_items.append(merged)
        # The group-level guard only prevents re-emitting a surviving merged
        # sequence; an all-unplayable group emits its annotation prose at every
        # source sequence's output location, in source item order.
        if merged_by_key[key] is None:
            output_items.extend(annotation_prose.get(item.id, []))
        fallback = fallbacks.get(item.id)
        if fallback is not None:
            output_items.append(fallback)

    output_items, diagnostics = _remap_references(
        output_items,
        validated.diagnostics,
        sequence_ids,
        set(sequence_keys),
        node_refs,
    )
    if evidence_pages is not None:
        output_items = _sort_items_by_evidence(output_items, evidence_pages)
    result_data = validated.model_dump(mode="json")
    result_data["items"] = [item.model_dump(mode="json") for item in output_items]
    result_data["diagnostics"] = [item.model_dump(mode="json") for item in diagnostics]
    consolidated = ExtractionPackageV1_1.model_validate(result_data)
    return normalize_chess_moves_v1_1(consolidated)


__all__ = ["consolidate_move_sequences", "consolidate_move_sequences_v1_1"]
