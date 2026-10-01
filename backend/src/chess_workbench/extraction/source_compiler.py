"""Compile source-bound semantic events into a reviewable CCEF 1.1 package.

The interpreter supplies meanings and relationships, never CCEF bookkeeping.
One bad event becomes a local unresolved item while independent events survive.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Literal

import chess
from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    CCEF_VERSION_1_1,
    AnnotationFlowRef,
    Diagnostic,
    EvidenceRef,
    ExtractionPackageV1_1,
    ExtractionWarning,
    FenPosition,
    FigureItem,
    HeadingItem,
    MoveFlowRef,
    MoveNode,
    MoveNodeAnchor,
    MoveNodeAnnotationAnchor,
    MoveSequenceItemV1_1,
    PageRange,
    ProseItem,
    Provenance,
    SequenceAnnotation,
    SourceDescriptor,
    StartPosition,
    UnresolvedItem,
)
from .draft import find_diagram_seeds
from .notation import source_punctuation_nag
from .prompting import CcefPromptContext
from .validation import _clean_move_token, normalize_chess_moves_v1_1

_PRINTED_NUMBER = re.compile(r"(?<![A-Za-z0-9])([1-9]\d{0,2})\s*(\.{1,3})?\s*$")
_INLINE_NUMBER = re.compile(r"^([1-9]\d{0,2})(\s*\.{1,3}|\s+|(?=[KQRBNa-hO0]))")


def _printed_move_context(
    source: str, start: int, value: str
) -> tuple[int | None, Literal["w", "b"] | None]:
    prefix = _INLINE_NUMBER.match(value)
    if prefix is None:
        prefix = _PRINTED_NUMBER.search(source[max(0, start - 12) : start])
    if prefix is None:
        return None, None
    return int(prefix.group(1)), "b" if (prefix.group(2) or "").strip() == "..." else "w"


class _EventProblem(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SourceSlice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page: int = Field(ge=1)
    order: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class SemanticEvent(BaseModel):
    """A single proposed meaning attached to an exact source substring."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    kind: Literal["heading", "prose", "move", "annotation", "unresolved"]
    source: SourceSlice
    sequence: str | None = None
    parent: str | None = None
    anchor: str | None = None
    relation: Literal["before", "after"] | None = None
    level: int | None = None
    issue_code: (
        Literal[
            "source_quote_missing",
            "semantic_chunk_failed",
            "missing_context",
            "ambiguous_relation",
            "unparsed_notation",
        ]
        | None
    ) = None
    details: str | None = None
    mainline: bool | None = None
    continuation_anchor: str | None = None


class _Sequence:
    def __init__(
        self, key: str, initial_fen: str | None, binding: tuple[str, str] | None = None
    ) -> None:
        self.key = key
        self.binding = binding
        self.initial_position = (
            FenPosition(kind="fen", fen=initial_fen)
            if initial_fen is not None
            else StartPosition(kind="startpos")
        )
        self.nodes: list[MoveNode] = []
        self.annotations: list[SequenceAnnotation] = []
        self.flow: list[MoveFlowRef | AnnotationFlowRef] = []
        self.orders: dict[str | None, int] = defaultdict(int)
        self.mainline_flags: dict[str, bool] = {}

    def item(self, item_id: str) -> MoveSequenceItemV1_1:
        children: dict[str | None, list[MoveNode]] = defaultdict(list)
        for node in self.nodes:
            children[node.parent_id].append(node)
        for siblings in children.values():
            primary = next(
                (node for node in siblings if self.mainline_flags.get(node.id)),
                siblings[0],
            )
            for order, node in enumerate([primary, *(n for n in siblings if n is not primary)]):
                node.sibling_order = order
        refs = [ref for node in self.nodes for ref in node.evidence]
        refs.extend(ref for annotation in self.annotations for ref in annotation.evidence)
        return MoveSequenceItemV1_1(
            kind="move_sequence",
            id=item_id,
            evidence=refs,
            initial_position=self.initial_position,
            nodes=self.nodes,
            annotations=self.annotations,
            reading_flow=self.flow,
            extensions=(
                {
                    "chess-workbench.continuation": {
                        "base_normalized_ccef_sha256": self.binding[0],
                        "anchor_id": self.binding[1],
                    }
                }
                if self.binding is not None
                else {}
            ),
        )


def _on_valid_mainline(candidate: MoveNode, nodes: list[MoveNode]) -> bool:
    """An invalid sibling cannot displace the printed legal mainline."""
    by_id = {node.id: node for node in nodes}
    current = candidate
    while True:
        if current.parent_id is None:
            return True
        valid_siblings = [
            node
            for node in nodes
            if node.parent_id == current.parent_id and node.validation_status == "valid"
        ]
        if (
            not valid_siblings
            or min(valid_siblings, key=lambda node: node.sibling_order).id != current.id
        ):
            return False
        current = by_id[current.parent_id]


def _relink_unique_numbered_context(package: ExtractionPackageV1_1) -> bool:
    """Correct only a proven context mismatch with one legal preceding position.

    This is a local structural correction, not a second model repair pass. The
    original source binding stays attached and the correction is recorded.
    """
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        by_id = {node.id: node for node in item.nodes}
        relinked: set[str] = set()
        for node_index, node in enumerate(item.nodes):
            if (
                node.validation_status != "invalid"
                or node.parent_id is None
                or node.move_number is None
                or node.side_to_move is None
                or not any(
                    w.code in {"ccef_chess_context_mismatch", "ccef_chess_invalid_move"}
                    for w in node.warnings
                )
            ):
                continue
            parent = by_id[node.parent_id]
            if parent.fen_after is None:
                continue
            parent_board = chess.Board(parent.fen_after)
            if parent_board.fullmove_number == node.move_number and parent_board.turn == (
                node.side_to_move == "w"
            ):
                # The move before this invalid successor may belong to a
                # sibling branch. In Catalan p6, 3...Nf6 is legal after both
                # 3.g3 and 3.Nf3, but the printed 4.g3 is legal only after
                # 3.Nf3. Require one legal sibling and no other child before
                # moving that preceding node.
                predecessor = by_id.get(parent.parent_id) if parent.parent_id else None
                parent_children = [
                    candidate for candidate in item.nodes if candidate.parent_id == parent.id
                ]
                if (
                    predecessor is not None
                    and len(parent_children) == 1
                    and parent_children[0] is node
                    and any(w.code == "ccef_chess_invalid_move" for w in node.warnings)
                ):
                    parent_token = _clean_move_token(parent.move_text)
                    child_token = _clean_move_token(node.move_text)
                    alternatives = []
                    if parent_token is not None and child_token is not None:
                        for sibling in item.nodes[:node_index]:
                            if (
                                sibling.id == predecessor.id
                                or sibling.parent_id != predecessor.parent_id
                                or sibling.move_number != predecessor.move_number
                                or sibling.side_to_move != predecessor.side_to_move
                                or sibling.fen_after is None
                            ):
                                continue
                            board = chess.Board(sibling.fen_after)
                            try:
                                board.push_san(parent_token)
                                board.parse_san(child_token)
                            except ValueError:
                                continue
                            alternatives.append(sibling.id)
                    if len(alternatives) == 1:
                        parent.parent_id = alternatives[0]
                        relinked.add(parent.id)
                        parent.warnings.append(
                            ExtractionWarning(
                                code="source_parent_relinked",
                                message="Parent moved to the sole legal branch for its successor.",
                                evidence=parent.evidence,
                            )
                        )
                        package.diagnostics.append(
                            Diagnostic(
                                severity="warning",
                                code="source_parent_relinked",
                                message="Printed successor resolves a branch parent",
                                item_id=item.id,
                                node_id=parent.id,
                                evidence=parent.evidence,
                            )
                        )
                        changed = True
                continue
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            # A numbered alternative printed with the same turn as its
            # proposed parent is a sibling, provided that move is legal from
            # their shared predecessor. This stays local to the stated
            # relationship, even when the book contains other legal positions
            # with the same turn number.
            if parent.move_number == node.move_number and parent.side_to_move == node.side_to_move:
                parent_token = _clean_move_token(parent.move_text)
                if (
                    parent_token == token
                    and node.evidence
                    and parent.evidence
                    and node.evidence[0].page > parent.evidence[0].page
                ):
                    mainline_candidates = []
                    for candidate in item.nodes[:node_index]:
                        if candidate.fen_after is None or not _on_valid_mainline(
                            candidate, item.nodes
                        ):
                            continue
                        board = chess.Board(candidate.fen_after)
                        if board.fullmove_number != node.move_number or board.turn != (
                            node.side_to_move == "w"
                        ):
                            continue
                        try:
                            board.parse_san(token)
                        except ValueError:
                            continue
                        mainline_candidates.append(candidate.id)
                    if len(mainline_candidates) == 1:
                        node.parent_id = mainline_candidates[0]
                        relinked.add(node.id)
                        node.warnings.append(
                            ExtractionWarning(
                                code="source_parent_relinked",
                                message="Repeated cross-page move resumed the sole legal mainline.",
                                evidence=node.evidence,
                            )
                        )
                        package.diagnostics.append(
                            Diagnostic(
                                severity="warning",
                                code="source_parent_relinked",
                                message="Same-SAN cross-page mention kept in its mainline position",
                                item_id=item.id,
                                node_id=node.id,
                                evidence=node.evidence,
                            )
                        )
                        changed = True
                        continue
                predecessor = by_id.get(parent.parent_id) if parent.parent_id else None
                sibling_board = (
                    chess.Board(predecessor.fen_after)
                    if predecessor is not None and predecessor.fen_after is not None
                    else None
                )
                if (
                    sibling_board is not None
                    and sibling_board.fullmove_number == node.move_number
                    and sibling_board.turn == (node.side_to_move == "w")
                ):
                    try:
                        sibling_board.parse_san(token)
                    except ValueError:
                        pass
                    else:
                        node.parent_id = parent.parent_id
                        relinked.add(node.id)
                        node.warnings.append(
                            ExtractionWarning(
                                code="source_parent_relinked",
                                message="Numbered alternative attached beside its preceding move.",
                                evidence=node.evidence,
                            )
                        )
                        package.diagnostics.append(
                            Diagnostic(
                                severity="warning",
                                code="source_parent_relinked",
                                message="Numbered sibling corrected from model parent",
                                item_id=item.id,
                                node_id=node.id,
                                evidence=node.evidence,
                            )
                        )
                        changed = True
                        continue
            candidates: list[str | None] = []
            for predecessor in item.nodes[:node_index]:
                if predecessor.fen_after is None:
                    continue
                board = chess.Board(predecessor.fen_after)
                if board.fullmove_number != node.move_number or board.turn != (
                    node.side_to_move == "w"
                ):
                    continue
                try:
                    board.parse_san(token)
                except ValueError:
                    continue
                candidates.append(predecessor.id)
            initial_board = (
                chess.Board()
                if isinstance(item.initial_position, StartPosition)
                else chess.Board(item.initial_position.fen)
            )
            if initial_board.fullmove_number == node.move_number and initial_board.turn == (
                node.side_to_move == "w"
            ):
                try:
                    initial_board.parse_san(token)
                except ValueError:
                    pass
                else:
                    candidates.append(None)
            if len(candidates) != 1:
                continue
            node.parent_id = candidates[0]
            relinked.add(node.id)
            node.warnings.append(
                ExtractionWarning(
                    code="source_parent_relinked",
                    message="Parent corrected to the unique legal numbered position.",
                    evidence=node.evidence,
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_parent_relinked",
                    message="Move parent corrected from a conflicting model relationship",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=node.evidence,
                )
            )
            changed = True
        if relinked:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for node in item.nodes:
                children[node.parent_id].append(node)
            for siblings in children.values():
                ordered = sorted(
                    siblings,
                    key=lambda node: (node.id in relinked, node.sibling_order),
                )
                for order, sibling in enumerate(ordered):
                    sibling.sibling_order = order
    return changed


def _relink_colored_mainline_resumption(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """Resume a numbered mainline after a differently colored example score.

    Color alone never decides a chess relationship. A correction needs a turn
    mismatch at the proposed parent and exactly one legal, earlier mainline
    position printed in the resumed color.
    """
    colors = {
        entry.fragment.fragment_sha256: entry.fragment.font_color
        for page in context.pages
        for entry in page.fragments
    }
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        by_id = {node.id: node for node in item.nodes}
        relinked: set[str] = set()
        for index, node in enumerate(item.nodes):
            if (
                node.validation_status != "invalid"
                or node.parent_id is None
                or node.move_number is None
                or node.side_to_move is None
                or not node.evidence
            ):
                continue
            parent = by_id[node.parent_id]
            if not parent.evidence:
                continue
            current_color = colors.get(node.evidence[0].fragment_sha256 or "")
            parent_color = colors.get(parent.evidence[0].fragment_sha256 or "")
            if current_color is None or parent_color is None or current_color == parent_color:
                continue
            if parent.fen_after is not None:
                parent_board = chess.Board(parent.fen_after)
                if parent_board.fullmove_number == node.move_number and parent_board.turn == (
                    node.side_to_move == "w"
                ):
                    continue
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            candidates = []
            for predecessor in item.nodes[:index]:
                if (
                    predecessor.validation_status != "valid"
                    or predecessor.fen_after is None
                    or predecessor.sibling_order != 0
                    or not predecessor.evidence
                    or colors.get(predecessor.evidence[0].fragment_sha256 or "") != current_color
                ):
                    continue
                board = chess.Board(predecessor.fen_after)
                if board.fullmove_number != node.move_number or board.turn != (
                    node.side_to_move == "w"
                ):
                    continue
                try:
                    board.parse_san(token)
                except ValueError:
                    continue
                candidates.append(predecessor.id)
            if len(candidates) != 1:
                continue
            node.parent_id = candidates[0]
            relinked.add(node.id)
            node.warnings.append(
                ExtractionWarning(
                    code="source_parent_relinked",
                    message="Printed mainline resumed after a differently colored example.",
                    evidence=node.evidence,
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_parent_relinked",
                    message="Numbered move relinked to the sole legal same-color mainline",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=node.evidence,
                )
            )
            changed = True
        if relinked:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for child in item.nodes:
                children[child.parent_id].append(child)
            for siblings in children.values():
                for order, sibling in enumerate(
                    sorted(siblings, key=lambda value: (value.id in relinked, value.sibling_order))
                ):
                    sibling.sibling_order = order
    return changed


def _relink_nearest_numbered_context(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """Relink a printed move only when its source-scoped context is unique."""
    fragments = {
        entry.fragment.fragment_sha256: (page.physical_page, entry.order, entry.fragment)
        for page in context.pages
        for entry in page.fragments
    }
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        relinked: set[str] = set()
        for index, node in enumerate(item.nodes):
            if (
                node.validation_status != "invalid"
                or node.parent_id is None
                or not node.evidence
                or node.move_number is None
                or node.side_to_move is None
            ):
                continue
            ref = node.evidence[0]
            source = fragments.get(ref.fragment_sha256 or "")
            if source is None or ref.start_offset is None:
                continue
            page, order, fragment = source
            printed_number, printed_side = _printed_move_context(
                fragment.text, ref.start_offset, node.move_text
            )
            if printed_number != node.move_number or printed_side != node.side_to_move:
                continue
            current_place = (page, order, ref.start_offset)
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            candidates: list[tuple[tuple[int, int, int], MoveNode]] = []
            for predecessor in item.nodes[:index]:
                if (
                    predecessor.validation_status != "valid"
                    or predecessor.fen_after is None
                    or predecessor.sibling_order != 0
                    or not predecessor.evidence
                ):
                    continue
                previous_ref = predecessor.evidence[0]
                previous = fragments.get(previous_ref.fragment_sha256 or "")
                if (
                    previous is None
                    or previous[2].font_color is None
                    or previous[2].font_color != fragment.font_color
                ):
                    continue
                place = (previous[0], previous[1], previous_ref.start_offset or 0)
                if place >= current_place:
                    continue
                board = chess.Board(predecessor.fen_after)
                if board.fullmove_number != printed_number or board.turn != (printed_side == "w"):
                    continue
                try:
                    board.parse_san(token)
                except ValueError:
                    continue
                candidates.append((place, predecessor))
            # Source proximity does not establish the author's branch. If
            # several positions fit, keep the model relationship reviewable.
            if len(candidates) != 1:
                continue
            sole_candidate = candidates[0][1]
            if sole_candidate.id == node.parent_id:
                continue
            node.parent_id = sole_candidate.id
            relinked.add(node.id)
            node.warnings.append(
                ExtractionWarning(
                    code="source_parent_relinked",
                    message="Numbered move linked to its sole legal source-scoped position.",
                    evidence=node.evidence,
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_parent_relinked",
                    message="Unique source-scoped numbered context corrected the parent",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=node.evidence,
                )
            )
            changed = True
        if relinked:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for child in item.nodes:
                children[child.parent_id].append(child)
            for siblings in children.values():
                for order, sibling in enumerate(
                    sorted(siblings, key=lambda value: (value.id in relinked, value.sibling_order))
                ):
                    sibling.sibling_order = order
    return changed


def _separate_cross_page_same_san(
    package: ExtractionPackageV1_1,
) -> bool:
    """Keep a repeated move on a later page in its distinct mainline position."""
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        relinked: set[str] = set()

        for index, node in enumerate(item.nodes):
            if (
                node.validation_status != "valid"
                or node.parent_id is None
                or node.move_number is None
                or node.side_to_move is None
                or not node.evidence
            ):
                continue
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            repeated = any(
                prior.parent_id == node.parent_id
                and prior.evidence
                and prior.evidence[0].page < node.evidence[0].page
                and _clean_move_token(prior.move_text) == token
                for prior in item.nodes[:index]
            )
            if not repeated:
                continue
            candidates = []
            for predecessor in item.nodes[:index]:
                if predecessor.fen_after is None or not _on_valid_mainline(predecessor, item.nodes):
                    continue
                board = chess.Board(predecessor.fen_after)
                if board.fullmove_number != node.move_number or board.turn != (
                    node.side_to_move == "w"
                ):
                    continue
                try:
                    board.parse_san(token)
                except ValueError:
                    continue
                candidates.append(predecessor.id)
            if len(candidates) != 1 or candidates[0] == node.parent_id:
                continue
            node.parent_id = candidates[0]
            relinked.add(node.id)
            node.warnings.append(
                ExtractionWarning(
                    code="source_parent_relinked",
                    message="Repeated cross-page SAN kept in its distinct mainline position.",
                    evidence=node.evidence,
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_parent_relinked",
                    message="Cross-page same-SAN branch separated by legal mainline context",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=node.evidence,
                )
            )
            changed = True
        if relinked:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for child in item.nodes:
                children[child.parent_id].append(child)
            for siblings in children.values():
                for order, sibling in enumerate(
                    sorted(siblings, key=lambda value: (value.id in relinked, value.sibling_order))
                ):
                    sibling.sibling_order = order
    return changed


def _relink_standalone_mainline_reply(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """A later formal score row resumes an earlier standalone played move."""
    fragments = {
        entry.fragment.fragment_sha256: (page.physical_page, entry.order, entry.fragment.text)
        for page in context.pages
        for entry in page.fragments
    }
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        relinked: set[str] = set()
        for node in item.nodes:
            if node.validation_status != "valid" or not node.evidence:
                continue
            ref = node.evidence[0]
            source = fragments.get(ref.fragment_sha256 or "")
            if source is None or not source[2].lstrip().startswith(
                tuple(str(n) for n in range(1, 100))
            ):
                continue
            number, side = _printed_move_context(source[2], ref.start_offset or 0, node.move_text)
            token = _clean_move_token(node.move_text)
            if number is None or side is None or token is None:
                continue
            singleton_candidates = []
            for prior in item.nodes:
                if (
                    prior.id == node.id
                    or prior.validation_status != "valid"
                    or not prior.evidence
                    or prior.fen_after is None
                ):
                    continue
                prior_source = fragments.get(prior.evidence[0].fragment_sha256 or "")
                if (
                    prior_source is None
                    or prior_source[0] != source[0]
                    or prior_source[1] >= source[1]
                ):
                    continue
                prior_number, prior_side = _printed_move_context(
                    prior_source[2], prior.evidence[0].start_offset or 0, prior.move_text
                )
                if prior_number != number or prior_side == side:
                    continue
                if prior_source[2].strip() != prior.move_text.strip():
                    continue
                board = chess.Board(prior.fen_after)
                if board.fullmove_number != number or board.turn != (side == "w"):
                    continue
                try:
                    board.parse_san(token)
                except ValueError:
                    continue
                singleton_candidates.append(prior.id)
            if len(singleton_candidates) != 1 or singleton_candidates[0] == node.parent_id:
                continue
            node.parent_id = singleton_candidates[0]
            relinked.add(node.id)
            node.warnings.append(
                ExtractionWarning(
                    code="source_parent_relinked",
                    message="Later formal row resumed the standalone played move.",
                    evidence=node.evidence,
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_parent_relinked",
                    message="Formal reply reattached after intervening prose variation",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=node.evidence,
                )
            )
            changed = True
        if relinked:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for child in item.nodes:
                children[child.parent_id].append(child)
            for siblings in children.values():
                for order, sibling in enumerate(
                    sorted(siblings, key=lambda value: (value.id in relinked, value.sibling_order))
                ):
                    sibling.sibling_order = order
    return changed


def _relink_reply_after_sibling_list(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """Resume the printed mainline after an intervening same-turn alternative."""
    locations = {
        entry.fragment.fragment_sha256: (page.physical_page, entry.order)
        for page in context.pages
        for entry in page.fragments
    }
    scopes = {}
    for page in context.pages:
        depth = 0
        for entry in page.fragments:
            scopes[entry.fragment.fragment_sha256] = (depth, entry.fragment.text)
            for char in entry.fragment.text:
                depth = max(0, depth + (char == "(") - (char == ")"))

    def scope(node: MoveNode) -> int | None:
        if not node.evidence:
            return None
        ref = node.evidence[0]
        source = scopes.get(ref.fragment_sha256 or "")
        if source is None:
            return None
        depth, value = source
        for char in value[: ref.start_offset or 0]:
            depth = max(0, depth + (char == "(") - (char == ")"))
        return depth

    def location(node: MoveNode) -> tuple[int, int, int] | None:
        if not node.evidence:
            return None
        ref = node.evidence[0]
        place = locations.get(ref.fragment_sha256 or "")
        if place is None:
            return None
        return (*place, ref.start_offset or 0)

    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        item_changed = False
        by_id = {node.id: node for node in item.nodes}
        for node in item.nodes:
            if node.parent_id is None or node.validation_status != "valid":
                continue
            parent = by_id[node.parent_id]
            if parent.sibling_order == 0 or parent.parent_id is None:
                continue
            if node.move_number != parent.move_number or node.side_to_move == parent.side_to_move:
                continue
            siblings = [
                candidate
                for candidate in item.nodes
                if candidate.parent_id == parent.parent_id
                and candidate.move_number == parent.move_number
                and candidate.side_to_move == parent.side_to_move
            ]
            primary = next(
                (candidate for candidate in siblings if candidate.sibling_order == 0),
                None,
            )
            current, parent_place = location(node), location(parent)
            if (
                primary is None
                or primary.fen_after is None
                or current is None
                or parent_place is None
            ):
                continue
            # An additional choice printed between this proposed parent and
            # the reply ends that alternative. Without it, a reply may truly
            # belong to the alternative and must retain the model relationship.
            intervening = any(
                place is not None
                and place[0] == current[0]
                and parent_place < place < current
                and scope(sibling) == scope(parent)
                for sibling in siblings
                if sibling is not parent and sibling is not primary
                for place in [location(sibling)]
            )
            if not intervening:
                continue
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            board = chess.Board(primary.fen_after)
            if board.fullmove_number != node.move_number or board.turn != (
                node.side_to_move == "w"
            ):
                continue
            try:
                board.parse_san(token)
            except ValueError:
                continue
            # A later same-turn alternative was first placed beside this
            # reply by the numbered-move correction. Keep those siblings
            # together when the interrupted parent is corrected.
            related_replies = [
                candidate
                for candidate in item.nodes
                if candidate.parent_id == parent.id
                and candidate.move_number == node.move_number
                and candidate.side_to_move == node.side_to_move
            ]
            for reply in related_replies:
                reply_token = _clean_move_token(reply.move_text)
                if reply_token is None:
                    continue
                try:
                    board.parse_san(reply_token)
                except ValueError:
                    continue
                reply.parent_id = primary.id
                reply.warnings.append(
                    ExtractionWarning(
                        code="source_parent_relinked",
                        message="Reply resumed the printed mainline after sibling choices.",
                        evidence=reply.evidence,
                    )
                )
                package.diagnostics.append(
                    Diagnostic(
                        severity="warning",
                        code="source_parent_relinked",
                        message="Reply relinked after intervening sibling choice",
                        item_id=item.id,
                        node_id=reply.id,
                        evidence=reply.evidence,
                    )
                )
                changed = True
                item_changed = True
        if item_changed:
            children: dict[str | None, list[MoveNode]] = defaultdict(list)
            for child in item.nodes:
                children[child.parent_id].append(child)
            for siblings in children.values():
                for order, sibling in enumerate(
                    sorted(siblings, key=lambda value: value.sibling_order)
                ):
                    sibling.sibling_order = order
    return changed


def _rebind_unique_numbered_occurrence(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """Correct a repeated quote only when the parent fixes its printed turn."""
    fragments = {
        entry.fragment.fragment_sha256: entry.fragment.text
        for page in context.pages
        for entry in page.fragments
    }
    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        item_changed = False
        by_id = {node.id: node for node in item.nodes}
        for node in item.nodes:
            if node.validation_status == "valid" or node.parent_id is None:
                continue
            parent = by_id[node.parent_id]
            if parent.fen_after is None or len(node.evidence) != 1:
                continue
            ref = node.evidence[0]
            source = fragments.get(ref.fragment_sha256 or "")
            if source is None or ref.start_offset is None:
                continue
            board = chess.Board(parent.fen_after)
            current_number, current_side = _printed_move_context(
                source, ref.start_offset, node.move_text
            )
            expected_side: Literal["w", "b"] = "w" if board.turn else "b"
            if current_number == board.fullmove_number and current_side == expected_side:
                continue
            token = _clean_move_token(node.move_text)
            if token is None:
                continue
            try:
                board.parse_san(token)
            except ValueError:
                continue
            matches = []
            for match in re.finditer(re.escape(node.move_text), source):
                number, side = _printed_move_context(source, match.start(), node.move_text)
                if number == board.fullmove_number and side == expected_side:
                    matches.append(match)
            if len(matches) != 1 or matches[0].start() == ref.start_offset:
                continue
            ref.start_offset = matches[0].start()
            ref.end_offset = matches[0].end()
            node.move_number = board.fullmove_number
            node.side_to_move = expected_side
            node.warnings.append(
                ExtractionWarning(
                    code="source_occurrence_rebound",
                    message="Repeated quote rebound to its numbered source occurrence.",
                    evidence=[ref],
                )
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="source_occurrence_rebound",
                    message="Repeated source quote corrected using the verified parent turn",
                    item_id=item.id,
                    node_id=node.id,
                    evidence=[ref],
                )
            )
            changed = True
            item_changed = True
        if item_changed:
            item.evidence = [ref for node in item.nodes for ref in node.evidence]
            item.evidence.extend(
                ref for annotation in item.annotations for ref in annotation.evidence
            )
    return changed


def _collapse_duplicate_leaf_moves(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> bool:
    """Treat a repeated printed move as one chess edge with both source refs."""
    locations = {
        entry.fragment.fragment_sha256: (page.physical_page, entry.order)
        for page in context.pages
        for entry in page.fragments
    }
    page_entries = {page.physical_page: page.fragments for page in context.pages}

    def is_game_move(node: MoveNode) -> bool:
        for ref in node.evidence:
            place = locations.get(ref.fragment_sha256 or "")
            if place is None:
                continue
            page, order = place
            neighbors = page_entries[page][order : order + 2]
            if any("game move" in entry.fragment.text.lower() for entry in neighbors):
                return True
        return False

    changed = False
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        groups: dict[tuple[str | None, str], list[MoveNode]] = defaultdict(list)
        for node in item.nodes:
            if node.validation_status == "valid" and node.uci_candidate is not None:
                groups[(node.parent_id, node.uci_candidate)].append(node)
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            chosen = next((node for node in duplicates if is_game_move(node)), duplicates[0])
            removed = [node for node in duplicates if node is not chosen]
            removed_ids = {node.id for node in removed}
            positions = {node.id: index for index, node in enumerate(item.nodes)}
            if any(
                node.parent_id in removed_ids and positions[node.id] < positions[chosen.id]
                for node in item.nodes
            ):
                continue
            for node in item.nodes:
                if node.parent_id in removed_ids:
                    node.parent_id = chosen.id
            for annotation in item.annotations:
                if (
                    isinstance(annotation.anchor, MoveNodeAnnotationAnchor)
                    and annotation.anchor.node_id in removed_ids
                ):
                    annotation.anchor.node_id = chosen.id
            for prose in package.items:
                if (
                    isinstance(prose, ProseItem)
                    and isinstance(prose.anchor, MoveNodeAnchor)
                    and prose.anchor.sequence_id == item.id
                    and prose.anchor.node_id in removed_ids
                ):
                    prose.anchor.node_id = chosen.id
            for diagnostic in package.diagnostics:
                if diagnostic.item_id == item.id and diagnostic.node_id in removed_ids:
                    diagnostic.node_id = chosen.id
            chosen.evidence = sorted(
                [ref for node in duplicates for ref in node.evidence],
                key=lambda ref: (
                    *locations.get(ref.fragment_sha256 or "", (ref.page, 0)),
                    ref.start_offset or 0,
                ),
            )
            chosen.warnings.append(
                ExtractionWarning(
                    code="duplicate_move_mention_collapsed",
                    message="Repeated source mentions refer to one move from this position.",
                    evidence=chosen.evidence,
                )
            )
            item.nodes = [node for node in item.nodes if node.id not in removed_ids]
            item.reading_flow = [
                entry
                for entry in item.reading_flow
                if not isinstance(entry, MoveFlowRef) or entry.node_id not in removed_ids
            ]
            package.diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="duplicate_move_mention_collapsed",
                    message="Repeated printed move merged into one source-backed node",
                    item_id=item.id,
                    node_id=chosen.id,
                    evidence=chosen.evidence,
                )
            )
            changed = True
        siblings: dict[str | None, list[MoveNode]] = defaultdict(list)
        for node in item.nodes:
            siblings[node.parent_id].append(node)
        for group in siblings.values():
            selected = next((node for node in group if is_game_move(node)), None)
            if selected is None or selected.sibling_order == 0:
                ordered = sorted(group, key=lambda node: node.sibling_order)
            else:
                ordered = [
                    selected,
                    *(
                        node
                        for node in sorted(group, key=lambda node: node.sibling_order)
                        if node is not selected
                    ),
                ]
                selected.warnings.append(
                    ExtractionWarning(
                        code="source_mainline_inferred",
                        message="Printed game-move cue identifies this sibling as the mainline.",
                        evidence=selected.evidence,
                    )
                )
                changed = True
            for order, node in enumerate(ordered):
                node.sibling_order = order
        if changed:
            item.evidence = [ref for node in item.nodes for ref in node.evidence]
            item.evidence.extend(
                ref for annotation in item.annotations for ref in annotation.evidence
            )
    return changed


def _retain_reprinted_move_before_reply(
    package: ExtractionPackageV1_1, context: CcefPromptContext
) -> None:
    """Keep a repeated printed move when the model emits only its new reply."""
    fragments = {
        entry.fragment.fragment_sha256: entry.fragment.text
        for page in context.pages
        for entry in page.fragments
    }
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        by_id = {node.id: node for node in item.nodes}
        for node in item.nodes:
            if node.parent_id is None or node.validation_status != "valid":
                continue
            parent = by_id[node.parent_id]
            if parent.validation_status != "valid" or len(node.evidence) != 1:
                continue
            child_ref = node.evidence[0]
            source = fragments.get(child_ref.fragment_sha256 or "")
            if source is None or child_ref.start_offset is None:
                continue
            prefix = source[: child_ref.start_offset]
            match = re.fullmatch(r"\s*([1-9]\d{0,2})(\.{1,3})\s*(\S+)\s*", prefix)
            if match is None:
                continue
            printed_number = int(match.group(1))
            printed_side = "b" if match.group(2) == "..." else "w"
            if (
                parent.move_number != printed_number
                or parent.side_to_move != printed_side
                or _clean_move_token(match.group(3)) != _clean_move_token(parent.move_text)
                or any(
                    ref.fragment_sha256 == child_ref.fragment_sha256
                    and ref.start_offset == match.start(3)
                    for ref in parent.evidence
                )
            ):
                continue
            mention_ref = EvidenceRef(
                page=child_ref.page,
                bbox=child_ref.bbox,
                start_offset=match.start(1),
                end_offset=match.end(3),
                fragment_sha256=child_ref.fragment_sha256,
            )
            annotation = SequenceAnnotation(
                id=f"restatement_{node.id}",
                text=source[mention_ref.start_offset : mention_ref.end_offset],
                anchor=MoveNodeAnnotationAnchor(
                    kind="move_node", node_id=parent.id, relation="after"
                ),
                evidence=[mention_ref],
            )
            item.annotations.append(annotation)
            item.evidence.append(mention_ref)
            flow_index = next(
                (
                    index
                    for index, entry in enumerate(item.reading_flow)
                    if isinstance(entry, MoveFlowRef) and entry.node_id == node.id
                ),
                len(item.reading_flow),
            )
            item.reading_flow.insert(
                flow_index,
                AnnotationFlowRef(kind="annotation", annotation_id=annotation.id),
            )
            package.diagnostics.append(
                Diagnostic(
                    severity="info",
                    code="source_move_restatement_retained",
                    message="Repeated printed move retained before its reply",
                    item_id=item.id,
                    node_id=parent.id,
                    evidence=[mention_ref],
                )
            )


def compile_semantic_events(
    context: CcefPromptContext,
    raw_events: list[dict[str, Any]],
    *,
    sequence_initial_fens: dict[str, str | None] | None = None,
    sequence_bindings: dict[str, tuple[str, str]] | None = None,
    explicit_relationships: bool = False,
) -> ExtractionPackageV1_1:
    """Compile each proposed event independently against the trusted evidence snapshot.

    ``sequence_initial_fens`` belongs to the caller's confirmed context. A model
    cannot manufacture a board position by adding a field to its event.
    """
    fragments = {
        (page.physical_page, entry.order): entry.fragment
        for page in context.pages
        for entry in page.fragments
    }
    fragment_locations = {
        entry.fragment.fragment_sha256: (page.physical_page, entry.order)
        for page in context.pages
        for entry in page.fragments
    }
    diagram_seeds = find_diagram_seeds(context)
    sequence_initial_fens = sequence_initial_fens or {}
    sequence_bindings = sequence_bindings or {}
    sequences: dict[str, _Sequence] = {}
    sequence_aliases: dict[str, str] = {}
    root_groups: dict[tuple[str, int, int, str, int, str | None], str] = {}
    heading_epoch = 0
    event_nodes: dict[str, tuple[str, str]] = {}
    seen_events: set[str] = set()
    items: list[HeadingItem | ProseItem | MoveSequenceItemV1_1 | FigureItem | UnresolvedItem] = []
    pending_sequences: list[tuple[int, str]] = []
    diagnostics: list[Diagnostic] = []
    for page in context.pages:
        for entry in page.fragments:
            fragment = entry.fragment
            if fragment.origin != "diagram":
                continue
            try:
                marker = json.loads(fragment.text)
            except json.JSONDecodeError:
                continue
            if not isinstance(marker, dict) or marker.get("kind") != "chess_diagram":
                continue
            figure_ref = EvidenceRef(
                page=page.physical_page,
                bbox=[fragment.box.x0, fragment.box.y0, fragment.box.x1, fragment.box.y1],
                fragment_sha256=fragment.fragment_sha256,
            )
            fen = marker.get("operational_fen")
            items.append(
                FigureItem(
                    kind="figure",
                    id=f"figure{page.physical_page}_{entry.order}",
                    evidence=[figure_ref],
                    figure_type="chessboard",
                    position_fen_candidate=fen if isinstance(fen, str) else None,
                )
            )

    for index, raw in enumerate(raw_events):
        item_id = f"item{index + 1}"
        try:
            event = SemanticEvent.model_validate(raw)
            if event.id in seen_events:
                raise ValueError("duplicate semantic event id")
            seen_events.add(event.id)
            fragment = fragments[(event.source.page, event.source.order)]
            if fragment.origin == "diagram":
                # The trusted diagram marker already produced its figure item.
                # A model cannot reinterpret its machine-readable JSON as book text.
                continue
            if event.source.end > len(fragment.text) or event.source.start >= event.source.end:
                raise ValueError("source slice is outside the cited fragment")
            value = fragment.text[event.source.start : event.source.end]
            if not value.strip():
                raise ValueError("source slice is empty")
            ref = EvidenceRef(
                page=event.source.page,
                bbox=[fragment.box.x0, fragment.box.y0, fragment.box.x1, fragment.box.y1],
                start_offset=event.source.start,
                end_offset=event.source.end,
                fragment_sha256=fragment.fragment_sha256,
            )
            if event.kind == "heading":
                heading_epoch += 1
                items.append(
                    HeadingItem(
                        kind="heading",
                        id=item_id,
                        evidence=[ref],
                        text=value,
                        level=event.level or 1,
                    )
                )
            elif event.kind == "prose":
                items.append(ProseItem(kind="prose", id=item_id, evidence=[ref], text=value))
            elif event.kind == "unresolved":
                items.append(
                    UnresolvedItem(
                        kind="unresolved",
                        id=item_id,
                        evidence=[ref],
                        unresolved_type="text",
                        reason_code=event.issue_code or "semantic_uncertain",
                        raw_text=value,
                        details=event.details,
                    )
                )
            else:
                if event.kind == "annotation" and not event.sequence:
                    if event.anchor is None:
                        items.append(
                            ProseItem(kind="prose", id=item_id, evidence=[ref], text=value)
                        )
                        continue
                    anchor_node = event_nodes.get(event.anchor)
                    if anchor_node is None:
                        raise ValueError("annotation anchor is unknown")
                    sequence_key = anchor_node[0]
                else:
                    if not event.sequence:
                        raise ValueError("move has no sequence")
                    sequence_key = sequence_aliases.get(event.sequence, event.sequence)
                relation_id = event.parent if event.kind == "move" else event.anchor
                if not explicit_relationships and relation_id in event_nodes:
                    parent_sequence = event_nodes[relation_id][0]
                    if sequence_key != parent_sequence:
                        diagnostics.append(
                            Diagnostic(
                                severity="warning",
                                code="sequence_alias_corrected",
                                message=f"Event {index + 1} attached to its parent sequence",
                                evidence=[ref],
                            )
                        )
                        sequence_key = parent_sequence
                sequence = sequences.get(sequence_key)
                inferred_parent_id: str | None = None
                if (
                    not explicit_relationships
                    and sequence is None
                    and event.kind == "move"
                    and event.parent is None
                ):
                    printed_number, printed_side = _printed_move_context(
                        fragment.text, event.source.start, value
                    )
                    if printed_number == 1 and printed_side == "b":
                        token = _clean_move_token(value)
                        candidates: list[tuple[str, str]] = []
                        if token is not None:
                            for candidate_key, existing in sequences.items():
                                if not isinstance(existing.initial_position, StartPosition):
                                    continue
                                for prior in existing.nodes:
                                    if (
                                        prior.parent_id is not None
                                        or prior.move_number != 1
                                        or prior.side_to_move != "w"
                                        or any(
                                            node.parent_id == prior.id for node in existing.nodes
                                        )
                                        or prior.evidence[0].page != event.source.page
                                    ):
                                        continue
                                    board = chess.Board()
                                    prior_token = _clean_move_token(prior.move_text)
                                    if prior_token is None:
                                        continue
                                    try:
                                        board.push_san(prior_token)
                                        board.parse_san(token)
                                    except ValueError:
                                        continue
                                    candidates.append((candidate_key, prior.id))
                        if len(candidates) == 1:
                            assert event.sequence is not None
                            sequence_key, inferred_parent_id = candidates[0]
                            sequence_aliases[event.sequence] = sequence_key
                            sequence = sequences[sequence_key]
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    code="source_root_continuation",
                                    message="Unique open first move joined to printed black reply",
                                    evidence=[ref],
                                )
                            )
                is_new_sequence = sequence is None
                root_group: tuple[str, int, int, str, int, str | None] | None = None
                if sequence is None:
                    if event.kind != "move" or event.parent is not None:
                        raise ValueError("new sequence must start with a root move")
                    printed_number, printed_side = _printed_move_context(
                        fragment.text, event.source.start, value
                    )
                    initial_fen = sequence_initial_fens.get(sequence_key)
                    if initial_fen is None and printed_number is not None:
                        eligible = [
                            seed
                            for seed in diagram_seeds
                            if seed.move_number == printed_number
                            and seed.side_to_move == printed_side
                            and (seed.page, seed.order) <= (event.source.page, event.source.order)
                        ]
                        if eligible:
                            initial_fen = max(
                                eligible, key=lambda seed: (seed.page, seed.order)
                            ).fen
                    if printed_number is not None and printed_number > 1 and initial_fen is None:
                        raise _EventProblem(
                            "missing_initial_position",
                            "Printed later move has no confirmed starting position",
                        )
                    if (
                        initial_fen is not None
                        and printed_number is not None
                        and printed_side is not None
                    ):
                        root_group = (
                            initial_fen,
                            event.source.page,
                            printed_number,
                            printed_side,
                            heading_epoch,
                            sequence_bindings.get(sequence_key, ("", ""))[1] or None,
                        )
                        existing_key = root_groups.get(root_group)
                        if existing_key is not None and not explicit_relationships:
                            assert event.sequence is not None
                            sequence_aliases[event.sequence] = existing_key
                            sequence_key = existing_key
                            sequence = sequences[existing_key]
                            is_new_sequence = False
                            diagnostics.append(
                                Diagnostic(
                                    severity="warning",
                                    code="root_alternative_joined",
                                    message="Root alternatives from one confirmed position joined",
                                    evidence=[ref],
                                )
                            )
                    if sequence is None:
                        sequence = _Sequence(
                            sequence_key,
                            initial_fen,
                            sequence_bindings.get(sequence_key),
                        )
                if event.kind == "move":
                    parent_id: str | None = inferred_parent_id
                    if event.parent is not None:
                        parent = event_nodes.get(event.parent)
                        if parent is None or parent[0] != sequence_key:
                            raise ValueError("parent move is unknown in this sequence")
                        parent_id = parent[1]
                    node_id = f"move{index + 1}"
                    printed_number, printed_side = _printed_move_context(
                        fragment.text, event.source.start, value
                    )
                    sequence.nodes.append(
                        MoveNode(
                            id=node_id,
                            parent_id=parent_id,
                            sibling_order=sequence.orders[parent_id],
                            move_text=value,
                            nags=(
                                [nag] if (nag := source_punctuation_nag(value)) is not None else []
                            ),
                            move_number=printed_number,
                            side_to_move=printed_side,
                            evidence=[ref],
                        )
                    )
                    sequence.orders[parent_id] += 1
                    sequence.mainline_flags[node_id] = event.mainline is True
                    sequence.flow.append(MoveFlowRef(kind="move", node_id=node_id))
                    event_nodes[event.id] = (sequence_key, node_id)
                    if is_new_sequence:
                        sequences[sequence_key] = sequence
                        pending_sequences.append((len(items), sequence_key))
                        if root_group is not None:
                            root_groups[root_group] = sequence_key
                else:
                    anchor = None
                    if event.anchor is not None:
                        target = event_nodes.get(event.anchor)
                        if target is None or target[0] != sequence_key:
                            raise ValueError("annotation anchor is unknown in this sequence")
                        anchor = MoveNodeAnnotationAnchor(
                            kind="move_node", node_id=target[1], relation=event.relation or "after"
                        )
                    annotation_id = f"annotation{index + 1}"
                    sequence.annotations.append(
                        SequenceAnnotation(
                            id=annotation_id, text=value, anchor=anchor, evidence=[ref]
                        )
                    )
                    sequence.flow.append(
                        AnnotationFlowRef(kind="annotation", annotation_id=annotation_id)
                    )
        except (ValueError, KeyError) as error:
            # A parseable location preserves the exact local source for correction.
            ref = None
            value = None
            source = raw.get("source") if isinstance(raw, dict) else None
            try:
                source = SourceSlice.model_validate(source)
                fragment = fragments[(source.page, source.order)]
                if 0 <= source.start < source.end <= len(fragment.text):
                    value = fragment.text[source.start : source.end]
                    ref = EvidenceRef(
                        page=source.page,
                        bbox=[fragment.box.x0, fragment.box.y0, fragment.box.x1, fragment.box.y1],
                        start_offset=source.start,
                        end_offset=source.end,
                        fragment_sha256=fragment.fragment_sha256,
                    )
            except (ValueError, KeyError):
                pass
            reason_code = (
                error.code if isinstance(error, _EventProblem) else "semantic_event_invalid"
            )
            if ref is not None:
                items.append(
                    UnresolvedItem(
                        kind="unresolved",
                        id=item_id,
                        evidence=[ref],
                        unresolved_type="text",
                        reason_code=reason_code,
                        raw_text=value if value and value.strip() else None,
                        details=str(error)[:1000],
                    )
                )
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code=reason_code,
                    message=f"Event {index + 1}: {str(error)[:1000]}",
                    item_id=item_id if ref is not None else None,
                    evidence=[ref] if ref is not None else [],
                )
            )

    # Insert each sequence at its first source event, retaining unrelated item order.
    for ordinal, (position, key) in reversed(list(enumerate(pending_sequences, 1))):
        items.insert(position, sequences[key].item(f"sequence{ordinal}"))
    items.sort(
        key=lambda item: min(
            (
                *fragment_locations.get(ref.fragment_sha256 or "", (ref.page, 0)),
                ref.start_offset or 0,
            )
            for ref in item.evidence
        )
    )
    package = ExtractionPackageV1_1(
        schema_version=CCEF_VERSION_1_1,
        package_id=context.package_id,
        source=SourceDescriptor(
            source_ref=context.source_ref,
            media_type=context.media_type,
            language=context.language,
            page_range=PageRange(start_page=context.first_page, end_page=context.last_page),
        ),
        items=items,
        diagnostics=diagnostics,
        provenance=Provenance(
            created_at=context.created_at,
            adapter_name="chess-workbench-source-compiler",
            adapter_version="0.1",
        ),
    )
    normalized = normalize_chess_moves_v1_1(package)
    if explicit_relationships:
        return normalized
    relinkers = (
        lambda candidate: _rebind_unique_numbered_occurrence(candidate, context),
        _relink_unique_numbered_context,
        lambda candidate: _relink_reply_after_sibling_list(candidate, context),
        lambda candidate: _relink_colored_mainline_resumption(candidate, context),
        lambda candidate: _relink_nearest_numbered_context(candidate, context),
        _separate_cross_page_same_san,
        lambda candidate: _relink_standalone_mainline_reply(candidate, context),
    )
    while True:
        # Each rule reads validation and FEN from the current tree. Recompute
        # immediately after a change, including its descendants, before any
        # other rule chooses a parent using those values.
        for relink in relinkers:
            if relink(normalized):
                normalized = normalize_chess_moves_v1_1(normalized)
                break
        else:
            break
    if _collapse_duplicate_leaf_moves(normalized, context):
        normalized = normalize_chess_moves_v1_1(normalized)
    _retain_reprinted_move_before_reply(normalized, context)
    return normalized
