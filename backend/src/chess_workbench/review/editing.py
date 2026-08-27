"""Pure semantic edits for one normalized CCEF review package.

The browser sends user-facing chess commands, never arbitrary replacement
JSON.  This module updates a deep copy, rebuilds the exact-cover move flow and
re-runs the authoritative python-chess normalizer before returning it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal, TypeGuard, cast

import chess
from pydantic import JsonValue

from chess_workbench.extraction.contracts import (
    AnnotationFlowRef,
    Diagnostic,
    EvidenceRef,
    ExtractionPackage,
    ExtractionPackageV1_1,
    HeadingItem,
    MoveFlowRef,
    MoveNode,
    MoveNodeAnchor,
    MoveNodeAnnotationAnchor,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    ProseItem,
    SequenceAnnotation,
    StartPosition,
)
from chess_workbench.extraction.validation import (
    normalize_chess_moves,
    normalize_chess_moves_v1_1,
)
from chess_workbench.schemas.review import (
    PdfReviewAddLine,
    PdfReviewDeleteSubtree,
    PdfReviewEditOperation,
    PdfReviewEditText,
    PdfReviewMakeMainline,
    PdfReviewPromoteVariation,
    PdfReviewSetNag,
)

ReviewPackage = ExtractionPackage | ExtractionPackageV1_1
ReviewSequence = MoveSequenceItem | MoveSequenceItemV1_1


@dataclass(frozen=True, slots=True)
class ReviewEditResult:
    package: ReviewPackage
    decisions: dict[str, JsonValue]


def apply_review_edit(
    package: ReviewPackage, operation: PdfReviewEditOperation
) -> ReviewEditResult:
    """Apply one bounded review operation to a fresh package value."""
    if type(package) not in (ExtractionPackage, ExtractionPackageV1_1):
        raise TypeError("package must be a supported CCEF review package")
    result = copy.deepcopy(package)

    if isinstance(operation, PdfReviewAddLine):
        decisions = _add_line(result, operation)
    elif isinstance(operation, PdfReviewDeleteSubtree):
        decisions = _delete_subtree(result, operation)
    elif isinstance(operation, PdfReviewPromoteVariation):
        decisions = _promote_variation(result, operation)
    elif isinstance(operation, PdfReviewMakeMainline):
        decisions = _make_mainline(result, operation)
    elif isinstance(operation, PdfReviewEditText):
        decisions = _edit_text(result, operation)
    elif isinstance(operation, PdfReviewSetNag):
        decisions = _set_nag(result, operation)
    else:  # pragma: no cover - discriminated request contract is exhaustive.
        raise TypeError("unsupported review edit operation")

    if isinstance(result, ExtractionPackageV1_1):
        normalized: ReviewPackage = normalize_chess_moves_v1_1(result)
    else:
        normalized = normalize_chess_moves(result)
    if normalized.model_dump(mode="json") == package.model_dump(mode="json"):
        raise ValueError("review edit did not change the package")
    return ReviewEditResult(package=normalized, decisions=decisions)


def _is_sequence(item: object) -> TypeGuard[ReviewSequence]:
    return isinstance(item, (MoveSequenceItem, MoveSequenceItemV1_1))


def _sequence(package: ReviewPackage, sequence_id: str) -> ReviewSequence:
    match = next(
        (item for item in package.items if _is_sequence(item) and item.id == sequence_id),
        None,
    )
    if match is None:
        raise ValueError("review move sequence was not found")
    return match


def _node(sequence: ReviewSequence, node_id: str) -> MoveNode:
    match = next((node for node in sequence.nodes if node.id == node_id), None)
    if match is None:
        raise ValueError("review move node was not found")
    return match


def _initial_board(sequence: ReviewSequence) -> chess.Board:
    initial = sequence.initial_position
    try:
        board = chess.Board() if isinstance(initial, StartPosition) else chess.Board(initial.fen)
    except ValueError:
        raise ValueError("review sequence does not have a legal initial position") from None
    if not board.is_valid():
        raise ValueError("review sequence does not have a legal initial position")
    return board


def _board_after(sequence: ReviewSequence, parent_node_id: str | None) -> chess.Board:
    if parent_node_id is None:
        return _initial_board(sequence)
    parent = _node(sequence, parent_node_id)
    if parent.validation_status != "valid" or parent.fen_after is None:
        raise ValueError("review line must start from a valid move node")
    try:
        board = chess.Board(parent.fen_after)
    except ValueError:
        raise ValueError("review line must start from a valid move node") from None
    if not board.is_valid():
        raise ValueError("review line must start from a valid move node")
    return board


def _add_line(package: ReviewPackage, operation: PdfReviewAddLine) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    page_range = package.source.page_range
    if page_range is None or not (
        page_range.start_page <= operation.evidence_page <= page_range.end_page
    ):
        raise ValueError("review move evidence page is outside the source range")

    board = _board_after(sequence, operation.parent_node_id)
    parent_id = operation.parent_node_id
    created_ids: list[str] = []
    traversed_ids: list[str] = []
    for uci in operation.moves:
        existing = next(
            (
                candidate
                for candidate in sequence.nodes
                if candidate.parent_id == parent_id
                and candidate.validation_status == "valid"
                and candidate.uci_candidate == uci
            ),
            None,
        )
        if existing is not None:
            traversed_ids.append(existing.id)
            parent_id = existing.id
            assert existing.fen_after is not None
            board = chess.Board(existing.fen_after)
            continue

        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise ValueError("review line contains an invalid UCI move") from None
        if move not in board.legal_moves:
            raise ValueError("review line contains a move that is illegal in its position")
        san = board.san(move)
        fen_before = board.fen(en_passant="fen")
        move_number = board.fullmove_number
        side_to_move: Literal["w", "b"] = "w" if board.turn else "b"
        sibling_order = sum(1 for node in sequence.nodes if node.parent_id == parent_id)
        node_id = _next_local_id(sequence)
        board.push(move)
        fen_after = board.fen(en_passant="fen")
        sequence.nodes.append(
            MoveNode(
                id=node_id,
                parent_id=parent_id,
                sibling_order=sibling_order,
                move_text=san,
                move_number=move_number,
                side_to_move=side_to_move,
                san_candidate=san,
                uci_candidate=uci,
                nags=[],
                validation_status="valid",
                fen_before=fen_before,
                fen_after=fen_after,
                evidence=[EvidenceRef(page=operation.evidence_page)],
                confidence=None,
                warnings=[],
                extensions={},
            )
        )
        created_ids.append(node_id)
        parent_id = node_id

    if not created_ids:
        raise ValueError("review line already exists")
    _reflow(sequence)
    return {
        "operation": "add_line",
        "sequence_id": operation.sequence_id,
        "parent_node_id": operation.parent_node_id,
        "moves": list(operation.moves),
        "created_node_ids": cast(list[JsonValue], created_ids),
        "traversed_node_ids": cast(list[JsonValue], traversed_ids),
        "evidence_page": operation.evidence_page,
    }


def _next_local_id(sequence: ReviewSequence) -> str:
    used = {node.id for node in sequence.nodes}
    if isinstance(sequence, MoveSequenceItemV1_1):
        used.update(annotation.id for annotation in sequence.annotations)
    index = 1
    while f"manual-{index}" in used:
        index += 1
    return f"manual-{index}"


def _delete_subtree(
    package: ReviewPackage, operation: PdfReviewDeleteSubtree
) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    _node(sequence, operation.node_id)
    removed_ids = {operation.node_id}
    changed = True
    while changed:
        changed = False
        for node in sequence.nodes:
            if node.parent_id in removed_ids and node.id not in removed_ids:
                removed_ids.add(node.id)
                changed = True

    removed_annotations: set[str] = set()
    if isinstance(sequence, MoveSequenceItemV1_1):
        removed_annotations = {
            annotation.id
            for annotation in sequence.annotations
            if isinstance(annotation.anchor, MoveNodeAnnotationAnchor)
            and annotation.anchor.node_id in removed_ids
        }
        sequence.annotations = [
            annotation
            for annotation in sequence.annotations
            if annotation.id not in removed_annotations
        ]
        sequence.reading_flow = [
            entry
            for entry in sequence.reading_flow
            if not (
                (isinstance(entry, MoveFlowRef) and entry.node_id in removed_ids)
                or (
                    isinstance(entry, AnnotationFlowRef)
                    and entry.annotation_id in removed_annotations
                )
            )
        ]
    sequence.nodes = [node for node in sequence.nodes if node.id not in removed_ids]

    removed_sequence = not sequence.nodes
    if removed_sequence:
        if isinstance(package, ExtractionPackageV1_1):
            package.items = [item for item in package.items if item.id != sequence.id]
        else:
            package.items = [item for item in package.items if item.id != sequence.id]
    else:
        _renumber_siblings(sequence)
        _reflow(sequence)

    for item in package.items:
        if (
            isinstance(item, ProseItem)
            and isinstance(item.anchor, MoveNodeAnchor)
            and item.anchor.sequence_id == sequence.id
            and (removed_sequence or item.anchor.node_id in removed_ids)
        ):
            item.anchor = None

    package.diagnostics = [
        diagnostic
        for diagnostic in package.diagnostics
        if not _diagnostic_removed(
            diagnostic,
            sequence_id=sequence.id,
            removed_node_ids=removed_ids,
            removed_sequence=removed_sequence,
        )
    ]
    return {
        "operation": "delete_subtree",
        "sequence_id": operation.sequence_id,
        "node_id": operation.node_id,
        "removed_node_count": len(removed_ids),
        "removed_annotation_count": len(removed_annotations),
        "removed_sequence": removed_sequence,
    }


def _diagnostic_removed(
    diagnostic: Diagnostic,
    *,
    sequence_id: str,
    removed_node_ids: set[str],
    removed_sequence: bool,
) -> bool:
    if diagnostic.item_id != sequence_id:
        return False
    return removed_sequence or diagnostic.node_id in removed_node_ids


def _renumber_siblings(sequence: ReviewSequence) -> None:
    parents = {node.parent_id for node in sequence.nodes}
    for parent_id in parents:
        siblings = sorted(
            (node for node in sequence.nodes if node.parent_id == parent_id),
            key=lambda node: node.sibling_order,
        )
        for order, node in enumerate(siblings):
            node.sibling_order = order


def _promote_variation(
    package: ReviewPackage, operation: PdfReviewPromoteVariation
) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    target = _node(sequence, operation.node_id)
    if target.sibling_order == 0:
        raise ValueError("review move is already the first variation")
    previous = next(
        node
        for node in sequence.nodes
        if node.parent_id == target.parent_id and node.sibling_order == target.sibling_order - 1
    )
    old_order = target.sibling_order
    target.sibling_order -= 1
    previous.sibling_order += 1
    _reflow(sequence)
    return {
        "operation": "promote_variation",
        "sequence_id": operation.sequence_id,
        "node_id": operation.node_id,
        "from_order": old_order,
        "to_order": target.sibling_order,
    }


def _make_mainline(
    package: ReviewPackage, operation: PdfReviewMakeMainline
) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    current = _node(sequence, operation.node_id)
    changed_nodes: list[str] = []
    while True:
        old_order = current.sibling_order
        if old_order > 0:
            for sibling in sequence.nodes:
                if sibling.parent_id != current.parent_id or sibling.id == current.id:
                    continue
                if sibling.sibling_order < old_order:
                    sibling.sibling_order += 1
            current.sibling_order = 0
            changed_nodes.append(current.id)
        if current.parent_id is None:
            break
        current = _node(sequence, current.parent_id)
    if not changed_nodes:
        raise ValueError("review line is already the mainline")
    _reflow(sequence)
    return {
        "operation": "make_mainline",
        "sequence_id": operation.sequence_id,
        "node_id": operation.node_id,
        "promoted_node_ids": cast(list[JsonValue], changed_nodes),
    }


def _edit_text(package: ReviewPackage, operation: PdfReviewEditText) -> dict[str, JsonValue]:
    item = next((item for item in package.items if item.id == operation.item_id), None)
    if item is None:
        raise ValueError("review text item was not found")
    if operation.annotation_id is not None:
        if not isinstance(item, MoveSequenceItemV1_1):
            raise ValueError("review annotation was not found")
        annotation = next(
            (
                candidate
                for candidate in item.annotations
                if candidate.id == operation.annotation_id
            ),
            None,
        )
        if annotation is None:
            raise ValueError("review annotation was not found")
        before = annotation.text
        annotation.text = operation.text
        if operation.text_format is not None:
            annotation.text_format = operation.text_format
        target = "annotation"
    elif isinstance(item, (HeadingItem, ProseItem)):
        before = item.text
        item.text = operation.text
        if isinstance(item, ProseItem) and operation.text_format is not None:
            item.text_format = operation.text_format
        elif isinstance(item, HeadingItem) and operation.text_format is not None:
            raise ValueError("heading text does not have a text format")
        target = item.kind
    else:
        raise ValueError("review item does not contain editable text")
    if before == operation.text:
        raise ValueError("review text is unchanged")
    return {
        "operation": "edit_text",
        "target": target,
        "item_id": operation.item_id,
        "annotation_id": operation.annotation_id,
    }


def _set_nag(package: ReviewPackage, operation: PdfReviewSetNag) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    target = _node(sequence, operation.node_id)
    nags = [] if operation.nag is None else [operation.nag]
    if target.nags == nags:
        raise ValueError("review move NAG is unchanged")
    target.nags = nags
    return {
        "operation": "set_nag",
        "sequence_id": operation.sequence_id,
        "node_id": operation.node_id,
        "nag": operation.nag,
    }


def _pgn_node_order(sequence: ReviewSequence) -> list[MoveNode]:
    children: dict[str | None, list[MoveNode]] = {}
    for node in sequence.nodes:
        children.setdefault(node.parent_id, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: node.sibling_order)

    ordered: list[MoveNode] = []

    def emit_from(parent_id: str | None) -> None:
        siblings = children.get(parent_id, [])
        if not siblings:
            return
        main = siblings[0]
        ordered.append(main)
        for variation in siblings[1:]:
            emit_variation(variation)
        emit_from(main.id)

    def emit_variation(node: MoveNode) -> None:
        ordered.append(node)
        emit_from(node.id)

    emit_from(None)
    if len(ordered) != len(sequence.nodes):
        raise ValueError("review move tree is disconnected")
    return ordered


def _reflow(sequence: ReviewSequence) -> None:
    ordered = _pgn_node_order(sequence)
    if not isinstance(sequence, MoveSequenceItemV1_1):
        sequence.nodes = ordered
        return

    prefix: list[AnnotationFlowRef] = []
    after_move: dict[str, list[AnnotationFlowRef]] = {}
    current_move: str | None = None
    for entry in sequence.reading_flow:
        if isinstance(entry, MoveFlowRef):
            current_move = entry.node_id
        elif current_move is None:
            prefix.append(entry)
        else:
            after_move.setdefault(current_move, []).append(entry)

    flow: list[MoveFlowRef | AnnotationFlowRef] = list(prefix)
    for node in ordered:
        flow.append(MoveFlowRef(kind="move", node_id=node.id))
        flow.extend(after_move.get(node.id, []))
    annotation_by_id: dict[str, SequenceAnnotation] = {
        annotation.id: annotation for annotation in sequence.annotations
    }
    sequence.nodes = ordered
    sequence.reading_flow = flow
    sequence.annotations = [
        annotation_by_id[entry.annotation_id]
        for entry in flow
        if isinstance(entry, AnnotationFlowRef)
    ]


__all__ = ["ReviewEditResult", "apply_review_edit"]
