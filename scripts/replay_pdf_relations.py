"""Replay a saved relation response against current local compilation code.

Usage: uv run --project backend --locked python scripts/replay_pdf_relations.py RUN_ID
This reads local CAS artifacts only and never contacts the model provider.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    SourceEvidenceFragment,
    TextStyleRun,
)
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
)
from chess_workbench.extraction.relations import (
    RelationPatchResponse,
    RelationState,
    apply_relation_patches,
    apply_relations,
    build_relation_patch_request,
    compile_relations,
    formal_score_note_issues,
    localize_invalid_relation_subtrees,
    parse_relation_response,
    recover_completed_relation_prefix,
    source_tokens,
    style_continuity_issues,
    validation_relation_issues,
)
from sqlalchemy.engine import make_url


def load_saved_run(run_id: UUID, settings: Settings) -> tuple[CcefPromptContext, dict]:
    """Load immutable evidence and responses without opening a write connection."""
    connection = sqlite3.connect(
        f"file:{make_url(settings.database_url).database}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    run = connection.execute(
        "select r.*,a.source_file_id from extraction_runs r "
        "join pdf_assets a on a.id=r.pdf_asset_id where r.id=?",
        (run_id.hex,),
    ).fetchone()
    if run is None:
        raise SystemExit("run not found")
    artifacts = list(
        connection.execute(
            "select * from extraction_artifacts where run_id=?", (run_id.hex,)
        )
    )
    pages = []
    for artifact in sorted(artifacts, key=lambda row: row["page_number"] or 0):
        if artifact["kind"] != "ocr_fragment":
            continue
        data = json.loads(
            (settings.source_storage_root / artifact["relative_path"]).read_text()
        )
        fragments = []
        for raw in data["fragments"]:
            fragment = SourceEvidenceFragment(
                physical_page=raw["physical_page"],
                box=NormalizedBox(
                    **dict(zip(("x0", "y0", "x1", "y1"), raw["bbox"], strict=True))
                ),
                text=raw["text"],
                origin=raw["origin"],
                confidence=raw["confidence"],
                engine_name=raw["engine_name"],
                engine_version=raw["engine_version"],
                fragment_sha256=raw["fragment_sha256"],
                font_color=raw.get("font_color"),
                style_runs=[
                    TextStyleRun.model_validate(value)
                    for value in raw.get("style_runs", [])
                ],
            )
            fragments.append(
                PromptEvidenceFragment(order=raw["order"], fragment=fragment)
            )
        pages.append(
            PromptEvidencePage(
                physical_page=artifact["page_number"], fragments=fragments
            )
        )
    context = CcefPromptContext(
        package_id=run_id,
        created_at=datetime.fromisoformat(run["created_at"]).replace(tzinfo=UTC),
        source_ref=f"source-file:{UUID(run['source_file_id'])}",
        media_type="application/pdf",
        language="en",
        first_page=run["first_page"],
        last_page=run["last_page"],
        pages=pages,
        max_output_tokens=settings.ccef_max_output_tokens,
        max_prompt_chars=settings.ccef_max_prompt_chars,
    )
    manifest_artifact = next(
        row for row in artifacts if row["kind"] == "semantic_manifest"
    )
    manifest = json.loads(
        (settings.source_storage_root / manifest_artifact["relative_path"]).read_text()
    )
    connection.close()
    return context, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--patch-file", type=Path)
    parser.add_argument("--patch-request", type=Path)
    parser.add_argument("--patches-only", action="store_true")
    args = parser.parse_args()
    run_id = UUID(args.run_id)
    settings = Settings()
    context, manifest = load_saved_run(run_id, settings)
    state = RelationState()
    tokens = source_tokens(context)
    parsed_windows = []
    patch_chunk = None
    for chunk in manifest["chunks"]:
        if chunk["request"]["response_schema_name"] == "chess_source_relation_patch_v1":
            patch_chunk = chunk
            continue
        owned = set(
            json.loads(chunk["request"]["messages"][1]["content"])["window"][
                "owned_span_refs"
            ]
        )
        if chunk["response"]["finish_reason"] == "length":
            response = recover_completed_relation_prefix(chunk["response"]["content"])
            if response is None:
                continue
        else:
            response = parse_relation_response(chunk["response"]["content"])
        parsed_windows.append((response, owned))
    responses = [response for response, _ in parsed_windows]
    if patch_chunk is not None and patch_chunk.get("applied"):
        patch = RelationPatchResponse.model_validate_json(
            patch_chunk.get("applied_patch") or patch_chunk["response"]["content"]
        )
        responses = apply_relation_patches(responses, patch)
    if args.patch_file is not None:
        patch_data = json.loads(args.patch_file.read_text())
        patch = RelationPatchResponse.model_validate_json(
            patch_data["response"]["content"]
        )
        if args.patches_only:
            patch = patch.model_copy(
                update={
                    "replacements": [],
                    "promotions": [],
                    "additions": [],
                    "games": [],
                    "demotions": [],
                }
            )
        responses = apply_relation_patches(responses, patch)
    for response, (_, owned) in zip(responses, parsed_windows, strict=True):
        apply_relations(context, response, tokens, owned, state)
    package = compile_relations(context, state)
    issues = style_continuity_issues(context, package, state, responses, tokens)
    issues.extend(validation_relation_issues(package, state, responses, tokens))
    issues.extend(formal_score_note_issues(context, tokens, responses))
    if args.patch_request is not None:
        request = build_relation_patch_request(context, tokens, responses, issues[:4])
        args.patch_request.write_text(request.model_dump_json(indent=2))
    package = localize_invalid_relation_subtrees(context, state, package)
    sequences = [item for item in package.items if item.kind == "move_sequence"]
    nodes = [node for sequence in sequences for node in sequence.nodes]
    print(
        json.dumps(
            {
                "run_id": str(run_id),
                "sequences": len(sequences),
                "moves": len(nodes),
                "valid_moves": sum(node.validation_status == "valid" for node in nodes),
                "unresolved": sum(item.kind == "unresolved" for item in package.items),
                "aliases": [
                    {"game_ref": game, "from": line, "to": target_line}
                    for (game, line), (_, target_line) in state.line_aliases.items()
                ],
                "problems": len(state.problems),
                "issues": issues,
                "patch_applied": bool(
                    (patch_chunk and patch_chunk.get("applied")) or args.patch_file
                ),
            },
            ensure_ascii=False,
        )
    )
    if args.output is not None:
        args.output.write_text(package.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
