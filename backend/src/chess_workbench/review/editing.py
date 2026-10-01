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
    FenPosition,
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
    StartPosition,
    UnresolvedItem,
)
from chess_workbench.extraction.notation import NAG_OVERRIDE_EXTENSION, effective_move_nags
from chess_workbench.extraction.validation import (
    normalize_chess_moves,
    normalize_chess_moves_v1_1,
)
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import (
    PdfReviewAddLine,
    PdfReviewDeleteSubtree,
    PdfReviewDetachPositionAnchor,
    PdfReviewEditOperation,
    PdfReviewEditText,
    PdfReviewExcludeItem,
    PdfReviewMakeMainline,
    PdfReviewPromoteVariation,
    PdfReviewReattachVariation,
    PdfReviewResolveUnresolved,
    PdfReviewSetInitialPosition,
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
    elif isinstance(operation, PdfReviewExcludeItem):
        decisions = _exclude_item(result, operation)
    elif isinstance(operation, PdfReviewDetachPositionAnchor):
        decisions = _detach_position_anchor(result, operation)
    elif isinstance(operation, PdfReviewResolveUnresolved):
        decisions = _resolve_unresolved(result, operation)
    elif isinstance(operation, PdfReviewSetInitialPosition):
        decisions = _set_initial_position(result, operation)
    elif isinstance(operation, PdfReviewReattachVariation):
        decisions = _reattach_variation(result, operation)
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


def _add_line(
    package: ReviewPackage,
    operation: PdfReviewAddLine,
    *,
    source_evidence: list[EvidenceRef] | None = None,
) -> dict[str, JsonValue]:
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
    path_ids: list[str] = []
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
            path_ids.append(existing.id)
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
                evidence=source_evidence or [EvidenceRef(page=operation.evidence_page)],
                confidence=None,
                warnings=[],
                extensions={},
            )
        )
        created_ids.append(node_id)
        path_ids.append(node_id)
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
        "path_node_ids": cast(list[JsonValue], path_ids),
        "evidence_page": operation.evidence_page,
        "terminal_node_id": parent_id,
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
            package.items.remove(cast(MoveSequenceItemV1_1, sequence))
        else:
            package.items.remove(cast(MoveSequenceItem, sequence))
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
    if effective_move_nags(target) == nags:
        raise ValueError("review move NAG is unchanged")
    target.nags = nags
    target.extensions[NAG_OVERRIDE_EXTENSION] = True
    return {
        "operation": "set_nag",
        "sequence_id": operation.sequence_id,
        "node_id": operation.node_id,
        "nag": operation.nag,
    }


def _exclude_item(package: ReviewPackage, operation: PdfReviewExcludeItem) -> dict[str, JsonValue]:
    item_index = next(
        (
            index
            for index, candidate in enumerate(package.items)
            if candidate.id == operation.item_id
        ),
        None,
    )
    if item_index is None:
        raise ValueError("review item was not found")
    item = package.items[item_index]
    if _is_sequence(item):
        raise ValueError("move sequences must be removed with delete_subtree")
    package.items.pop(item_index)
    removed_diagnostics = sum(
        1 for diagnostic in package.diagnostics if diagnostic.item_id == operation.item_id
    )
    package.diagnostics = [
        diagnostic for diagnostic in package.diagnostics if diagnostic.item_id != operation.item_id
    ]
    return {
        "operation": "exclude_item",
        "item_id": operation.item_id,
        "removed_diagnostic_count": removed_diagnostics,
    }


def _detach_position_anchor(
    package: ReviewPackage, operation: PdfReviewDetachPositionAnchor
) -> dict[str, JsonValue]:
    """Keep review text in source order while explicitly removing a bad FEN binding."""
    current_issue_ids = {
        issue.issue_id
        for issue in inspect_review_candidate(package).issues
        if issue.blocking
        and issue.scope in ("item", "annotation")
        and issue.code in ("position_anchor_no_match", "position_anchor_ambiguous")
    }
    if operation.issue_id not in current_issue_ids:
        raise ValueError("review position-anchor issue was not found")
    for item in package.items:
        if isinstance(item, ProseItem) and isinstance(item.anchor, PositionAnchor):
            issue_ids = {
                f"item:{item.id}:position-anchor-no-match",
                f"item:{item.id}:position-anchor-ambiguous",
            }
            if operation.issue_id in issue_ids:
                item.anchor = None
                return {
                    "operation": "detach_position_anchor",
                    "issue_id": operation.issue_id,
                    "item_id": item.id,
                    "annotation_id": None,
                }
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        for annotation in item.annotations:
            if not isinstance(annotation.anchor, PositionAnnotationAnchor):
                continue
            issue_ids = {
                f"annotation:{item.id}:{annotation.id}:position-anchor-no-match",
                f"annotation:{item.id}:{annotation.id}:position-anchor-ambiguous",
            }
            if operation.issue_id in issue_ids:
                annotation.anchor = None
                return {
                    "operation": "detach_position_anchor",
                    "issue_id": operation.issue_id,
                    "item_id": item.id,
                    "annotation_id": annotation.id,
                }
    raise ValueError("review position-anchor issue was not found")


def _validated_fen(value: str) -> str:
    try:
        board = chess.Board(value)
    except ValueError:
        raise ValueError("review initial FEN is invalid") from None
    if not board.is_valid():
        raise ValueError("review initial FEN is not a legal position")
    return board.fen(en_passant="fen")


def _set_initial_position(
    package: ReviewPackage, operation: PdfReviewSetInitialPosition
) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    fen = _validated_fen(operation.fen)
    if isinstance(sequence.initial_position, FenPosition) and sequence.initial_position.fen == fen:
        raise ValueError("review initial position is unchanged")
    sequence.initial_position = FenPosition(kind="fen", fen=fen)
    return {"operation": "set_initial_position", "sequence_id": sequence.id, "fen": fen}


def _reattach_variation(
    package: ReviewPackage, operation: PdfReviewReattachVariation
) -> dict[str, JsonValue]:
    sequence = _sequence(package, operation.sequence_id)
    target = _sequence(package, operation.target_sequence_id or operation.sequence_id)
    node = _node(sequence, operation.node_id)
    parent_id = operation.parent_node_id
    if sequence.id == target.id and node.parent_id == parent_id:
        raise ValueError("review variation already has this parent")
    descendants = {node.id}
    changed = True
    while changed:
        changed = False
        for candidate in sequence.nodes:
            if candidate.parent_id in descendants and candidate.id not in descendants:
                descendants.add(candidate.id)
                changed = True
    if sequence.id == target.id and parent_id in descendants:
        raise ValueError("review variation cannot attach to its descendant")
    board = _board_after(target, parent_id)
    try:
        board.parse_san(node.san_candidate or node.move_text)
    except ValueError:
        raise ValueError("review variation move is illegal from its new parent") from None
    old_parent = node.parent_id
    if sequence.id != target.id:
        if not isinstance(sequence, MoveSequenceItemV1_1) or not isinstance(
            target, MoveSequenceItemV1_1
        ):
            raise ValueError("cross-sequence move requires a 1.1 review package")
        moved = [candidate for candidate in sequence.nodes if candidate.id in descendants]
        remaining = [candidate for candidate in sequence.nodes if candidate.id not in descendants]
        used = {candidate.id for candidate in target.nodes}
        used.update(annotation.id for annotation in target.annotations)
        mapped: dict[str, str] = {}
        for candidate in moved:
            new_id = candidate.id
            serial = 1
            while new_id in used:
                new_id = f"transferred-{serial}"
                serial += 1
            used.add(new_id)
            mapped[candidate.id] = new_id
        moved_annotation_ids: set[str] = set()
        current_move: str | None = None
        for flow in sequence.reading_flow:
            if isinstance(flow, MoveFlowRef):
                current_move = flow.node_id
            elif current_move in descendants:
                moved_annotation_ids.add(flow.annotation_id)
        moved_annotations = [
            annotation
            for annotation in sequence.annotations
            if annotation.id in moved_annotation_ids
        ]
        moved_flow = [
            flow
            for flow in sequence.reading_flow
            if (isinstance(flow, MoveFlowRef) and flow.node_id in descendants)
            or (isinstance(flow, AnnotationFlowRef) and flow.annotation_id in moved_annotation_ids)
        ]
        annotation_ids: dict[str, str] = {}
        for annotation in moved_annotations:
            if isinstance(annotation.anchor, MoveNodeAnnotationAnchor):
                if annotation.anchor.node_id in mapped:
                    annotation.anchor.node_id = mapped[annotation.anchor.node_id]
                else:
                    annotation.anchor = None
            new_id = annotation.id
            serial = 1
            while new_id in used:
                new_id = f"transferred-note-{serial}"
                serial += 1
            used.add(new_id)
            annotation_ids[annotation.id] = new_id
            annotation.id = new_id
        sequence.annotations = [
            annotation for annotation in sequence.annotations if annotation not in moved_annotations
        ]
        sequence.reading_flow = [
            flow
            for flow in sequence.reading_flow
            if not (
                (isinstance(flow, MoveFlowRef) and flow.node_id in descendants)
                or (
                    isinstance(flow, AnnotationFlowRef)
                    and flow.annotation_id in moved_annotation_ids
                )
            )
        ]
        for candidate in moved:
            original_id = candidate.id
            candidate.id = mapped[original_id]
            candidate.parent_id = (
                parent_id if original_id == node.id else mapped[cast(str, candidate.parent_id)]
            )
        node.sibling_order = sum(
            1 for candidate in target.nodes if candidate.parent_id == parent_id
        )
        sequence.nodes = remaining
        target.nodes.extend(moved)
        target.annotations.extend(moved_annotations)
        target.reading_flow.extend(
            MoveFlowRef(kind="move", node_id=mapped[flow.node_id])
            if isinstance(flow, MoveFlowRef)
            else AnnotationFlowRef(
                kind="annotation", annotation_id=annotation_ids[flow.annotation_id]
            )
            for flow in moved_flow
        )
        target.evidence.extend(node.evidence)
        for item in package.items:
            if (
                isinstance(item, ProseItem)
                and isinstance(item.anchor, MoveNodeAnchor)
                and item.anchor.sequence_id == sequence.id
                and item.anchor.node_id in mapped
            ):
                item.anchor.sequence_id = target.id
                item.anchor.node_id = mapped[item.anchor.node_id]
        for diagnostic in package.diagnostics:
            if diagnostic.item_id == sequence.id and diagnostic.node_id in mapped:
                diagnostic.item_id = target.id
                diagnostic.node_id = mapped[diagnostic.node_id]
        if remaining:
            _renumber_siblings(sequence)
            _reflow(sequence)
        else:
            cast(ExtractionPackageV1_1, package).items.remove(sequence)
            package.diagnostics = [
                diagnostic
                for diagnostic in package.diagnostics
                if diagnostic.item_id != sequence.id
            ]
        _renumber_siblings(target)
        _reflow(target)
        return {
            "operation": "reattach_variation",
            "sequence_id": sequence.id,
            "target_sequence_id": target.id,
            "node_id": node.id,
            "from_parent_node_id": old_parent,
            "parent_node_id": parent_id,
            "moved_node_count": len(moved),
        }
    node.parent_id = parent_id
    node.sibling_order = sum(
        1
        for candidate in sequence.nodes
        if candidate.id != node.id and candidate.parent_id == parent_id
    )
    _renumber_siblings(sequence)
    _reflow(sequence)
    return {
        "operation": "reattach_variation",
        "sequence_id": sequence.id,
        "node_id": node.id,
        "from_parent_node_id": old_parent,
        "parent_node_id": parent_id,
    }


def _set_new_line_nags(
    sequence: ReviewSequence,
    decision: dict[str, JsonValue],
    moves: list[str],
    nags: list[int | None],
) -> None:
    if not nags:
        return
    if len(nags) != len(moves):
        raise ValueError("review line NAG count must match its moves")
    created_ids = set(cast(list[str], decision["created_node_ids"]))
    path_ids = cast(list[str], decision["path_node_ids"])
    for node_id, nag in zip(path_ids, nags, strict=True):
        if node_id in created_ids and nag is not None:
            _node(sequence, node_id).nags = [nag]


def _resolve_unresolved(
    package: ReviewPackage, operation: PdfReviewResolveUnresolved
) -> dict[str, JsonValue]:
    index = next((i for i, item in enumerate(package.items) if item.id == operation.item_id), None)
    if index is None or not isinstance(package.items[index], (UnresolvedItem, ProseItem)):
        raise ValueError("review source text item was not found")
    item = cast(UnresolvedItem | ProseItem, package.items[index])
    if operation.following and (operation.as_kind != "line" or operation.sequence_id is None):
        raise ValueError("following fragments require a line in an existing score")
    text = operation.text or (
        item.text if isinstance(item, ProseItem) else item.raw_text or item.details
    )
    recovered: list[str] = []
    if operation.as_kind == "prose":
        if not text:
            raise ValueError("review prose requires text")
        package.items[index] = ProseItem(
            kind="prose",
            id=item.id,
            text=text,
            text_format="plain",
            anchor=None,
            evidence=item.evidence,
            confidence=item.confidence,
            warnings=item.warnings,
            extensions=item.extensions,
        )
    elif operation.as_kind == "annotation":
        if not isinstance(package, ExtractionPackageV1_1) or not operation.sequence_id or not text:
            raise ValueError("review annotation requires a 1.1 sequence and text")
        sequence = _sequence(package, operation.sequence_id)
        if not isinstance(sequence, MoveSequenceItemV1_1):
            raise ValueError("review annotation requires a 1.1 sequence")
        anchor = None
        if operation.anchor_node_id is not None:
            _node(sequence, operation.anchor_node_id)
            anchor = MoveNodeAnnotationAnchor(
                kind="move_node", node_id=operation.anchor_node_id, relation="after"
            )
        annotation_id = _next_local_id(sequence)
        sequence.annotations.append(
            SequenceAnnotation(
                id=annotation_id,
                text=text,
                text_format="plain",
                anchor=anchor,
                evidence=item.evidence,
            )
        )
        sequence.reading_flow.append(
            AnnotationFlowRef(kind="annotation", annotation_id=annotation_id)
        )
        package.items.pop(index)
    else:
        if not isinstance(package, ExtractionPackageV1_1) or not operation.moves:
            raise ValueError("review line requires a 1.1 package and UCI moves")
        if operation.nags and len(operation.nags) != len(operation.moves):
            raise ValueError("review line NAG count must match its moves")
        if operation.sequence_id is None:
            if operation.initial_fen is None:
                raise ValueError("review new line requires an initial FEN")
            fen = _validated_fen(operation.initial_fen)
            sequence_id = f"manual-sequence-{len(package.items) + 1}"
            while any(existing.id == sequence_id for existing in package.items):
                sequence_id += "-x"
            board = chess.Board(fen)
            nodes: list[MoveNode] = []
            parent_id = None
            for n, uci in enumerate(operation.moves, 1):
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    raise ValueError("review line contains an illegal move")
                san = board.san(move)
                nag = operation.nags[n - 1] if operation.nags else None
                node_id = f"manual-{n}"
                nodes.append(
                    MoveNode(
                        id=node_id,
                        parent_id=parent_id,
                        sibling_order=0,
                        move_text=san,
                        nags=[] if nag is None else [nag],
                        evidence=item.evidence,
                    )
                )
                board.push(move)
                parent_id = node_id
            package.items[index] = MoveSequenceItemV1_1(
                kind="move_sequence",
                id=sequence_id,
                title=None,
                initial_position=FenPosition(kind="fen", fen=fen),
                nodes=nodes,
                annotations=[],
                reading_flow=[MoveFlowRef(kind="move", node_id=node.id) for node in nodes],
                evidence=item.evidence,
            )
        else:
            sequence = _sequence(package, operation.sequence_id)
            first_result = _add_line(
                package,
                PdfReviewAddLine(
                    kind="add_line",
                    sequence_id=sequence.id,
                    parent_node_id=operation.anchor_node_id,
                    moves=operation.moves,
                    evidence_page=item.evidence[0].page,
                ),
                source_evidence=item.evidence,
            )
            _set_new_line_nags(sequence, first_result, operation.moves, operation.nags)
            package.items.pop(index)
            parent_id = cast(str, first_result["terminal_node_id"])
            for following in operation.following:
                next_index = next(
                    (
                        i
                        for i, candidate in enumerate(package.items)
                        if candidate.id == following.item_id
                    ),
                    None,
                )
                if next_index is None or not isinstance(package.items[next_index], UnresolvedItem):
                    raise ValueError("following unresolved fragment was not found")
                next_item = cast(UnresolvedItem, package.items[next_index])
                result = _add_line(
                    package,
                    PdfReviewAddLine(
                        kind="add_line",
                        sequence_id=sequence.id,
                        parent_node_id=parent_id,
                        moves=following.moves,
                        evidence_page=next_item.evidence[0].page,
                    ),
                    source_evidence=next_item.evidence,
                )
                _set_new_line_nags(sequence, result, following.moves, following.nags)
                parent_id = cast(str, result["terminal_node_id"])
                recovered.append(next_item.id)
                package.items.pop(next_index)
            package.diagnostics = [
                diagnostic
                for diagnostic in package.diagnostics
                if diagnostic.item_id not in recovered
            ]
    if isinstance(item, ProseItem) and operation.as_kind == "line" and operation.text:
        remainder_id = f"{item.id}-remainder"
        while any(existing.id == remainder_id for existing in package.items):
            remainder_id += "-x"
        package.items.insert(
            index, item.model_copy(update={"id": remainder_id, "text": operation.text.strip()})
        )
    package.diagnostics = [
        diagnostic for diagnostic in package.diagnostics if diagnostic.item_id != item.id
    ]
    return {
        "operation": "resolve_unresolved",
        "item_id": item.id,
        "as_kind": operation.as_kind,
        "recovered_item_ids": cast(list[JsonValue], recovered),
    }


def _source_node_order(sequence: ReviewSequence) -> list[MoveNode]:
    by_id = {node.id: node for node in sequence.nodes}
    source_ids = (
        [flow.node_id for flow in sequence.reading_flow if isinstance(flow, MoveFlowRef)]
        if isinstance(sequence, MoveSequenceItemV1_1)
        else []
    )
    source_ids.extend(node.id for node in sequence.nodes if node.id not in source_ids)
    pending = list(dict.fromkeys(source_ids))
    ordered: list[MoveNode] = []
    emitted: set[str] = set()
    while pending:
        ready = [
            node_id
            for node_id in pending
            if by_id[node_id].parent_id is None or by_id[node_id].parent_id in emitted
        ]
        if not ready:
            raise ValueError("review move tree is disconnected")
        node_id = ready[0]
        ordered.append(by_id[node_id])
        emitted.add(node_id)
        pending.remove(node_id)
    return ordered


def _reflow(sequence: ReviewSequence) -> None:
    # Nodes need topological order; reading_flow separately records the PDF's
    # reading order and must not be rewritten to match the edited chess tree.
    ordered = _source_node_order(sequence)
    sequence.nodes = ordered
    if not isinstance(sequence, MoveSequenceItemV1_1):
        return

    node_ids = {node.id for node in ordered}
    annotation_by_id: dict[str, SequenceAnnotation] = {
        annotation.id: annotation for annotation in sequence.annotations
    }
    flow: list[MoveFlowRef | AnnotationFlowRef] = []
    seen_moves: set[str] = set()
    seen_annotations: set[str] = set()
    for entry in sequence.reading_flow:
        if isinstance(entry, MoveFlowRef) and entry.node_id in node_ids:
            flow.append(entry)
            seen_moves.add(entry.node_id)
        elif isinstance(entry, AnnotationFlowRef) and entry.annotation_id in annotation_by_id:
            flow.append(entry)
            seen_annotations.add(entry.annotation_id)
    for node in ordered:
        if node.id not in seen_moves:
            flow.append(MoveFlowRef(kind="move", node_id=node.id))
    for annotation in sequence.annotations:
        if annotation.id not in seen_annotations:
            flow.append(AnnotationFlowRef(kind="annotation", annotation_id=annotation.id))
    if [entry.node_id for entry in flow if isinstance(entry, MoveFlowRef)] != [
        node.id for node in ordered
    ]:
        before: list[AnnotationFlowRef] = []
        after_move: dict[str, list[AnnotationFlowRef]] = {}
        current_move: str | None = None
        for entry in flow:
            if isinstance(entry, MoveFlowRef):
                current_move = entry.node_id
            elif current_move is None:
                before.append(entry)
            else:
                after_move.setdefault(current_move, []).append(entry)
        flow = list(before)
        for node in ordered:
            flow.append(MoveFlowRef(kind="move", node_id=node.id))
            flow.extend(after_move.get(node.id, []))
    sequence.reading_flow = flow
    sequence.annotations = [
        annotation_by_id[entry.annotation_id]
        for entry in flow
        if isinstance(entry, AnnotationFlowRef)
    ]


__all__ = ["ReviewEditResult", "apply_review_edit"]
