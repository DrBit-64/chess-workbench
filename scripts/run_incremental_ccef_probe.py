#!/usr/bin/env python3
"""Run one paid, output-first incremental CCEF probe against local PDF evidence.

This operator tool intentionally stops before database commit or UI work.  It
loads one accepted CCEF 1.1 baseline, renders the adjacent page range, sends a
single continuation-aware request, and preserves every useful debug artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from chess_workbench.config import Settings, load_deepseek_api_key
from chess_workbench.extraction.candidates import _bind_fragment_evidence
from chess_workbench.extraction.contracts import (
    ExtractionPackageV1_1,
    FenPosition,
    MoveSequenceItemV1_1,
    PageRange,
    ccef_v1_1_schema_document,
)
from chess_workbench.extraction.decoder import decode_extraction_response_v1_1
from chess_workbench.extraction.deepseek import DeepSeekV4FlashProvider
from chess_workbench.extraction.evidence import (
    NormalizedBox,
    RenderProfile,
    SourceEvidenceFragment,
    source_fragment_sha256,
)
from chess_workbench.extraction.incremental import (
    CcefContinuationContext,
    build_ccef_continuation_context,
)
from chess_workbench.extraction.pdfium import PdfiumPageRenderer
from chess_workbench.extraction.prompting import (
    CcefPromptContext,
    PromptEvidenceFragment,
    PromptEvidencePage,
    build_ccef_v1_1_semantic_generation_request,
)
from chess_workbench.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
)
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.services.source_storage import (
    read_verified_content_addressed_bytes,
)
from chess_workbench.store.database import Database
from chess_workbench.store.models import (
    ExtractionArtifact,
    ExtractionRun,
    Job,
    PdfAsset,
    SourceFile,
)
from sqlalchemy import select

_DEFAULT_BASE_RUN = UUID("4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a")
_BINDING_EXTENSION_KEY = "chess-workbench.continuation"
_INCREMENTAL_RULES = """\
This is an incremental extraction request. The evidence pages are new; the continuation context
and previous-page tail are trusted context-only data and must never be cited as new evidence.
Do not repeat moves already present in the continuation path tails.
For every move_sequence that continues a prior sequence, choose the exact legal anchor where its
first printed move is played. Set that sequence's initial_position to kind \"fen\" with exactly the
anchor position_fen, and set item.extensions[\"chess-workbench.continuation\"] to exactly
{\"base_normalized_ccef_sha256\": <context hash>, \"anchor_id\": <chosen anchor id>}.
Different printed continuations may choose different anchors, including a main line and an earlier
alternative. Never merge them merely because they belong to the same game; the later local binder
will graft each sequence at its declared anchor.
For a genuinely new independent game or score, use its source-supported initial position and leave
item.extensions empty. All top-level package extensions must remain empty.
Only new-page source fragments may appear in EvidenceRef values. Return one CCEF 1.1 JSON object.
"""


@dataclass(frozen=True, slots=True)
class _ProbeInput:
    base_package: ExtractionPackageV1_1
    base_sha256: str
    source_ref: str
    source_pdf: bytes
    render_profile: RenderProfile
    previous_page_text: tuple[str, ...]


def _json_bytes(value: Any, *, pretty: bool = False) -> bytes:
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


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


async def _load_probe_input(
    database: Database,
    settings: Settings,
    base_run_id: UUID,
) -> _ProbeInput:
    async with database.session() as session:
        row = (
            await session.execute(
                select(ExtractionRun, Job, PdfAsset, SourceFile)
                .join(Job, Job.id == ExtractionRun.job_id)
                .join(PdfAsset, PdfAsset.id == ExtractionRun.pdf_asset_id)
                .join(SourceFile, SourceFile.id == PdfAsset.source_file_id)
                .where(ExtractionRun.id == base_run_id)
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("accepted baseline run was not found")
        run, job, _asset, source = row
        if job.status != "succeeded" or run.pipeline_version != "pdf-extraction:v4":
            raise RuntimeError("baseline run is not an accepted CCEF v4 result")
        artifacts = list(
            await session.scalars(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.run_id == base_run_id
                )
            )
        )

    slots = {(artifact.kind, artifact.page_number): artifact for artifact in artifacts}
    normalized = slots.get(("normalized_ccef", None))
    previous = slots.get(("ocr_fragment", run.last_page))
    if normalized is None or previous is None:
        raise RuntimeError(
            "baseline normalized CCEF or previous-page evidence is missing"
        )

    normalized_bytes = await asyncio.to_thread(
        read_verified_content_addressed_bytes,
        settings.source_storage_root,
        relative_path=normalized.relative_path,
        expected_sha256=normalized.content_sha256,
        expected_size=normalized.byte_size,
        max_bytes=64 * 1024 * 1024,
    )
    package = ExtractionPackageV1_1.model_validate_json(normalized_bytes)
    canonical = _json_bytes(package.model_dump(mode="json"))
    if (
        canonical != normalized_bytes
        or hashlib.sha256(canonical).hexdigest() != normalized.content_sha256
    ):
        raise RuntimeError("baseline normalized CCEF is not canonical or hash-bound")

    previous_bytes = await asyncio.to_thread(
        read_verified_content_addressed_bytes,
        settings.source_storage_root,
        relative_path=previous.relative_path,
        expected_sha256=previous.content_sha256,
        expected_size=previous.byte_size,
        max_bytes=64 * 1024 * 1024,
    )
    previous_document = json.loads(previous_bytes)
    previous_text = tuple(
        fragment["text"]
        for fragment in previous_document.get("fragments", [])
        if isinstance(fragment, dict) and isinstance(fragment.get("text"), str)
    )

    pdf_bytes = await asyncio.to_thread(
        read_verified_content_addressed_bytes,
        settings.source_storage_root,
        relative_path=source.relative_path,
        expected_sha256=source.sha256,
        expected_size=source.size_bytes,
        max_bytes=settings.pdf_max_bytes,
    )
    profile_value = (
        job.payload.get("profile", {}) if isinstance(job.payload, dict) else {}
    )
    render_value = (
        profile_value.get("render", {}) if isinstance(profile_value, dict) else {}
    )
    return _ProbeInput(
        base_package=package,
        base_sha256=normalized.content_sha256,
        source_ref=package.source.source_ref,
        source_pdf=pdf_bytes,
        render_profile=RenderProfile.model_validate(render_value),
        previous_page_text=previous_text,
    )


def _evidence_pages(
    probe: _ProbeInput,
    first_page: int,
    last_page: int,
) -> list[PromptEvidencePage]:
    renderer = PdfiumPageRenderer()
    pages: list[PromptEvidencePage] = []
    for physical_page in range(first_page, last_page + 1):
        rendered = renderer.render_page(
            probe.source_pdf, physical_page, probe.render_profile
        )
        if (
            sum(
                1
                for fragment in rendered.embedded_fragments
                for character in fragment.text
                if not character.isspace()
            )
            < probe.render_profile.embedded_text_min_chars
        ):
            raise RuntimeError(
                "incremental probe requires embedded text on every selected page"
            )
        entries: list[PromptEvidenceFragment] = []
        for order, fragment in enumerate(rendered.embedded_fragments):
            box = NormalizedBox(
                x0=fragment.box.x0 / rendered.width,
                y0=fragment.box.y0 / rendered.height,
                x1=fragment.box.x1 / rendered.width,
                y1=fragment.box.y1 / rendered.height,
            )
            source_fragment = SourceEvidenceFragment(
                physical_page=physical_page,
                box=box,
                text=fragment.text,
                origin="embedded_text",
                confidence=None,
                engine_name=rendered.renderer_name,
                engine_version=rendered.renderer_version,
                fragment_sha256=source_fragment_sha256(
                    physical_page,
                    box,
                    fragment.text,
                    "embedded_text",
                    rendered.renderer_name,
                    rendered.renderer_version,
                ),
            )
            entries.append(
                PromptEvidenceFragment(order=order, fragment=source_fragment)
            )
        pages.append(PromptEvidencePage(physical_page=physical_page, fragments=entries))
    return pages


def _incremental_request(
    prompt_context: CcefPromptContext,
    continuation_context: CcefContinuationContext,
    previous_page_text: tuple[str, ...],
) -> StructuredGenerationRequest:
    base = build_ccef_v1_1_semantic_generation_request(prompt_context)
    trusted_context = {
        "continuation_context": continuation_context.model_dump(mode="json"),
        "previous_page_tail_context_only": list(previous_page_text),
    }
    context_message = (
        _INCREMENTAL_RULES
        + "\nTrusted context:\n"
        + json.dumps(
            trusted_context,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return StructuredGenerationRequest(
        messages=[
            base.messages[0],
            StructuredMessage(role="system", content=context_message),
            base.messages[1],
        ],
        response_schema_name=base.response_schema_name,
        # Trusted continuation FENs are allowed even when the new pages do not print a FEN.
        response_schema=ccef_v1_1_schema_document(),
        max_output_tokens=base.max_output_tokens,
    )


def _check_metadata(package: ExtractionPackageV1_1, context: CcefPromptContext) -> None:
    if (
        package.package_id != context.package_id
        or package.source.source_ref != context.source_ref
        or package.source.media_type != context.media_type
        or package.source.language != context.language
        or package.source.page_range
        != PageRange(start_page=context.first_page, end_page=context.last_page)
        or package.provenance.created_at != context.created_at
        or package.provenance.adapter_name != "chess-workbench-ccef-prompt"
        or package.provenance.adapter_version != "1.1"
        or package.provenance.provider is not None
        or package.provenance.model is not None
        or package.provenance.request_sha256 is not None
        or package.provenance.response_sha256 is not None
        or package.extensions != {}
    ):
        raise RuntimeError(
            "incremental provider package metadata does not match the request"
        )


def _bind_continuations(
    package: ExtractionPackageV1_1,
    continuation_context: CcefContinuationContext,
) -> tuple[ExtractionPackageV1_1, list[dict[str, str]], int]:
    bound_package = package.model_copy(deep=True)
    anchors = {
        anchor.id: anchor
        for sequence in continuation_context.sequences
        for anchor in sequence.anchors
    }
    bindings: list[dict[str, str]] = []
    repaired_initial_positions = 0
    for item in bound_package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        value = item.extensions.get(_BINDING_EXTENSION_KEY)
        if value is None:
            continue
        if not isinstance(value, dict) or set(value) != {
            "base_normalized_ccef_sha256",
            "anchor_id",
        }:
            raise RuntimeError(
                f"sequence {item.id} has a malformed continuation binding"
            )
        anchor_id = value.get("anchor_id")
        base_hash = value.get("base_normalized_ccef_sha256")
        anchor = anchors.get(anchor_id) if isinstance(anchor_id, str) else None
        if (
            base_hash != continuation_context.base_normalized_ccef_sha256
            or anchor is None
        ):
            raise RuntimeError(
                f"sequence {item.id} has an unknown continuation binding"
            )
        # The provider selects a hash-bound anchor ID. Its redundant FEN copy is
        # untrusted, so the local anchor is authoritative before chess validation.
        if (
            not isinstance(item.initial_position, FenPosition)
            or item.initial_position.fen != anchor.position_fen
        ):
            item.initial_position = FenPosition(kind="fen", fen=anchor.position_fen)
            repaired_initial_positions += 1
        bindings.append(
            {
                "sequence_id": item.id,
                "anchor_id": anchor.id,
                "base_sequence_id": anchor.sequence_id,
                "after_node_id": anchor.after_node_id or "<root>",
            }
        )
    if not bindings:
        raise RuntimeError("incremental response contains no continuation binding")
    return (
        ExtractionPackageV1_1.model_validate(bound_package.model_dump(mode="json")),
        bindings,
        repaired_initial_positions,
    )


def _report(
    package: ExtractionPackageV1_1,
    bindings: list[dict[str, str]],
    response: StructuredGenerationResponse,
    binding_diagnostics: tuple[str, ...],
    repaired_initial_positions: int,
) -> dict[str, Any]:
    sequences: list[dict[str, Any]] = []
    invalid = 0
    ambiguous = 0
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        statuses = [node.validation_status for node in item.nodes]
        invalid += statuses.count("invalid")
        ambiguous += statuses.count("ambiguous")
        sequences.append(
            {
                "id": item.id,
                "title": item.title,
                "initial_position": item.initial_position.model_dump(mode="json"),
                "continuation": item.extensions.get(_BINDING_EXTENSION_KEY),
                "node_count": len(item.nodes),
                "annotation_count": len(item.annotations),
                "status_counts": {
                    status: statuses.count(status)
                    for status in ("valid", "invalid", "ambiguous", "unvalidated")
                },
                "first_moves": [node.move_text for node in item.nodes[:8]],
                "last_moves": [node.move_text for node in item.nodes[-8:]],
            }
        )
    return {
        "provider": response.provider,
        "model": response.model,
        "finish_reason": response.finish_reason,
        "usage": response.usage.model_dump(mode="json"),
        "item_count": len(package.items),
        "sequence_count": len(sequences),
        "move_node_count": sum(sequence["node_count"] for sequence in sequences),
        "invalid_move_count": invalid,
        "ambiguous_move_count": ambiguous,
        "bindings": bindings,
        "repaired_initial_position_count": repaired_initial_positions,
        "evidence_binding_diagnostics": list(binding_diagnostics),
        "sequences": sequences,
        "requires_human_review": bool(invalid or ambiguous),
    }


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    database = Database(settings.database_url)
    prefix = Path(args.output_prefix)
    try:
        probe = await _load_probe_input(database, settings, args.base_run)
        next_range = PageRange(start_page=args.first_page, end_page=args.last_page)
        continuation = build_ccef_continuation_context(
            probe.base_package,
            base_normalized_ccef_sha256=probe.base_sha256,
            next_page_range=next_range,
        )
        pages = await asyncio.to_thread(
            _evidence_pages, probe, args.first_page, args.last_page
        )
        package_id = uuid5(
            NAMESPACE_URL,
            f"chess-workbench:incremental-probe:{probe.base_sha256}:{args.first_page}:{args.last_page}",
        )
        prompt_context = CcefPromptContext(
            package_id=package_id,
            created_at=datetime.now(UTC),
            source_ref=probe.source_ref,
            media_type="application/pdf",
            language=probe.base_package.source.language,
            first_page=args.first_page,
            last_page=args.last_page,
            pages=pages,
            max_output_tokens=settings.ccef_max_output_tokens,
            max_prompt_chars=settings.ccef_max_prompt_chars,
        )
        request = _incremental_request(
            prompt_context, continuation, probe.previous_page_text
        )
        _write(
            prefix.with_suffix(".context.json"),
            _json_bytes(continuation.model_dump(mode="json"), pretty=True),
        )
        _write(
            prefix.with_suffix(".request.json"),
            _json_bytes(request.model_dump(mode="json"), pretty=True),
        )
        if args.prepare_only:
            print(
                json.dumps(
                    {
                        "prepared": True,
                        "base_sha256": probe.base_sha256,
                        "page_range": [args.first_page, args.last_page],
                        "continuation_sequence_count": len(continuation.sequences),
                        "continuation_anchor_count": sum(
                            len(sequence.anchors) for sequence in continuation.sequences
                        ),
                        "evidence_fragment_count": sum(
                            len(page.fragments) for page in prompt_context.pages
                        ),
                        "message_character_count": sum(
                            len(message.content) for message in request.messages
                        ),
                    },
                    indent=2,
                )
            )
            return

        key = load_deepseek_api_key(settings)
        if key is None:
            raise RuntimeError("DeepSeek API key file is not configured")

        async def record_invalid(
            raw: bytes, status: int, diagnostics: tuple[str, ...]
        ) -> None:
            _write(prefix.with_suffix(".transport-invalid.bin"), raw)
            _write(
                prefix.with_suffix(".transport-invalid.json"),
                _json_bytes(
                    {"status": status, "diagnostics": list(diagnostics)}, pretty=True
                ),
            )

        provider = DeepSeekV4FlashProvider(
            api_key=key.get_secret_value(),
            timeout_seconds=settings.ccef_provider_timeout_seconds,
            max_output_tokens_limit=settings.ccef_max_output_tokens,
            thinking_enabled=True,
            invalid_response_recorder=record_invalid,
        )
        response = await provider.generate(request)
        _write(
            prefix.with_suffix(".provider-response.json"),
            _json_bytes(response.model_dump(mode="json"), pretty=True),
        )
        try:
            decoded = decode_extraction_response_v1_1(response)
            _write(
                prefix.with_suffix(".decoded.json"),
                _json_bytes(decoded.model_dump(mode="json"), pretty=True),
            )
            _check_metadata(decoded, prompt_context)
            bound, binding_diagnostics = _bind_fragment_evidence(
                decoded, prompt_context
            )
            if bound is None:
                raise RuntimeError(
                    "incremental response evidence could not be bound: "
                    + ", ".join(binding_diagnostics)
                )
            bound, bindings, repaired_initial_positions = _bind_continuations(
                bound, continuation
            )
            normalized = normalize_chess_moves_v1_1(bound)
            _write(
                prefix.with_suffix(".raw.json"),
                _json_bytes(bound.model_dump(mode="json"), pretty=True),
            )
            _write(
                prefix.with_suffix(".normalized.json"),
                _json_bytes(normalized.model_dump(mode="json"), pretty=True),
            )
            report = _report(
                normalized,
                bindings,
                response,
                binding_diagnostics,
                repaired_initial_positions,
            )
            _write(prefix.with_suffix(".report.json"), _json_bytes(report, pretty=True))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except Exception as error:
            diagnostics = getattr(error, "diagnostics", ())
            _write(
                prefix.with_suffix(".error.json"),
                _json_bytes(
                    {
                        "error_type": type(error).__name__,
                        "message": str(error),
                        "diagnostics": list(diagnostics),
                    },
                    pretty=True,
                ),
            )
            raise
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run", type=UUID, default=_DEFAULT_BASE_RUN)
    parser.add_argument("--first-page", type=int, default=324)
    parser.add_argument("--last-page", type=int, default=328)
    parser.add_argument(
        "--output-prefix",
        default="data/debug/stage8d-incremental-pages-324-328",
    )
    parser.add_argument(
        "--execute-paid-provider-call",
        action="store_true",
        help="required acknowledgement: this command performs exactly one paid provider call",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="render and preserve the request without calling the provider",
    )
    args = parser.parse_args()
    if args.execute_paid_provider_call == args.prepare_only:
        parser.error(
            "choose exactly one of --prepare-only or --execute-paid-provider-call"
        )
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
