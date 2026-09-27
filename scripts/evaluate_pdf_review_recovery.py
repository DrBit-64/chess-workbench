"""Compare a replay artifact to independently transcribed source relationships.

The oracle is evaluation data only; it is never supplied to the repair algorithm/model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.relations import parse_relation_response, source_tokens
from experiment_pdf_review_recovery import compile_saved, evidence_key, token_keys
from replay_pdf_relations import load_saved_run


def evaluate(run_id, oracle_file, replay_dir):
    context, _ = load_saved_run(run_id, Settings())
    oracle = json.loads(oracle_file.read_text())
    tokens = source_tokens(context)
    source_keys = token_keys(context)
    token_by_evidence = {key: ref for ref, key in source_keys.items()}

    def refs(line):
        selected = [
            t.id for span in line["spans"] for t in tokens if t.span_ref == span
        ]
        return selected[line.get("skip_prefix", 0) :]

    main = refs(oracle["main"])
    expectations = {}
    line_groups = [("main", main, None)]
    for variation in oracle["variations"]:
        line_groups.append((variation["label"], refs(variation), variation["after"]))
    for label, chain, parent in line_groups:
        for ref in chain:
            if ref in expectations:
                raise ValueError(f"Duplicate oracle occurrence: {ref}")
            expectations[ref] = (parent, label)
            parent = ref

    responses = [
        parse_relation_response(json.dumps(r))
        for r in json.loads((replay_dir / "responses.json").read_text())
    ]
    owned = {
        f"s{p.physical_page}_{f.order}" for p in context.pages for f in p.fragments
    }
    _, state = compile_saved(context, responses, [owned] * len(responses))
    candidate = ExtractionPackageV1_1.model_validate_json(
        (replay_dir / "localized.json").read_text()
    )
    observed = {}
    for seq in (i for i in candidate.items if i.kind == "move_sequence"):
        node_refs = {
            n.id: token_by_evidence.get(evidence_key(n.evidence[0])) for n in seq.nodes
        }
        for n in seq.nodes:
            ref = node_refs[n.id]
            observed.setdefault(ref, []).append(
                (node_refs.get(n.parent_id), n.validation_status)
            )
    failures = []
    for ref, (expected_parent, label) in expectations.items():
        actual = observed.get(ref, [])
        if actual != [(expected_parent, "valid")]:
            failures.append(
                {
                    "source": ref,
                    "group": label,
                    "expected_parent": expected_parent,
                    "actual": actual,
                }
            )

    def source_path(ref, parents):
        result = []
        while ref is not None:
            if ref in result or ref not in parents:
                return None
            result.append(ref)
            ref = parents[ref]
        return tuple(reversed(result))

    expected_parents = {ref: value[0] for ref, value in expectations.items()}
    actual_parents = {
        ref: values[0][0] for ref, values in observed.items() if len(values) == 1
    }
    wrong_paths = [
        ref
        for ref in expectations
        if source_path(ref, expected_parents) != source_path(ref, actual_parents)
    ]
    main_game_line = state.token_line.get(main[0])
    main_failures = [
        ref
        for ref in main
        if state.token_line.get(ref) != main_game_line or ref not in observed
    ]
    extra_refs = [ref for ref in observed if ref not in expectations]
    failures_by_group = {f["group"] for f in failures} | {
        expectations[ref][1] for ref in wrong_paths
    }
    report = {
        "oracle_moves": len(expectations),
        "correct_parent_and_legal": len(expectations) - len(failures),
        "correct_complete_source_paths": len(expectations) - len(wrong_paths),
        "wrong_or_missing_source_paths": wrong_paths,
        "missing_moves": sum(ref not in observed for ref in expectations),
        "parent_failures": failures,
        "unexpected_moves": extra_refs,
        "played_mainline_length": len(main),
        "mainline_relation_failures": main_failures,
        "variation_count": len(oracle["variations"]),
        "complete_correct_variations": sum(
            label not in failures_by_group for label, _, _ in line_groups[1:]
        ),
        "scope": "Printed mainline and formal variations; prose annotation placement is not scored.",
    }
    (replay_dir / "source-evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.run_id, args.oracle, args.replay)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                not in {
                    "parent_failures",
                    "mainline_relation_failures",
                    "wrong_or_missing_source_paths",
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
