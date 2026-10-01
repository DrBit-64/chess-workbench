"""Read-only real-game acceptance: simulate one wrong Catalan p6–9 relation and human repair."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.relations import (
    Continue,
    localize_invalid_relation_subtrees,
    source_tokens,
)
from chess_workbench.review.editing import apply_review_edit
from chess_workbench.review.recovery import recover_dependencies
from chess_workbench.schemas.review import (
    PdfReviewAddLine,
    PdfReviewEditText,
    PdfReviewReattachVariation,
    PdfReviewSetNag,
)
from experiment_pdf_review_recovery import compile_saved, saved_responses, summary
from replay_pdf_relations import load_saved_run

RUN = UUID("96e60d11-2c72-505f-aeb0-d033dfc50641")
BROKEN_VARIATION = "seg3"
MOVED_MAINLINE = "seg4"
OUTPUT = Path("data/debug/review-recovery-20260927/catalan-p6-9")


def source_node(package, context, ref):
    token = next(token for token in source_tokens(context) if token.id == ref)
    fragment = next(
        item.fragment
        for page in context.pages
        if page.physical_page == token.page
        for item in page.fragments
        if item.order == token.order
    )
    for sequence in (item for item in package.items if item.kind == "move_sequence"):
        for node in sequence.nodes:
            if any(
                e.page == token.page
                and e.fragment_sha256 == fragment.fragment_sha256
                and e.start_offset == token.start
                and e.end_offset == token.end
                for e in node.evidence
            ):
                return sequence, node
    raise AssertionError(f"source move {ref} is absent")


def lineage(sequence, node):
    nodes = {item.id: item for item in sequence.nodes}
    moves = []
    while node is not None:
        moves.append(node.uci_candidate)
        node = nodes.get(node.parent_id)
    return tuple(reversed(moves))


def main():
    context, manifest = load_saved_run(RUN, Settings())
    responses, owned = saved_responses(manifest)
    original, original_state = compile_saved(context, responses, owned)
    assert summary(original)["moves"] == 148
    broken = copy.deepcopy(responses)
    variation = next(s for r in broken for s in r.segments if s.id == BROKEN_VARIATION)
    removed = next(s for r in broken for s in r.segments if s.id == MOVED_MAINLINE)
    assert len(removed.move_refs) == 2 and variation.game_ref == removed.game_ref
    moved_ref = removed.move_refs.pop(0)
    variation.move_refs.append(moved_ref)
    variation.evidence_refs.extend(removed.evidence_refs)
    removed.entry = Continue(kind="continue", after_move_ref=moved_ref)
    degraded, broken_state = compile_saved(context, broken, owned)
    degraded = localize_invalid_relation_subtrees(context, broken_state, degraded)
    source, bad_node = source_node(degraded, context, moved_ref)
    parent_ref = original_state.parent[moved_ref]
    assert parent_ref is not None
    _, desired_parent = source_node(degraded, context, parent_ref)
    current = apply_review_edit(
        degraded,
        PdfReviewReattachVariation(
            kind="reattach_variation",
            sequence_id=source.id,
            node_id=bad_node.id,
            parent_node_id=desired_parent.id,
        ),
    ).package
    assert current.schema_version == "chess-content-extraction/1.1"
    current = apply_review_edit(
        current,
        PdfReviewSetNag(
            kind="set_nag",
            sequence_id=source.id,
            node_id=desired_parent.id,
            nag=1,
        ),
    ).package
    first = next(item for item in current.items if item.kind == "move_sequence")
    current = apply_review_edit(
        current,
        PdfReviewAddLine(
            kind="add_line",
            sequence_id=first.id,
            parent_node_id=first.nodes[0].id,
            moves=["e7e5"],
            evidence_page=6,
        ),
    ).package
    editable = next(item for item in current.items if item.kind == "prose")
    current = apply_review_edit(
        current,
        PdfReviewEditText(
            kind="edit_text",
            item_id=editable.id,
            text="Human wording kept after recovery.",
        ),
    ).package
    result = recover_dependencies(context, broken, owned, degraded, current)
    restored = result.package
    target = next(
        item
        for item in restored.items
        if item.kind == "move_sequence" and item.id == source.id
    )
    assert any(
        node.id == "manual-1" and node.uci_candidate == "e7e5" for node in target.nodes
    )
    assert (
        next(item for item in restored.items if item.id == editable.id).text
        == "Human wording kept after recovery."
    )
    assert next(node for node in target.nodes if node.id == desired_parent.id).nags == [
        1
    ]
    source_matches = 0
    mainline_matches = 0
    original_mainline_count = 0
    for seq in (item for item in original.items if item.kind == "move_sequence"):
        rebuilt = next(
            item
            for item in restored.items
            if item.kind == "move_sequence" and item.id == seq.id
        )
        for node in seq.nodes:
            matches = [
                candidate
                for candidate in rebuilt.nodes
                if lineage(seq, node) == lineage(rebuilt, candidate)
                and any(
                    a.page == b.page
                    and a.fragment_sha256 == b.fragment_sha256
                    and a.start_offset == b.start_offset
                    and a.end_offset == b.end_offset
                    for a in node.evidence
                    for b in candidate.evidence
                )
            ]
            if len(matches) == 1:
                source_matches += 1
                if node.sibling_order == 0:
                    original_mainline_count += 1
                    if matches[0].sibling_order == 0:
                        mainline_matches += 1
    report = {
        "run_id": str(RUN),
        "pages": [6, 9],
        "original_move_count": summary(original)["moves"],
        "degraded_move_count": summary(degraded)["moves"],
        "after_human_move_count": summary(current)["moves"],
        "restored_move_count": summary(restored)["moves"],
        "source_path_matches": source_matches,
        "mainline_source_matches": mainline_matches,
        "original_mainline_count": original_mainline_count,
        "recovered_move_count": len(result.added_moves),
        "retired_issues": result.retired_issue_count,
        "conflicts": result.conflicts,
        "manual_line_preserved": True,
        "manual_nag_preserved": True,
        "manual_prose_preserved": True,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    assert (
        source_matches == 148
        and mainline_matches == original_mainline_count
        and not result.conflicts
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
