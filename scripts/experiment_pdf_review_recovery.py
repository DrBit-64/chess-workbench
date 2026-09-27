"""Read-only experiment: promote human reattachments to source relations and replay.

Only writes experiment artifacts under --output; never updates a review session.
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path
from uuid import UUID

import chess
from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.relations import (
    RelationPatchResponse,
    RelationState,
    apply_relation_patches,
    apply_relations,
    compile_relations,
    localize_invalid_relation_subtrees,
    parse_relation_response,
    source_tokens,
    validation_relation_issues,
)
from replay_pdf_relations import load_saved_run
from sqlalchemy.engine import make_url


def saved_responses(manifest):
    windows = []
    patches = []
    for chunk in manifest["chunks"]:
        if chunk["request"]["response_schema_name"] == "chess_source_relation_patch_v1":
            if chunk.get("applied"):
                patches.append(
                    RelationPatchResponse.model_validate_json(
                        chunk.get("applied_patch") or chunk["response"]["content"]
                    )
                )
            continue
        owned = set(
            json.loads(chunk["request"]["messages"][1]["content"])["window"][
                "owned_span_refs"
            ]
        )
        windows.append((parse_relation_response(chunk["response"]["content"]), owned))
    responses = [response for response, _ in windows]
    for patch in patches:
        responses = apply_relation_patches(responses, patch)
    return responses, [owned for _, owned in windows]


def compile_saved(context, responses, owned):
    state = RelationState()
    tokens = source_tokens(context)
    for response, window in zip(responses, owned, strict=True):
        apply_relations(context, response, tokens, window, state)
    package = compile_relations(context, state)
    return package, state


def evidence_key(e):
    return (e.page, e.fragment_sha256, e.start_offset, e.end_offset)


def token_keys(context):
    fragments = {
        (p.physical_page, f.order): f.fragment
        for p in context.pages
        for f in p.fragments
    }
    return {
        t.id: (t.page, fragments[t.page, t.order].fragment_sha256, t.start, t.end)
        for t in source_tokens(context)
    }


def nodes_by_id(package):
    return {
        (item.id, node.id): node
        for item in package.items
        if item.kind == "move_sequence"
        for node in item.nodes
    }


def derive_human_patch(context, responses, state, baseline, reviewed):
    keys = token_keys(context)
    token_by_key = {key: token for token, key in keys.items()}
    old = nodes_by_id(baseline)
    new = nodes_by_id(reviewed)
    replacements = []
    corrections = []
    for key, before in old.items():
        after = new.get(key)
        if after is None or before.parent_id == after.parent_id:
            continue
        ref = next(
            (
                token_by_key.get(evidence_key(e))
                for e in before.evidence
                if evidence_key(e) in token_by_key
            ),
            None,
        )
        parent = new.get((key[0], after.parent_id))
        parent_ref = (
            next(
                (
                    token_by_key.get(evidence_key(e))
                    for e in parent.evidence
                    if evidence_key(e) in token_by_key
                ),
                None,
            )
            if parent
            else None
        )
        if not ref or not parent_ref or parent_ref not in state.token_line:
            raise ValueError(
                "Human reattachment lacks a unique original source occurrence"
            )
        owners = [s for r in responses for s in r.segments if ref in s.move_refs]
        if len(owners) != 1:
            raise ValueError("Human move has ambiguous source segment ownership")
        segment = owners[0]
        index = segment.move_refs.index(ref)
        game, line = state.token_line[parent_ref]
        if state.lines[(game, line)][2] != parent_ref:
            raise ValueError("This experiment supports explicit line-tail resumes only")
        suffix = segment.model_dump(mode="json")
        suffix.update(
            id=f"human_resume_{segment.id}_{index}",
            game_ref=game,
            line_ref=line,
            entry={"kind": "continue", "after_move_ref": parent_ref},
            move_refs=segment.move_refs[index:],
        )
        replacement = []
        if index:
            prefix = segment.model_dump(mode="json")
            prefix["move_refs"] = segment.move_refs[:index]
            replacement.append(prefix)
        replacement.append(suffix)
        sources = list(
            dict.fromkeys(
                [
                    *segment.evidence_refs,
                    next(
                        t.span_ref for t in source_tokens(context) if t.id == parent_ref
                    ),
                ]
            )
        )
        replacements.append(
            {"segment_id": segment.id, "segments": replacement, "source_refs": sources}
        )
        corrections.append(
            {
                "node_id": before.id,
                "move": before.move_text,
                "source_ref": ref,
                "parent_ref": parent_ref,
                "target_line": line,
                "split_index": index,
            }
        )
    patch = RelationPatchResponse.model_validate(
        {
            "schema_version": "chess-source-relation-patch/1",
            "patches": [],
            "replacements": replacements,
        }
    )
    return patch, corrections


def summary(package, state=None):
    nodes = list(nodes_by_id(package).values())
    invalid_roots = []
    mainlines = []
    for seq in (i for i in package.items if i.kind == "move_sequence"):
        by_id = {n.id: n for n in seq.nodes}
        for n in seq.nodes:
            if n.validation_status != "valid" and (
                n.parent_id is None or by_id[n.parent_id].validation_status == "valid"
            ):
                invalid_roots.append(
                    {
                        "node": n.id,
                        "move": n.move_text,
                        "page": n.evidence[0].page,
                        "parent": n.parent_id,
                    }
                )
        line = []
        parent = None
        while children := sorted(
            [n for n in seq.nodes if n.parent_id == parent],
            key=lambda n: n.sibling_order,
        ):
            n = children[0]
            board = chess.Board(n.fen_before) if n.fen_before else None
            number = n.move_number or (board.fullmove_number if board else "?")
            side = n.side_to_move or ("w" if board and board.turn else "b")
            line.append(f"{number}{'.' if side == 'w' else '...'}{n.move_text}")
            parent = n.id
        mainlines.append(line)
    return {
        "moves": len(nodes),
        "legal": sum(n.validation_status == "valid" for n in nodes),
        "unresolved": sum(i.kind == "unresolved" for i in package.items),
        "unresolved_by_page": dict(
            Counter(i.evidence[0].page for i in package.items if i.kind == "unresolved")
        ),
        "invalid_roots": invalid_roots,
        "mainlines": mainlines,
        "relation_problems": len(state.problems) if state else None,
    }


def paths(package):
    result = {}
    for seq in (i for i in package.items if i.kind == "move_sequence"):
        by_id = {n.id: n for n in seq.nodes}
        for n in seq.nodes:
            lineage = []
            current = n
            while current is not None:
                lineage.append(current.uci_candidate)
                current = by_id.get(current.parent_id)
            result[(seq.id, n.id)] = tuple(reversed(lineage))
    return result


def compare_manual(baseline, reviewed, candidate):
    original = nodes_by_id(baseline)
    manual = nodes_by_id(reviewed)
    proposed = nodes_by_id(candidate)
    manual_paths = paths(reviewed)
    candidate_paths = paths(candidate)
    matches = []
    conflicts = []
    reattached = []
    reattachment_conflicts = []
    for key, n in manual.items():
        is_reattachment = key in original
        if is_reattachment and original[key].parent_id == n.parent_id:
            continue
        candidates = [
            cn
            for ck, cn in proposed.items()
            if candidate_paths[ck] == manual_paths[key]
            and cn.validation_status == "valid"
            and any(
                a.page == b.page
                and a.fragment_sha256 == b.fragment_sha256
                and a.start_offset is not None
                and b.start_offset is not None
                and a.start_offset <= b.start_offset < b.end_offset <= a.end_offset
                for a in n.evidence
                for b in cn.evidence
            )
        ]
        detail = {
            "node": n.id,
            "move": n.move_text,
            "candidate_nodes": [cn.id for cn in candidates],
        }
        if is_reattachment:
            (reattached if len(candidates) == 1 else reattachment_conflicts).append(
                detail
            )
        else:
            (matches if len(candidates) == 1 else conflicts).append(detail)
    return {
        "manual_added": len(matches) + len(conflicts),
        "exact_path_and_source_matches": len(matches),
        "conflicts": conflicts,
        "matches": matches,
        "manual_reattached": len(reattached) + len(reattachment_conflicts),
        "reattachment_matches": reattached,
        "reattachment_conflicts": reattachment_conflicts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-patch", type=Path)
    parser.add_argument(
        "--human-revision",
        type=int,
        help="Use only corrections known at this revision; compare against the latest review",
    )
    args = parser.parse_args()
    settings = Settings()
    args.output.mkdir(parents=True, exist_ok=True)
    context, manifest = load_saved_run(args.run_id, settings)
    with sqlite3.connect(
        f"file:{make_url(settings.database_url).database}?mode=ro", uri=True
    ) as db:
        db.row_factory = sqlite3.Row
        session = db.execute(
            "SELECT * FROM pdf_review_sessions WHERE extraction_run_id=? ORDER BY updated_at DESC LIMIT 1",
            (args.run_id.hex,),
        ).fetchone()
        revisions = list(
            db.execute(
                "SELECT revision_number,relative_path FROM pdf_review_revisions WHERE session_id=? ORDER BY revision_number",
                (session["id"],),
            )
        )
    packages = {
        r["revision_number"]: ExtractionPackageV1_1.model_validate_json(
            (settings.source_storage_root / r["relative_path"]).read_text()
        )
        for r in revisions
    }
    baseline = packages[1]
    latest = packages[session["version"]]
    responses, owned = saved_responses(manifest)
    original, state = compile_saved(context, responses, owned)
    patch, corrections = derive_human_patch(
        context,
        responses,
        state,
        baseline,
        packages[args.human_revision] if args.human_revision else latest,
    )
    corrected = apply_relation_patches(responses, patch)
    if args.model_patch:
        model_patch = RelationPatchResponse.model_validate_json(
            args.model_patch.read_text()
        )
        corrected = apply_relation_patches(corrected, model_patch)
    package, newstate = compile_saved(context, corrected, owned)
    localized = localize_invalid_relation_subtrees(
        context, copy.deepcopy(newstate), package
    )
    report = {
        "run_id": str(args.run_id),
        "review_version": session["version"],
        "patch_from_revision": args.human_revision or session["version"],
        "human_corrections": corrections,
        "saved_baseline": summary(baseline),
        "latest_review": summary(latest),
        "replay_before": summary(original, state),
        "replay_after": summary(package, newstate),
        "localized_after": summary(localized),
        "manual_preservation": compare_manual(baseline, latest, package),
        "issues": validation_relation_issues(
            package, newstate, corrected, source_tokens(context)
        ),
    }
    for name, value in [
        ("report", report),
        ("human-patch", patch.model_dump(mode="json")),
        ("responses", [r.model_dump(mode="json") for r in corrected]),
    ]:
        (args.output / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2)
        )
    (args.output / "candidate.json").write_text(package.model_dump_json(indent=2))
    (args.output / "localized.json").write_text(localized.model_dump_json(indent=2))
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"issues", "manual_preservation"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(
        json.dumps(
            {k: v for k, v in report["manual_preservation"].items() if k != "matches"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
