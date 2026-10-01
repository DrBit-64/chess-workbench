"""One-edit acceptance against the real, previously failed Catalan p18-24 run.

The move error was produced by DeepSeek. This script uses the same review edit
operation as the website, and compares the repaired played line with the PDF's
printed score. It neither alters the saved extraction nor fabricates an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.relations import localize_invalid_relation_subtrees
from chess_workbench.review.editing import apply_review_edit
from chess_workbench.review.recovery import recover_dependencies
from chess_workbench.schemas.review import PdfReviewAddLine
from experiment_pdf_review_recovery import compile_saved, saved_responses, token_keys
from replay_pdf_relations import load_saved_run

ROOT = Path("data/debug/review-recovery-20260927/next-game-p18-24").absolute()
RUN_ID = UUID("bf7260c9-35a1-51b4-9a20-96610a13caab")
# Independently transcribed black printed score from the source PDF, p20-24.
# Independently checked branch starts from the printed blue score spans.
EXPECTED_VARIATION_ROOTS = {
    "t18_17_3": "t18_6_6",  # 10.Bf4 after 9...b6
    "t18_28_5": "t18_6_12",  # 10...Bb7 instead of 10...a5
    "t18_29_5": "t18_6_12",  # 10...Ba6 instead of 10...a5
    "t18_32_12": "t18_18_6",  # 11.Bf4 after 10...a5
    "t18_46_5": "t18_34_3",  # 11...Ba6 instead of 11...Bb7
    "t19_14_3": "t19_4_8",  # 17.Qxc4 instead of 17.Bxf6
    "t19_60_3": "t19_17_7",  # 21.a4 instead of 21.Rc6
    "t20_10_12": "t19_61_5",  # 22.Rxb6 instead of 22.Rcc1
    "t20_49_5": "t20_36_3",  # 25...Bxd6 instead of 25...Rd7
    "t21_10_20": "t21_11_14",  # 31...Ra3 after 31.axb3
    "t22_10_5": "t21_63_3",  # 36...Kh6 instead of 36...Bxb4
    "t22_23_3": "t21_67_5",  # 37.Rxb5 instead of 37.Ne5
    "t22_37_6": "t22_11_3",  # 37...f6 instead of 37...Rd5
    "t22_52_5": "t22_38_3",  # 38...Bc3 instead of 38...Rxh5
    "t23_10_5": "t23_0_12",  # 40...Kf5 instead of 40...Kh7
    "t23_23_3": "t23_11_19",  # 43.Rxb5 instead of 43.Nf3
    "t23_36_5": "t23_11_26",  # 43...Kg6 instead of 43...Rf5
    "t23_48_6": "t23_38_15",  # 45...e5 instead of 45...Bd2
    "t24_10_3": "t23_52_32",  # 52.Nxb4 instead of 52.Ke4
}

EXPECTED_FROM_26 = [
    "Nc4",
    "Rxd1",
    "Rxd1",
    "b5",
    "Ne5",
    "Bf6",
    "Nd7",
    "a4",
    "Rc1",
    "axb3",
    "axb3",
    "Be7",
    "Rc7",
    "Rd8",
    "Rb7",
    "Bd6",
    "g4",
    "h5",
    "gxh5",
    "Kh7",
    "b4",
    "Bxb4",
    "Ne5",
    "Rd5",
    "Nxf7",
    "Rxh5",
    "f4",
    "Kg6",
    "Ne5+",
    "Kh7",
    "Nf7",
    "Kg6",
    "Ne5+",
    "Kh7",
    "Nf3",
    "Rf5",
    "Ng5+",
    "Kh6",
    "Kf3",
    "Bd2",
    "e3",
    "b4",
    "Nxe6",
    "Rh5",
    "Nxg7",
    "Rxh2",
    "Nf5+",
    "Kg6",
    "Ne7+",
    "Kf6",
    "Nd5+",
    "Ke6",
    "Ke4",
    "Rh3",
    "Rb6+",
    "Kd7",
    "Kd3",
    "Bc1",
    "Rxb4",
    "Kd6",
    "Kd4",
]


def sequence(package):
    return next(
        item
        for item in package.items
        if item.kind == "move_sequence" and len(item.nodes) > 10
    )


def mainline(item):
    by_parent = {}
    for node in item.nodes:
        if node.sibling_order == 0:
            by_parent[node.parent_id] = node
    result = []
    parent_id = None
    while parent_id in by_parent:
        node = by_parent[parent_id]
        result.append(node)
        parent_id = node.id
    return result


def main():
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{ROOT / 'evaluation.db'}",
        source_storage_root=ROOT / "storage",
    )
    context, manifest = load_saved_run(RUN_ID, settings)
    responses, owned = saved_responses(manifest)
    baseline, state = compile_saved(context, responses, owned)
    baseline = localize_invalid_relation_subtrees(context, state, baseline)
    baseline_sequence = sequence(baseline)
    assert mainline(baseline_sequence)[-1].move_text == "Rd7"
    before_nodes = {node.id for node in baseline_sequence.nodes}
    # The real model wrongly put 25...Bxd6 26.Rxd6 on the main line. One human
    # correction inserts the book's 26.Nc4 after its existing 25...Rd7.
    edited = apply_review_edit(
        baseline,
        PdfReviewAddLine(
            kind="add_line",
            sequence_id=baseline_sequence.id,
            parent_node_id=mainline(baseline_sequence)[-1].id,
            moves=["d6c4"],
            evidence_page=20,
        ),
    ).package
    human_ids = {node.id for node in sequence(edited).nodes} - before_nodes
    assert len(human_ids) == 1
    result = recover_dependencies(
        context, responses, owned, baseline, edited, human_added_ids=human_ids
    )
    recovered = sequence(result.package)
    played = mainline(recovered)
    tail = [node.san_candidate for node in played[50:]]
    actual = [value.replace("X", "x") for value in tail]
    failures = [
        {
            "ply": 51 + index,
            "expected": expected,
            "actual": actual[index] if index < len(actual) else None,
        }
        for index, expected in enumerate(EXPECTED_FROM_26)
        if index >= len(actual) or actual[index] != expected
    ]
    unresolved = [item for item in result.package.items if item.kind == "unresolved"]
    total_unresolved = len(unresolved)
    by_evidence = {key: ref for ref, key in token_keys(context).items()}
    node_refs = {
        node.id: next(
            (
                by_evidence.get(
                    (e.page, e.fragment_sha256, e.start_offset, e.end_offset)
                )
                for e in node.evidence
                if (e.page, e.fragment_sha256, e.start_offset, e.end_offset)
                in by_evidence
            ),
            None,
        )
        for node in recovered.nodes
    }
    actual_parents = {
        node_refs[node.id]: node_refs.get(node.parent_id)
        for node in recovered.nodes
        if node_refs[node.id] is not None
    }
    variation_failures = {
        ref: {"expected": parent, "actual": actual_parents.get(ref)}
        for ref, parent in EXPECTED_VARIATION_ROOTS.items()
        if actual_parents.get(ref) != parent
    }
    unique_unresolved = {
        (
            item.evidence[0].page,
            item.evidence[0].fragment_sha256,
            item.evidence[0].start_offset,
            item.evidence[0].end_offset,
        )
        for item in unresolved
    }
    source_keys = token_keys(context)
    represented = {
        (e.page, e.fragment_sha256, e.start_offset, e.end_offset)
        for item in result.package.items
        if item.kind == "move_sequence"
        for node in item.nodes
        for e in node.evidence
        if node.validation_status == "valid"
    }
    covered_issues = []
    for item in unresolved:
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
                for e in item.evidence
            )
        ]
        if covered and all(key in represented for key in covered):
            covered_issues.append(item)
    unresolved_by_page = {
        page: sum(item.evidence[0].page == page for item in unresolved)
        for page in range(18, 25)
    }
    report = {
        "run_id": str(RUN_ID),
        "source_pages": [18, 24],
        "human_operations": 1,
        "human_move": "26.Nc4",
        "baseline_valid_moves": len(baseline_sequence.nodes),
        "baseline_mainline_plies": len(mainline(baseline_sequence)),
        "restored_move_count": len(recovered.nodes),
        "restored_mainline_plies": len(played),
        "expected_tail_plies": len(EXPECTED_FROM_26),
        "tail_matches_source": not failures and len(actual) == len(EXPECTED_FROM_26),
        "tail_failures": failures[:10],
        "variation_roots_checked": len(EXPECTED_VARIATION_ROOTS),
        "variation_root_failures": variation_failures,
        "restored_variation_roots": [
            {
                "source": node_refs[node.id],
                "move": node.move_text,
                "parent": node_refs.get(node.parent_id),
                "page": node.evidence[0].page,
            }
            for node in recovered.nodes
            if node.sibling_order > 0 and node_refs[node.id] is not None
        ],
        "new_moves_from_program": len(result.added_moves),
        "retired_issue_cards": result.retired_issue_count,
        "remaining_unresolved_cards": total_unresolved,
        "unique_unresolved_sources": len(unique_unresolved),
        "fully_represented_issue_cards": len(covered_issues),
        "unresolved_by_page": unresolved_by_page,
        "remaining_unresolved": [
            {"page": item.evidence[0].page, "text": (item.raw_text or "")[:100]}
            for item in unresolved
        ],
        "conflicts": result.conflicts,
        "human_move_preserved": human_ids.issubset(
            {node.id for node in recovered.nodes}
        ),
    }
    (ROOT / "recovery-acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert (
        report["tail_matches_source"]
        and report["human_move_preserved"]
        and not variation_failures
    )


if __name__ == "__main__":
    main()
