"""Shared bounded recovery for standalone and incremental CCEF 1.1 generations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError

from .candidates import CcefCandidateError
from .contracts import ExtractionPackageV1_1
from .coverage import (
    CcefCoverageError,
    apply_ccef_coverage_supplement,
    build_ccef_coverage_supplement_request,
    ccef_coverage_chain_document,
    inspect_ccef_move_coverage,
)
from .decoder import CcefDecodeError
from .general_repair import (
    CcefRepairError,
    apply_ccef_repair,
    build_ccef_repair_request,
    canonicalize_ccef_response,
    ccef_repair_chain_document,
)
from .prompting import CcefPromptContext
from .provider import (
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationResponse,
)

FailureRecorder = Callable[
    [StructuredGenerationResponse, str, str, tuple[str, ...]], Awaitable[None]
]


@dataclass(frozen=True, slots=True)
class CcefRecoveryResult[RecoveryValue]:
    """One accepted value plus the immutable audit description of its recovery."""

    value: RecoveryValue
    original_response: StructuredGenerationResponse
    accepted_response: StructuredGenerationResponse
    provider_document: object
    changed: bool


class CcefRecoveryError(ValueError):
    """Sanitized terminal result from the shared recovery boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _diagnostics(error: BaseException) -> tuple[str, ...]:
    value = getattr(error, "diagnostics", ())
    if type(value) is not tuple:
        return ()
    return tuple(
        entry
        for entry in value
        if type(entry) is str and entry and "\n" not in entry and len(entry) <= 512
    )


def _initial_failure_code(error: BaseException) -> str:
    if isinstance(error, CcefDecodeError):
        return f"ccef_{error.code}"
    if isinstance(error, CcefCandidateError):
        return f"ccef_{error.code}"
    return "ccef_invalid_package"


async def recover_ccef_response[RecoveryValue](
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
    *,
    validate: Callable[[StructuredGenerationResponse], RecoveryValue],
    normalized_package: Callable[[RecoveryValue], ExtractionPackageV1_1],
    repair_provider: StructuredGenerationProvider,
    coverage_provider: StructuredGenerationProvider,
    record_failure: FailureRecorder,
    trusted_context: dict[str, object] | None = None,
) -> CcefRecoveryResult[RecoveryValue]:
    """Canonicalize, patch once if needed, supplement once if needed, and fully revalidate.

    The validator callback owns pipeline-specific trust, continuation, chess and composition
    checks.  This function owns only the common recovery policy and never accepts a result that
    the same callback did not validate after the final change.
    """

    try:
        repair_base, deterministic_operations = canonicalize_ccef_response(response)
    except CcefDecodeError:
        repair_base = response
        deterministic_operations = ()

    repair_response: StructuredGenerationResponse | None = None
    accepted_response = repair_base
    try:
        value = validate(accepted_response)
    except (CcefDecodeError, CcefCandidateError, ValidationError, ValueError) as initial_error:
        initial_code = _initial_failure_code(initial_error)
        await record_failure(
            response,
            initial_code,
            str(initial_error),
            _diagnostics(initial_error),
        )
        if isinstance(initial_error, CcefDecodeError) and initial_error.code in {
            "invalid_json",
            "truncated",
        }:
            raise CcefRecoveryError(
                initial_code,
                "Structured generation did not return a complete repairable JSON object",
            ) from None
        try:
            repair_request = build_ccef_repair_request(
                repair_base,
                context,
                failure=initial_error,
                trusted_context=trusted_context,
            )
        except (CcefDecodeError, CcefRepairError):
            raise CcefRecoveryError(
                initial_code,
                "Structured generation content is not a repairable CCEF package",
            ) from None
        try:
            repair_response = await repair_provider.generate(repair_request)
        except StructuredGenerationProviderError:
            raise CcefRecoveryError(
                "ccef_repair_failed",
                "CCEF repair could not be generated",
            ) from None
        try:
            accepted_response = apply_ccef_repair(
                repair_base,
                repair_response,
                context,
                failure=initial_error,
            )
            value = validate(accepted_response)
        except (
            CcefDecodeError,
            CcefCandidateError,
            CcefRepairError,
            ValidationError,
            ValueError,
        ) as error:
            await record_failure(
                repair_response,
                "ccef_repair_failed",
                str(error),
                _diagnostics(error),
            )
            raise CcefRecoveryError(
                "ccef_repair_failed",
                "CCEF repair did not pass local validation",
            ) from None

    provider_document: object = response.model_dump(mode="json")
    if deterministic_operations or repair_response is not None:
        provider_document = ccef_repair_chain_document(
            response,
            accepted_response,
            deterministic_operations=deterministic_operations,
            repair=repair_response,
            repair_base=repair_base,
        )

    package = normalized_package(value)
    coverage_report = inspect_ccef_move_coverage(package, context)
    coverage_response: StructuredGenerationResponse | None = None
    if coverage_report.gaps:
        coverage_base = accepted_response
        try:
            coverage_request = build_ccef_coverage_supplement_request(
                coverage_base,
                context,
                coverage_report,
                package,
            )
            coverage_response = await coverage_provider.generate(coverage_request)
            accepted_response = apply_ccef_coverage_supplement(
                coverage_base,
                coverage_response,
                context,
                coverage_report,
                package,
            )
            value = validate(accepted_response)
            if inspect_ccef_move_coverage(normalized_package(value), context).gaps:
                raise CcefCoverageError(
                    "coverage_incomplete",
                    "CCEF coverage supplement left numbered move gaps",
                )
        except StructuredGenerationProviderError:
            raise CcefRecoveryError(
                "ccef_coverage_repair_failed",
                "Missing CCEF variations could not be generated",
            ) from None
        except (
            CcefCandidateError,
            CcefCoverageError,
            CcefDecodeError,
            ValidationError,
            ValueError,
        ) as error:
            if coverage_response is not None:
                await record_failure(
                    coverage_response,
                    "ccef_coverage_repair_failed",
                    str(error),
                    _diagnostics(error),
                )
            raise CcefRecoveryError(
                "ccef_coverage_repair_failed",
                "Missing CCEF variations did not pass local validation",
            ) from None
        assert coverage_response is not None
        provider_document = ccef_coverage_chain_document(
            provider_document,
            accepted_response,
            coverage_response,
            coverage_report,
        )

    changed = bool(deterministic_operations or repair_response is not None or coverage_response)
    return CcefRecoveryResult(
        value=value,
        original_response=response,
        accepted_response=accepted_response,
        provider_document=provider_document,
        changed=changed,
    )


__all__ = [
    "CcefRecoveryError",
    "CcefRecoveryResult",
    "recover_ccef_response",
]
