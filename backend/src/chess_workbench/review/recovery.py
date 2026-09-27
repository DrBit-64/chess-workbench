"""Replay saved source relations after a human reattaches an existing move.

The current review package owns all human edits. Replay only contributes new,
source-identified legal moves and retires unchanged resolved issue cards.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass

import chess

from chess_workbench.extraction.contracts import (
    EvidenceRef,
    ExtractionPackageV1_1,
    MoveFlowRef,
    MoveNode,
    MoveSequenceItemV1_1,
    UnresolvedItem,
)
from chess_workbench.extraction.notation import source_punctuation_nag
from chess_workbench.extraction.prompting import CcefPromptContext
from chess_workbench.extraction.relations import (
    AlternativeTo,
    BranchAfter,
    Continue,
    LineSegment,
    RelationPatchResponse,
    RelationResponse,
    RelationState,
    SourceToken,
    apply_relation_patches,
    apply_relations,
    compile_relations,
    localize_invalid_relation_subtrees,
    source_tokens,
)
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.review.editing import _reflow, _renumber_siblings


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    package: ExtractionPackageV1_1
    corrected_entries: list[str]
    added_moves: list[tuple[int, str, str, str]]
    retired_issue_count: int
    preserved_manual_moves: int
    conflicts: list[str]


def _key(evidence: EvidenceRef) -> tuple[int, str | None, int | None, int | None]:
    return (
        evidence.page,
        evidence.fragment_sha256,
        evidence.start_offset,
        evidence.end_offset,
    )


def _source_keys(context: CcefPromptContext) -> dict[str, tuple[int, str, int, int]]:
    fragments = {
        (page.physical_page, item.order): item.fragment.fragment_sha256
        for page in context.pages
        for item in page.fragments
    }
    return {
        token.id: (token.page, fragments[token.page, token.order], token.start, token.end)
        for token in source_tokens(context)
    }


def _exact_ref(
    node: MoveNode,
    by_evidence: dict[tuple[int, str, int, int], str],
) -> str | None:
    for evidence in node.evidence:
        page, digest, start, end = _key(evidence)
        if digest is not None and start is not None and end is not None:
            found = by_evidence.get((page, digest, start, end))
            if found is not None:
                return found
    return None


def _sequences(package: ExtractionPackageV1_1) -> dict[str, MoveSequenceItemV1_1]:
    return {item.id: item for item in package.items if isinstance(item, MoveSequenceItemV1_1)}


def _paths(sequence: MoveSequenceItemV1_1) -> dict[str, tuple[str | None, ...]]:
    nodes = {node.id: node for node in sequence.nodes}
    result: dict[str, tuple[str | None, ...]] = {}
    for node in sequence.nodes:
        path = []
        current: MoveNode | None = node
        while current is not None:
            path.append(current.uci_candidate)
            current = nodes.get(current.parent_id) if current.parent_id else None
        result[node.id] = tuple(reversed(path))
    return result


def _contains(outer: EvidenceRef, inner: EvidenceRef) -> bool:
    return (
        outer.page == inner.page
        and outer.fragment_sha256 is not None
        and outer.fragment_sha256 == inner.fragment_sha256
        and outer.start_offset is not None
        and outer.end_offset is not None
        and inner.start_offset is not None
        and inner.end_offset is not None
        and outer.start_offset <= inner.start_offset
        and inner.end_offset <= outer.end_offset
    )


def _same_source(left: MoveNode, right: MoveNode) -> bool:
    return any(_contains(a, b) or _contains(b, a) for a in left.evidence for b in right.evidence)


def _source_ref(
    node: MoveNode,
    by_evidence: dict[tuple[int, str, int, int], str],
    source_keys: dict[str, tuple[int, str, int, int]],
    tokens: dict[str, SourceToken],
) -> str | None:
    exact = _exact_ref(node, by_evidence)
    if exact is not None:
        return exact
    # Human conversion currently records the containing text span on each
    # move. Resolve only an unambiguous SAN occurrence in that span.
    candidates = []
    label = _score_label(node.san_candidate or node.move_text)
    for ref, (page, digest, start, end) in source_keys.items():
        token = tokens[ref]
        if _score_label(token.raw) != label:
            continue
        if (
            token.move_number is not None
            and node.move_number is not None
            and token.move_number != node.move_number
        ):
            continue
        if (
            token.side is not None
            and node.side_to_move is not None
            and token.side != node.side_to_move
        ):
            continue
        if any(
            e.page == page
            and (
                (
                    e.fragment_sha256 == digest
                    and e.start_offset is not None
                    and e.end_offset is not None
                    and e.start_offset <= start
                    and end <= e.end_offset
                )
                or e.fragment_sha256 is None
            )
            for e in node.evidence
        ):
            candidates.append(ref)
    return candidates[0] if len(candidates) == 1 else None


def _score_label(value: str) -> str:
    return re.sub(r"[!?+#\s]", "", value).replace("X", "x").lower()


def _relation_state(
    context: CcefPromptContext,
    responses: list[RelationResponse],
    owned_spans: list[set[str]],
    tokens: list[SourceToken],
) -> RelationState:
    state = RelationState()
    for response, owned in zip(responses, owned_spans, strict=True):
        apply_relations(context, response, tokens, owned, state)
    return state


def _segment_owner(
    responses: list[RelationResponse],
    owned_spans: list[set[str]],
    source_ref: str,
    tokens: dict[str, SourceToken],
) -> tuple[LineSegment, int] | None:
    token = tokens.get(source_ref)
    if token is None:
        return None
    for response, owned in zip(responses, owned_spans, strict=True):
        if token.span_ref not in owned:
            continue
        for segment in response.segments:
            if source_ref in segment.move_refs:
                return segment, segment.move_refs.index(source_ref)
    return None


def _split_mixed_mainline(
    responses: list[RelationResponse],
    segment: LineSegment,
    old_index: int,
    new_index: int,
    *,
    parent_ref: str,
    source_ref: str,
    line_ref: str,
    tokens: dict[str, SourceToken],
) -> list[RelationResponse] | None:
    """Separate a printed alternative embedded between a parent and its continuation."""
    if not 0 < old_index < new_index:
        return None
    alternative_ref = segment.move_refs[old_index]
    alternative = tokens.get(alternative_ref) if isinstance(alternative_ref, str) else None
    parent = tokens[parent_ref]
    if (
        alternative is None
        or alternative.move_number is None
        or alternative.side is None
        or alternative.move_number != parent.move_number
        or alternative.side != parent.side
    ):
        return None
    prefix = segment.model_copy(deep=True)
    prefix.move_refs = segment.move_refs[:old_index]
    variation = segment.model_copy(deep=True)
    variation.id = f"review-variation-{alternative.id}"
    variation.line_ref = variation.id
    variation.entry = AlternativeTo(
        kind="alternative_to", target_line_ref=line_ref, target_move_ref=parent_ref
    )
    variation.move_refs = segment.move_refs[old_index:new_index]
    continuation = segment.model_copy(deep=True)
    continuation.id = f"review-resume-{source_ref}"
    continuation.line_ref = line_ref
    continuation.entry = Continue(kind="continue", after_move_ref=parent_ref)
    continuation.move_refs = segment.move_refs[new_index:]
    patch = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "replacements": [
                {
                    "segment_id": segment.id,
                    "segments": [
                        prefix.model_dump(mode="json"),
                        variation.model_dump(mode="json"),
                        continuation.model_dump(mode="json"),
                    ],
                    "source_refs": list(dict.fromkeys([*segment.evidence_refs, parent.span_ref])),
                }
            ],
        }
    )
    return apply_relation_patches(responses, patch)


def _change_segment(
    responses: list[RelationResponse],
    segment: LineSegment,
    index: int,
    *,
    line_ref: str,
    entry: Continue | AlternativeTo | BranchAfter,
    source_ref: str,
    parent_span_ref: str,
) -> list[RelationResponse]:
    citations = list(dict.fromkeys([*segment.evidence_refs, parent_span_ref]))
    if index == 0:
        patch = RelationPatchResponse.model_validate(
            {
                "schema_version": "chess-source-relation-patch/1",
                "patches": [
                    {
                        "segment_id": segment.id,
                        "line_ref": line_ref,
                        "entry": entry.model_dump(mode="json"),
                        "source_refs": citations,
                    }
                ],
            }
        )
    else:
        prefix = segment.model_copy(deep=True)
        prefix.move_refs = segment.move_refs[:index]
        suffix = segment.model_copy(deep=True)
        suffix.id = f"review-resume-{source_ref}"
        suffix.line_ref = line_ref
        suffix.entry = entry
        suffix.move_refs = segment.move_refs[index:]
        patch = RelationPatchResponse.model_validate(
            {
                "schema_version": "chess-source-relation-patch/1",
                "patches": [],
                "replacements": [
                    {
                        "segment_id": segment.id,
                        "segments": [
                            prefix.model_dump(mode="json"),
                            suffix.model_dump(mode="json"),
                        ],
                        "source_refs": citations,
                    }
                ],
            }
        )
    return apply_relation_patches(responses, patch)


def _human_patches(
    context: CcefPromptContext,
    responses: list[RelationResponse],
    owned_spans: list[set[str]],
    baseline: ExtractionPackageV1_1,
    current: ExtractionPackageV1_1,
    human_node_ids: set[str],
    mainline_node_ids: set[str],
    human_added_ids: set[str],
) -> tuple[list[RelationResponse], list[str], list[str]]:
    source_keys = _source_keys(context)
    by_evidence = {key: ref for ref, key in source_keys.items()}
    token_list = source_tokens(context)
    tokens = {token.id: token for token in token_list}
    originals = _sequences(baseline)
    current_sequences = _sequences(current)
    actions: list[tuple[int, MoveSequenceItemV1_1, MoveNode]] = []
    for sequence_id, sequence in current_sequences.items():
        previous = {node.id: node for node in originals.get(sequence_id, sequence).nodes}
        paths = _paths(sequence)
        for node in sequence.nodes:
            before = previous.get(node.id)
            if (
                node.id in human_node_ids
                or node.id in mainline_node_ids
                or node.id in human_added_ids
                or (before is not None and before.parent_id != node.parent_id)
            ):
                actions.append((len(paths[node.id]), sequence, node))
    actions.sort(key=lambda action: action[0])
    working = responses
    corrected: list[str] = []
    skipped: list[str] = []
    for _, sequence, node in actions:
        nodes = {candidate.id: candidate for candidate in sequence.nodes}
        parent = nodes.get(node.parent_id) if node.parent_id else None
        if parent is None:
            skipped.append(f"{node.move_text}: no source-backed parent")
            continue
        source_ref = _source_ref(node, by_evidence, source_keys, tokens)
        parent_ref = _source_ref(parent, by_evidence, source_keys, tokens)
        if source_ref is None or parent_ref is None:
            skipped.append(f"{node.move_text}: source occurrence is not unique")
            continue
        state = _relation_state(context, working, owned_spans, token_list)
        location = state.token_line.get(parent_ref)
        if location is None:
            skipped.append(f"{node.move_text}: parent source is not assembled")
            continue
        game, line = location
        owner = _segment_owner(working, owned_spans, source_ref, tokens)
        if owner is None:
            if node.id not in human_added_ids:
                skipped.append(f"{node.move_text}: source is absent from saved move relations")
                continue
            owners = [
                index
                for index, owned in enumerate(owned_spans)
                if tokens[source_ref].span_ref in owned
            ]
            if len(owners) != 1:
                skipped.append(f"{node.move_text}: source window is not unique")
                continue
            selected_main = node.sibling_order == 0
            if selected_main and state.lines[location][2] != parent_ref:
                # A printed example can repeat the last mainline move and
                # then occupy the saved line tail, blocking the actual next
                # move. Keep the example as its own cited branch.
                direct_child = next(
                    (
                        ref
                        for ref, previous_parent in state.parent.items()
                        if previous_parent == parent_ref
                        and state.token_line.get(ref) == location
                        and ref != source_ref
                    ),
                    None,
                )
                repeated = tokens.get(direct_child) if direct_child else None
                grandparent_ref = state.parent.get(parent_ref)
                displaced = (
                    _segment_owner(working, owned_spans, direct_child, tokens)
                    if direct_child
                    else None
                )
                if repeated is None or displaced is None or displaced[1] != 0:
                    skipped.append(f"{node.move_text}: existing mainline blocks new entry")
                    continue
                if (
                    grandparent_ref is not None
                    and repeated.move_number == tokens[parent_ref].move_number
                    and repeated.side == tokens[parent_ref].side
                    and _score_label(repeated.raw) == _score_label(tokens[parent_ref].raw)
                ):
                    # A restated move starts a separate printed example.
                    working = _change_segment(
                        working,
                        displaced[0],
                        0,
                        line_ref=f"review-example-{direct_child}",
                        entry=BranchAfter(
                            kind="branch_after",
                            target_line_ref=line,
                            target_move_ref=grandparent_ref,
                        ),
                        source_ref=repeated.id,
                        parent_span_ref=tokens[parent_ref].span_ref,
                    )
                elif (
                    node.move_number is not None
                    and node.side_to_move is not None
                    and repeated.move_number
                    == node.move_number + (1 if node.side_to_move == "b" else 0)
                    and repeated.side != node.side_to_move
                    and (repeated.page, repeated.order, repeated.start)
                    > (tokens[source_ref].page, tokens[source_ref].order, tokens[source_ref].start)
                ):
                    # The saved continuation already follows the missing move.
                    # Reanchor that one entry to the human-confirmed source.
                    working = _change_segment(
                        working,
                        displaced[0],
                        0,
                        line_ref=line,
                        entry=Continue(kind="continue", after_move_ref=source_ref),
                        source_ref=repeated.id,
                        parent_span_ref=tokens[source_ref].span_ref,
                    )
                else:
                    skipped.append(f"{node.move_text}: existing mainline blocks new entry")
                    continue
                state = _relation_state(context, working, owned_spans, token_list)
                if state.lines[location][2] != parent_ref:
                    skipped.append(f"{node.move_text}: mainline still blocks new entry")
                    continue
            new_entry: Continue | AlternativeTo | BranchAfter = (
                Continue(kind="continue", after_move_ref=parent_ref)
                if selected_main
                else BranchAfter(
                    kind="branch_after", target_line_ref=line, target_move_ref=parent_ref
                )
            )
            new_line = line if selected_main else f"review-variation-{source_ref}"
            working = [response.model_copy(deep=True) for response in working]
            working[owners[0]].segments.append(
                LineSegment(
                    id=f"review-add-{source_ref}",
                    game_ref=game,
                    line_ref=new_line,
                    entry=new_entry,
                    move_refs=[source_ref],
                    evidence_refs=list(
                        dict.fromkeys([tokens[source_ref].span_ref, tokens[parent_ref].span_ref])
                    ),
                )
            )
            corrected.append(f"{node.move_text} → {parent.move_text}")
            continue
        segment, index = owner
        if segment.game_ref != game:
            skipped.append(f"{node.move_text}: game differs from parent")
            continue
        current_parent = state.parent.get(source_ref)
        current_line = state.token_line.get(source_ref)
        selected_main = node.sibling_order == 0
        if current_parent == parent_ref and (not selected_main or current_line == location):
            continue
        if selected_main:
            # A promoted child displaces the former continuation at this
            # position. Demote that old segment before resuming the saved line.
            existing = next(
                (
                    ref
                    for ref, previous_parent in state.parent.items()
                    if previous_parent == parent_ref
                    and state.token_line.get(ref) == location
                    and ref != source_ref
                ),
                None,
            )
            if existing is not None:
                displaced = _segment_owner(working, owned_spans, existing, tokens)
                if displaced is not None and displaced[0].id == segment.id:
                    split = _split_mixed_mainline(
                        working,
                        segment,
                        displaced[1],
                        index,
                        parent_ref=parent_ref,
                        source_ref=source_ref,
                        line_ref=line,
                        tokens=tokens,
                    )
                    if split is not None:
                        working = split
                        corrected.append(f"{node.move_text} → {parent.move_text}")
                        continue
                if displaced is None or displaced[0].id == segment.id:
                    skipped.append(f"{node.move_text}: existing mainline cannot be split")
                    continue
                old_segment, old_index = displaced
                variation_line = (
                    old_segment.line_ref
                    if old_segment.line_ref != line
                    else f"review-variation-{existing}"
                )
                working = _change_segment(
                    working,
                    old_segment,
                    old_index,
                    line_ref=variation_line,
                    entry=AlternativeTo(
                        kind="alternative_to",
                        target_line_ref=line,
                        target_move_ref=source_ref,
                    ),
                    source_ref=existing,
                    parent_span_ref=tokens[source_ref].span_ref,
                )
                segment, index = _segment_owner(working, owned_spans, source_ref, tokens) or (
                    segment,
                    index,
                )
            entry: Continue | AlternativeTo | BranchAfter = Continue(
                kind="continue", after_move_ref=parent_ref
            )
            requested_line = segment.line_ref if index == 0 else line
        else:
            entry = BranchAfter(
                kind="branch_after", target_line_ref=line, target_move_ref=parent_ref
            )
            requested_line = (
                segment.line_ref if segment.line_ref != line else f"review-variation-{source_ref}"
            )
        working = _change_segment(
            working,
            segment,
            index,
            line_ref=requested_line,
            entry=entry,
            source_ref=source_ref,
            parent_span_ref=tokens[parent_ref].span_ref,
        )
        corrected.append(f"{node.move_text} → {parent.move_text}")
    return working, corrected, skipped


def _recover_styled_continuation(
    context: CcefPromptContext,
    responses: list[RelationResponse],
    package: ExtractionPackageV1_1,
    human_ids: set[str],
    source_keys: dict[str, tuple[int, str, int, int]],
    added: list[tuple[int, str, str, str]],
    represented_sources: set[tuple[int, str | None, int | None, int | None]],
    conflicts: list[str],
) -> None:
    """Continue a confirmed mainline when score and variation styles are distinct.

    Style is learned from the reviewed game's own source moves. Legal SAN,
    printed move numbers and exact citations are still required; an unclear
    style or conflicting human node stops the continuation.
    """
    if not human_ids:
        return
    tokens = source_tokens(context)
    token_by_id = {token.id: token for token in tokens}
    by_evidence = {key: ref for ref, key in source_keys.items()}
    fragments = {
        (page.physical_page, fragment.order): fragment.fragment
        for page in context.pages
        for fragment in page.fragments
    }

    def style(ref: str) -> str | None:
        token = token_by_id[ref]
        fragment = fragments[token.page, token.order]
        run = next(
            (part for part in fragment.style_runs if part.start <= token.start < part.end),
            None,
        )
        return run.color if run is not None and run.bold else None

    def primary(sequence: MoveSequenceItemV1_1, node: MoveNode) -> bool:
        by_id = {candidate.id: candidate for candidate in sequence.nodes}
        current: MoveNode | None = node
        while current is not None:
            if current.sibling_order != 0:
                return False
            current = by_id.get(current.parent_id) if current.parent_id else None
        return True

    for sequence in _sequences(package).values():
        source_nodes = {
            node.id: _source_ref(node, by_evidence, source_keys, token_by_id)
            for node in sequence.nodes
        }
        known = Counter(
            color
            for node in sequence.nodes
            if primary(sequence, node)
            and (ref := source_nodes[node.id]) is not None
            and (color := style(ref)) is not None
        )
        if not known:
            continue
        main_color, count = known.most_common(1)[0]
        if count < 8 or count * 4 < sum(known.values()) * 3:
            continue
        anchors = [
            (token_by_id[ref], node)
            for node in sequence.nodes
            if node.id in human_ids
            and primary(sequence, node)
            and (ref := source_nodes[node.id]) is not None
            and style(ref) == main_color
            and node.fen_after is not None
        ]
        if not anchors:
            continue
        anchor, anchor_node = min(
            anchors, key=lambda value: (value[0].page, value[0].order, value[0].start)
        )
        anchor_position = (anchor.page, anchor.order, anchor.start)
        game_starts: dict[str, tuple[int, int]] = {}
        for response in responses:
            for game in response.games:
                if game.kind != "game":
                    continue
                for source_ref in game.source_refs:
                    match = re.fullmatch(r"s(\d+)_(\d+)", source_ref)
                    if match is None:
                        continue
                    position = (int(match.group(1)), int(match.group(2)))
                    previous = game_starts.get(game.id)
                    if previous is None or position < previous:
                        game_starts[game.id] = position
        start = max(
            (position for position in game_starts.values() if position <= anchor_position[:2]),
            default=(context.first_page, 0),
        )
        end = min(
            (position for position in game_starts.values() if position > anchor_position[:2]),
            default=(context.last_page + 1, 0),
        )

        following = [
            token
            for token in tokens
            if start <= (token.page, token.order) < end
            and (token.page, token.order, token.start) > anchor_position
        ]
        # Without a contrasting printed score style, color alone gives no
        # evidence that a later legal move belongs to the played line.
        contrasting = sum(
            token.move_number is not None and style(token.id) not in (None, main_color)
            for token in following
        )
        if contrasting < 3:
            continue
        board = chess.Board(anchor_node.fen_after)
        parent_id = anchor_node.id
        inserted = False
        for token in following:
            if style(token.id) != main_color:
                continue
            fragment = fragments[token.page, token.order]
            same_span = [t for t in tokens if t.span_ref == token.span_ref]
            if (
                token.move_number is None
                and not any(t.move_number is not None for t in same_span)
                and fragment.text.strip() != token.raw
            ):
                continue
            if token.move_number is not None and token.move_number != board.fullmove_number:
                continue
            if token.side is not None and token.side != ("w" if board.turn else "b"):
                continue
            san = re.sub(r"[!?]+$", "", token.raw.replace("X", "x"))
            try:
                move = board.parse_san(san)
            except ValueError:
                continue
            evidence = EvidenceRef(
                page=token.page,
                fragment_sha256=source_keys[token.id][1],
                start_offset=token.start,
                end_offset=token.end,
            )
            existing = [node for node in sequence.nodes if source_nodes.get(node.id) == token.id]
            if len(existing) > 1 or (
                existing
                and (existing[0].parent_id != parent_id or existing[0].uci_candidate != move.uci())
            ):
                conflicts.append(f"{token.raw}: styled source conflicts with reviewed line")
                break
            if existing:
                child = existing[0]
                if child.sibling_order != 0:
                    siblings = [
                        node
                        for node in sequence.nodes
                        if node.parent_id == parent_id and node.sibling_order == 0
                    ]
                    if any(node.id in human_ids for node in siblings):
                        conflicts.append(f"{token.raw}: human mainline takes precedence")
                        break
                    for sibling in siblings:
                        sibling.sibling_order = child.sibling_order
                    child.sibling_order = 0
            else:
                siblings = [node for node in sequence.nodes if node.parent_id == parent_id]
                if any(node.id in human_ids and node.sibling_order == 0 for node in siblings):
                    conflicts.append(f"{token.raw}: human mainline takes precedence")
                    break
                used_ids = {node.id for node in sequence.nodes}
                serial = 1
                while f"recovered-{serial}" in used_ids:
                    serial += 1
                for sibling in siblings:
                    sibling.sibling_order += 1
                fen_before = board.fen(en_passant="fen")
                canonical_san = board.san(move)
                board.push(move)
                child = MoveNode(
                    id=f"recovered-{serial}",
                    parent_id=parent_id,
                    sibling_order=0,
                    move_text=canonical_san,
                    nags=([nag] if (nag := source_punctuation_nag(token.raw)) is not None else []),
                    move_number=token.move_number,
                    side_to_move=token.side,
                    san_candidate=canonical_san,
                    uci_candidate=move.uci(),
                    validation_status="valid",
                    fen_before=fen_before,
                    fen_after=board.fen(en_passant="fen"),
                    evidence=[evidence],
                )
                sequence.nodes.append(child)
                sequence.reading_flow.append(MoveFlowRef(kind="move", node_id=child.id))
                if evidence not in sequence.evidence:
                    sequence.evidence.append(evidence)
                source_nodes[child.id] = token.id
                represented_sources.add(_key(evidence))
                added.append((token.page, child.move_text, sequence.id, child.id))
                inserted = True
                parent_id = child.id
                continue
            board.push(move)
            parent_id = child.id
        if inserted:
            _renumber_siblings(sequence)
            _reflow(sequence)
        # A contrasting, bold score span is a candidate variation. Locate its
        # starting ply on the confirmed played line; repeated opening moves
        # may be traversed, but only a differing legal move creates a branch.
        played: list[MoveNode] = []
        selected_parent: str | None = None
        while True:
            played_child = next(
                (
                    node
                    for node in sequence.nodes
                    if node.parent_id == selected_parent and node.sibling_order == 0
                ),
                None,
            )
            if played_child is None:
                break
            played.append(played_child)
            selected_parent = played_child.id
        main_by_ply: dict[tuple[int, str], MoveNode] = {}
        for node in played:
            if node.fen_before is None:
                continue
            before = chess.Board(node.fen_before)
            main_by_ply[(before.fullmove_number, "w" if before.turn else "b")] = node
        by_span: dict[str, list[SourceToken]] = {}
        for token in tokens:
            if start <= (token.page, token.order) < end:
                by_span.setdefault(token.span_ref, []).append(token)
        active_board: chess.Board | None = None
        active_parent: str | None = None
        active_color: str | None = None
        previous_position: tuple[int, int] | None = None
        variation_added = False
        for page in context.pages:
            for fragment_entry in page.fragments:
                position = (page.physical_page, fragment_entry.order)
                if not start <= position < end:
                    continue
                span_ref = f"s{page.physical_page}_{fragment_entry.order}"
                span_tokens = by_span.get(span_ref, [])
                colors = {style(token.id) for token in span_tokens}
                colors.discard(None)
                colors.discard(main_color)
                if len(colors) != 1 or any(style(token.id) == main_color for token in span_tokens):
                    active_board = None
                    previous_position = None
                    continue
                color = next(iter(colors))
                selected = [token for token in span_tokens if style(token.id) == color]
                if not selected:
                    continue
                first = selected[0]
                if first.move_number is not None and first.side is not None:
                    target = main_by_ply.get((first.move_number, first.side))
                    if target is None or target.fen_before is None:
                        active_board = None
                        continue
                    active_board = chess.Board(target.fen_before)
                    active_parent = target.parent_id
                elif not (
                    active_board is not None
                    and active_color == color
                    and previous_position is not None
                    and position[0] == previous_position[0]
                    and position[1] == previous_position[1] + 1
                ):
                    active_board = None
                    continue
                active_color = color
                previous_position = position
                assert active_board is not None
                for token in selected:
                    if (
                        token.move_number is not None
                        and token.move_number != active_board.fullmove_number
                    ):
                        active_board = None
                        break
                    if token.side is not None and token.side != ("w" if active_board.turn else "b"):
                        active_board = None
                        break
                    notation = re.sub(r"[!?]+$", "", token.raw.replace("X", "x"))
                    try:
                        move = active_board.parse_san(notation)
                    except ValueError:
                        active_board = None
                        break
                    known_nodes = [
                        node for node in sequence.nodes if source_nodes.get(node.id) == token.id
                    ]
                    if known_nodes:
                        if (
                            len(known_nodes) != 1
                            or known_nodes[0].parent_id != active_parent
                            or known_nodes[0].uci_candidate != move.uci()
                        ):
                            active_board = None
                            break
                        child = known_nodes[0]
                    else:
                        children = [
                            node for node in sequence.nodes if node.parent_id == active_parent
                        ]
                        repeated = next(
                            (
                                node
                                for node in children
                                if node.sibling_order == 0 and node.uci_candidate == move.uci()
                            ),
                            None,
                        )
                        if repeated is not None:
                            # The book repeats a played prefix inside an example.
                            child = repeated
                        else:
                            used_ids = {node.id for node in sequence.nodes}
                            serial = 1
                            while f"recovered-{serial}" in used_ids:
                                serial += 1
                            fen_before = active_board.fen(en_passant="fen")
                            canonical_san = active_board.san(move)
                            active_board.push(move)
                            evidence = EvidenceRef(
                                page=token.page,
                                fragment_sha256=source_keys[token.id][1],
                                start_offset=token.start,
                                end_offset=token.end,
                            )
                            child = MoveNode(
                                id=f"recovered-{serial}",
                                parent_id=active_parent,
                                sibling_order=len(children),
                                move_text=canonical_san,
                                nags=(
                                    [nag]
                                    if (nag := source_punctuation_nag(token.raw)) is not None
                                    else []
                                ),
                                move_number=token.move_number,
                                side_to_move=token.side,
                                san_candidate=canonical_san,
                                uci_candidate=move.uci(),
                                validation_status="valid",
                                fen_before=fen_before,
                                fen_after=active_board.fen(en_passant="fen"),
                                evidence=[evidence],
                            )
                            sequence.nodes.append(child)
                            sequence.reading_flow.append(MoveFlowRef(kind="move", node_id=child.id))
                            if evidence not in sequence.evidence:
                                sequence.evidence.append(evidence)
                            source_nodes[child.id] = token.id
                            represented_sources.add(_key(evidence))
                            added.append((token.page, child.move_text, sequence.id, child.id))
                            variation_added = True
                            active_parent = child.id
                            continue
                    active_board.push(move)
                    active_parent = child.id
        if variation_added:
            _renumber_siblings(sequence)
            _reflow(sequence)


def _human_additions_follow_one_mainline(
    package: ExtractionPackageV1_1, added_ids: set[str]
) -> bool:
    """Use automatic style continuation only for a coherent reviewed path."""
    if not added_ids:
        return True
    found: set[str] = set()
    sequences: set[str] = set()
    for sequence in _sequences(package).values():
        by_id = {node.id: node for node in sequence.nodes}
        for node_id in added_ids & by_id.keys():
            found.add(node_id)
            sequences.add(sequence.id)
            current: MoveNode | None = by_id[node_id]
            while current is not None:
                if current.sibling_order != 0:
                    return False
                current = by_id.get(current.parent_id) if current.parent_id else None
    return found == added_ids and len(sequences) == 1


def recover_dependencies(
    context: CcefPromptContext,
    responses: list[RelationResponse],
    owned_spans: list[set[str]],
    baseline: ExtractionPackageV1_1,
    current: ExtractionPackageV1_1,
    *,
    human_node_ids: set[str] | None = None,
    mainline_node_ids: set[str] | None = None,
    human_added_ids: set[str] | None = None,
) -> RecoveryResult:
    """Generate a preview without modifying the ledger or current package."""
    if len(responses) != len(owned_spans):
        raise ValueError("saved relation windows and ownership do not match")
    tokens = source_tokens(context)
    source_keys = _source_keys(context)
    by_source_evidence = {key: ref for ref, key in source_keys.items()}
    token_by_id = {token.id: token for token in tokens}
    # A reviewed variation can have a different visual style from the played
    # line. In that case replay explicit edits, but do not extrapolate one
    # primary style across the user's manually curated branches.
    coherent_added_line = _human_additions_follow_one_mainline(current, human_added_ids or set())
    line_added_ids = (human_added_ids or set()) if coherent_added_line else set()
    changed, corrected, skipped = _human_patches(
        context,
        responses,
        owned_spans,
        baseline,
        current,
        human_node_ids or set(),
        mainline_node_ids or set(),
        line_added_ids,
    )
    if not corrected:
        raise ValueError(
            "no new source-backed human relation could be replayed: " + "; ".join(skipped[:3])
        )
    replay = _relation_state(context, changed, owned_spans, tokens)
    candidate = compile_relations(context, replay)
    candidate = localize_invalid_relation_subtrees(context, replay, candidate)
    merged = copy.deepcopy(current)
    originals = _sequences(current)
    merged_sequences = _sequences(merged)
    added: list[tuple[int, str, str, str]] = []
    conflicts: list[str] = list(skipped)
    preserved_manual = sum(
        1
        for sequence_id, sequence in originals.items()
        for node in sequence.nodes
        if node.id not in {old.id for old in _sequences(baseline).get(sequence_id, sequence).nodes}
    )
    if human_added_ids is not None:
        preserved_manual = sum(
            node.id in human_added_ids for sequence in originals.values() for node in sequence.nodes
        )
    represented_sources: set[tuple[int, str | None, int | None, int | None]] = set()
    for proposal in _sequences(candidate).values():
        target = merged_sequences.get(proposal.id)
        if target is None or target.initial_position != proposal.initial_position:
            conflicts.append(f"{proposal.id}: sequence start changed; replay skipped")
            continue
        original = originals[proposal.id]
        paths = _paths(original)
        proposed_paths = _paths(proposal)
        matched: dict[str, str] = {}
        used_current: set[str] = set()
        # Match the full line and the exact source occurrence, even when a
        # manual conversion used a wider fragment as its evidence.
        for node in proposal.nodes:
            matches = [
                existing
                for existing in original.nodes
                if existing.id not in used_current
                and existing.validation_status == "valid"
                and node.validation_status == "valid"
                and paths[existing.id] == proposed_paths[node.id]
                and (
                    _same_source(existing, node)
                    or (
                        (
                            existing_ref := _source_ref(
                                existing, by_source_evidence, source_keys, token_by_id
                            )
                        )
                        is not None
                        and existing_ref
                        == _source_ref(node, by_source_evidence, source_keys, token_by_id)
                    )
                )
            ]
            if len(matches) == 1:
                matched[node.id] = matches[0].id
                used_current.add(matches[0].id)
                represented_sources.update(_key(e) for e in node.evidence)
        pending = [
            node
            for node in proposal.nodes
            if node.id not in matched and node.validation_status == "valid"
        ]
        while pending:
            progressed = False
            remaining = []
            for node in pending:
                if node.parent_id is not None and node.parent_id not in matched:
                    remaining.append(node)
                    continue
                if any(
                    _same_source(existing, node) and existing.uci_candidate == node.uci_candidate
                    for existing in original.nodes
                ):
                    conflicts.append(f"{node.move_text}: source already edited on another line")
                    continue
                if any(
                    paths[existing.id] == proposed_paths[node.id]
                    and any(e.page == n.page for e in existing.evidence for n in node.evidence)
                    for existing in original.nodes
                ):
                    conflicts.append(f"{node.move_text}: existing manual move has uncertain source")
                    continue
                parent = matched.get(node.parent_id) if node.parent_id else None
                if any(
                    existing.parent_id == parent and existing.uci_candidate == node.uci_candidate
                    for existing in target.nodes
                ):
                    conflicts.append(f"{node.move_text}: move already exists at this position")
                    continue
                fresh = node.model_copy(deep=True)
                used_ids = {item.id for item in target.nodes}
                if fresh.id in used_ids:
                    serial = 1
                    while f"recovered-{serial}" in used_ids:
                        serial += 1
                    fresh.id = f"recovered-{serial}"
                fresh.parent_id = parent
                siblings = [item for item in target.nodes if item.parent_id == parent]
                fresh.sibling_order = len(siblings)
                if node.sibling_order == 0 and not any(
                    item.id
                    in {old.id for old in _sequences(baseline).get(proposal.id, original).nodes}
                    and item.sibling_order
                    != next(
                        (
                            old.sibling_order
                            for old in _sequences(baseline)[proposal.id].nodes
                            if old.id == item.id
                        ),
                        item.sibling_order,
                    )
                    for item in siblings
                ):
                    for sibling in siblings:
                        sibling.sibling_order += 1
                    fresh.sibling_order = 0
                target.nodes.append(fresh)
                target.reading_flow.append(MoveFlowRef(kind="move", node_id=fresh.id))
                target.evidence.extend(e for e in fresh.evidence if e not in target.evidence)
                represented_sources.update(_key(e) for e in fresh.evidence)
                matched[node.id] = fresh.id
                added.append((fresh.evidence[0].page, fresh.move_text, target.id, fresh.id))
                progressed = True
            if not progressed:
                conflicts.extend(
                    f"{node.move_text}: parent cannot be restored safely" for node in remaining
                )
                break
            pending = remaining
        _renumber_siblings(target)
        _reflow(target)
    if coherent_added_line:
        _recover_styled_continuation(
            context,
            responses,
            merged,
            (human_node_ids or set()) | (mainline_node_ids or set()) | line_added_ids,
            source_keys,
            added,
            represented_sources,
            conflicts,
        )
    # Retire untouched issue cards once every cited score token is represented
    # by a legal, source-identified move. The old model's duplicate unresolved
    # card is no longer authoritative after a confirmed continuation.
    baseline_items = {item.id: item for item in baseline.items}

    def fully_represented(issue: UnresolvedItem) -> bool:
        covered = [
            key
            for key in source_keys.values()
            if any(
                e.page == key[0]
                and e.fragment_sha256 == key[1]
                and e.start_offset is not None
                and e.end_offset is not None
                and e.start_offset <= key[2]
                and key[3] <= e.end_offset
                for e in issue.evidence
            )
        ]
        return bool(covered) and all(key in represented_sources for key in covered)

    retired = 0
    kept = []
    for item in merged.items:
        before = baseline_items.get(item.id)
        if (
            isinstance(item, UnresolvedItem)
            and before is not None
            and item == before
            and fully_represented(item)
        ):
            retired += 1
        else:
            kept.append(item)
    merged.items = kept
    existing_ids = {item.id for item in kept}
    merged.diagnostics = [
        d for d in merged.diagnostics if d.item_id is None or d.item_id in existing_ids
    ]
    normalized = normalize_chess_moves_v1_1(merged)
    if not added and not retired:
        raise ValueError("replay found no new moves or resolved issues")
    return RecoveryResult(normalized, corrected, added, retired, preserved_manual, conflicts)
