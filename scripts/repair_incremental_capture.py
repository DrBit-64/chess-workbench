#!/usr/bin/env python3
"""Repair one retained incremental CCEF failure without rerunning extraction.

This operator tool is intentionally read-only with respect to SQL and the
authoritative extraction artifact index.  It reuses an existing failed model
response and committed OCR evidence, performs at most one bounded patch call,
and writes locally validated debug artifacts below ``data/debug``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from chess_workbench.config import Settings
from chess_workbench.extraction.candidates import _decode_fragment_bound_response_v1_1
from chess_workbench.extraction.contracts import MoveSequenceItemV1_1, PageRange
from chess_workbench.extraction.general_repair import (
    apply_ccef_repair,
    apply_deterministic_ccef_repairs,
    build_ccef_repair_request,
    ccef_repair_diagnostics,
)
from chess_workbench.extraction.incremental import (
    build_ccef_continuation_context,
    compose_incremental_ccef,
)
from chess_workbench.extraction.provider import StructuredGenerationResponse, TokenUsage
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.ccef_failure_debug import CCEF_FAILURE_DEBUG_SCHEMA
from chess_workbench.services.pdf_extraction import (
    _active_provider,
    _deepseek_invalid_response_recorder,
    _load_committed_evidence,
)
from chess_workbench.services.pdf_incremental_extraction import (
    _bind_continuations,
    _check_metadata,
    _load_incremental_input,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models import ExtractionRun, Job
from sqlalchemy import select


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value, pretty=True))


def _progress(message: str) -> None:
    print(message, flush=True)


def _load_capture(
    storage_root: Path,
    *,
    run_id: UUID,
    job_id: UUID,
    attempt_count: int,
) -> StructuredGenerationResponse:
    capture_root = (
        storage_root
        / "debug"
        / "extraction-failures"
        / str(run_id)
        / f"attempt-{attempt_count}"
    )
    matches: list[tuple[dict[str, Any], bytes]] = []
    for report_path in sorted(capture_root.glob("*/*.json")):
        try:
            report = json.loads(report_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            not isinstance(report, dict)
            or report.get("artifact_schema") != CCEF_FAILURE_DEBUG_SCHEMA
            or report.get("run_id") != str(run_id)
            or report.get("job_id") != str(job_id)
            or report.get("attempt_count") != attempt_count
        ):
            continue
        failure = report.get("failure")
        if (
            not isinstance(failure, dict)
            or failure.get("code") != "ccef_invalid_package"
        ):
            continue
        response = report.get("response")
        if not isinstance(response, dict) or "http_status" in response:
            continue
        digest = response.get("content_sha256")
        byte_size = response.get("byte_size")
        if type(digest) is not str or type(byte_size) is not int:
            continue
        content_path = capture_root / digest[:2] / f"{digest}.txt"
        try:
            content = content_path.read_bytes()
        except OSError:
            continue
        if len(content) != byte_size or hashlib.sha256(content).hexdigest() != digest:
            continue
        matches.append((response, content))
    if len(matches) != 1:
        raise RuntimeError(
            "expected exactly one retained CCEF response for this attempt"
        )
    metadata, content = matches[0]
    return StructuredGenerationResponse(
        content=content.decode("utf-8"),
        provider=metadata["provider"],
        model=metadata["model"],
        finish_reason=metadata.get("finish_reason"),
        usage=TokenUsage.model_validate(metadata.get("usage", {})),
    )


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    database = Database(settings.database_url)
    try:
        _progress("Loading failed extraction run...")
        async with database.session() as session:
            row = (
                await session.execute(
                    select(ExtractionRun, Job)
                    .join(Job, Job.id == ExtractionRun.job_id)
                    .where(ExtractionRun.id == args.run_id)
                )
            ).one_or_none()
        if row is None:
            raise RuntimeError("incremental extraction run was not found")
        run, job = row
        if run.pipeline_version != "pdf-extraction:v5" or job.status != "failed":
            raise RuntimeError("run is not a failed incremental extraction")
        _progress("Loading committed base document and source evidence...")
        inputs = await _load_incremental_input(database, settings, job.payload)
        evidence = await _load_committed_evidence(database, settings, inputs.source)
        if evidence is None:
            raise RuntimeError("failed run has no committed OCR evidence")
        continuation = build_ccef_continuation_context(
            inputs.base_package,
            base_normalized_ccef_sha256=inputs.base_sha256,
            next_page_range=PageRange(
                start_page=inputs.source.first_page,
                end_page=inputs.source.last_page,
            ),
        )
        original = _load_capture(
            settings.source_storage_root,
            run_id=run.id,
            job_id=job.id,
            attempt_count=job.attempt_count,
        )
        diagnostics = ccef_repair_diagnostics(original, context=evidence.context)
        prefix = args.output_prefix or (
            settings.source_storage_root / "debug" / f"incremental-repair-{run.id}"
        )

        def validate_candidate(
            candidate: StructuredGenerationResponse,
        ) -> tuple[tuple[str, ...], Any, Any, Any]:
            decoded, binding_diagnostics, complete = (
                _decode_fragment_bound_response_v1_1(
                    candidate,
                    evidence.context,
                )
            )
            _check_metadata(decoded, evidence.context)
            if not complete:
                raise RuntimeError(
                    "repaired response did not bind all trusted evidence"
                )
            bound = _bind_continuations(decoded, continuation)
            normalized = normalize_chess_moves_v1_1(bound)
            aggregate = compose_incremental_ccef(
                inputs.base_package,
                normalized,
                context=continuation,
                document_id=inputs.document_id,
            )
            return tuple(binding_diagnostics), bound, normalized, aggregate

        repair_base, deterministic_operations = apply_deterministic_ccef_repairs(
            original
        )
        repair_failure: BaseException | None = None
        if deterministic_operations:
            _progress("Validating deterministic source-preserving repairs...")
            try:
                binding_diagnostics, bound, normalized, aggregate = validate_candidate(
                    repair_base
                )
            except (RuntimeError, ValueError) as error:
                repair_failure = error
            else:
                _write(
                    prefix.with_suffix(".repaired-raw.json"),
                    bound.model_dump(mode="json"),
                )
                _write(
                    prefix.with_suffix(".normalized.json"),
                    normalized.model_dump(mode="json"),
                )
                _write(
                    prefix.with_suffix(".aggregate.json"),
                    aggregate.model_dump(mode="json"),
                )
                report = {
                    "status": "validated",
                    "repair_mode": "deterministic",
                    "run_id": str(run.id),
                    "job_id": str(job.id),
                    "source_response_sha256": hashlib.sha256(
                        original.content.encode("utf-8")
                    ).hexdigest(),
                    "diagnostics": [
                        diagnostic.model_dump(mode="json") for diagnostic in diagnostics
                    ],
                    "deterministic_operations": list(deterministic_operations),
                    "repair_request_chars": 0,
                    "repair_usage": TokenUsage().model_dump(mode="json"),
                    "binding_diagnostics": list(binding_diagnostics),
                    "segment_item_count": len(normalized.items),
                    "aggregate_item_count": len(aggregate.items),
                    "aggregate_page_range": aggregate.source.page_range.model_dump(
                        mode="json"
                    )
                    if aggregate.source.page_range is not None
                    else None,
                }
                _write(prefix.with_suffix(".report.json"), report)
                print(json.dumps(report, ensure_ascii=False))
                return

        _progress("Building bounded CCEF-repair request...")
        repair_request = build_ccef_repair_request(
            repair_base,
            evidence.context,
            failure=repair_failure,
            trusted_context={
                "continuation": continuation.model_dump(mode="json"),
                "previous_page_text": list(inputs.previous_page_text),
            },
        )
        _write(
            prefix.with_suffix(".request.json"), repair_request.model_dump(mode="json")
        )
        if not args.execute and args.repair_response is None:
            print(
                json.dumps(
                    {
                        "status": "prepared",
                        "run_id": str(run.id),
                        "diagnostics": [
                            diagnostic.model_dump(mode="json")
                            for diagnostic in diagnostics
                        ],
                        "request_chars": sum(
                            len(message.content) for message in repair_request.messages
                        ),
                        "output_prefix": str(prefix),
                    },
                    ensure_ascii=False,
                )
            )
            return

        if args.repair_response is not None:
            _progress("Loading a retained CCEF-repair response...")
            repair_response = StructuredGenerationResponse.model_validate_json(
                args.repair_response.read_bytes()
            )
        else:
            provider = _active_provider(
                settings,
                None,
                thinking_enabled=False,
                json_output_enabled=True,
                invalid_response_recorder=_deepseek_invalid_response_recorder(
                    settings, inputs.source
                ),
            )
            _progress("Requesting one bounded CCEF repair...")
            repair_response = await provider.generate(repair_request)
        # Retain the paid response before any local gate can reject it.  This is
        # diagnostic state only; no SQL row or authoritative artifact changes.
        _write(
            prefix.with_suffix(".repair-response.json"),
            repair_response.model_dump(mode="json"),
        )
        _progress("Applying and validating the retained repair response...")
        repaired_response = apply_ccef_repair(
            repair_base,
            repair_response,
            evidence.context,
            failure=repair_failure,
        )
        binding_diagnostics, bound, normalized, aggregate = validate_candidate(
            repaired_response
        )
        _write(prefix.with_suffix(".repaired-raw.json"), bound.model_dump(mode="json"))
        _write(
            prefix.with_suffix(".normalized.json"), normalized.model_dump(mode="json")
        )
        _write(prefix.with_suffix(".aggregate.json"), aggregate.model_dump(mode="json"))
        statuses: dict[str, int] = {}
        for item in normalized.items:
            if not isinstance(item, MoveSequenceItemV1_1):
                continue
            for node in item.nodes:
                statuses[node.validation_status] = (
                    statuses.get(node.validation_status, 0) + 1
                )
        report = {
            "status": "validated",
            "run_id": str(run.id),
            "job_id": str(job.id),
            "source_response_sha256": hashlib.sha256(
                original.content.encode("utf-8")
            ).hexdigest(),
            "diagnostics": [
                diagnostic.model_dump(mode="json") for diagnostic in diagnostics
            ],
            "deterministic_operations": list(deterministic_operations),
            "repair_request_chars": sum(
                len(message.content) for message in repair_request.messages
            ),
            "repair_usage": repair_response.usage.model_dump(mode="json"),
            "binding_diagnostics": list(binding_diagnostics),
            "segment_item_count": len(normalized.items),
            "segment_move_statuses": statuses,
            "aggregate_item_count": len(aggregate.items),
            "aggregate_page_range": aggregate.source.page_range.model_dump(mode="json")
            if aggregate.source.page_range is not None
            else None,
        }
        _write(prefix.with_suffix(".report.json"), report)
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--output-prefix", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--execute",
        action="store_true",
        help="perform the single paid repair call; otherwise only prepare the request",
    )
    action.add_argument(
        "--repair-response",
        type=Path,
        help="replay one already retained StructuredGenerationResponse without network access",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
