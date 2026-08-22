"""Portable Chess Content Extraction Format (CCEF) v1.

This package is the provider- and consumer-neutral recognition contract
described by ADR 0010 and frozen by ``docs/architecture/ccef-v1.md``.

The root namespace eagerly imports only the standard-library/Pydantic core.
The HTTP adapter and python-chess normalizer remain explicit lazy exports, so
importing the contract does not load either optional integration dependency.
The dependency direction is: providers/OCR produce CCEF JSON, deterministic
validation consumes it, and a downstream ConsumerAdapter maps it into a
website's own model.
"""

from typing import TYPE_CHECKING, Any

from .contracts import (
    CCEF_VERSION,
    CCEF_VERSION_1_1,
    SCHEMA_DIALECT,
    SCHEMA_ID,
    SCHEMA_ID_1_1,
    AnnotationFlowRef,
    Diagnostic,
    EvidenceRef,
    ExtractionItemV1_1,
    ExtractionPackage,
    ExtractionPackageV1_1,
    ExtractionWarning,
    FenPosition,
    FigureItem,
    HeadingItem,
    MoveFlowRef,
    MoveNode,
    MoveNodeAnchor,
    MoveNodeAnnotationAnchor,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    PageRange,
    PositionAnchor,
    PositionAnnotationAnchor,
    ProseItem,
    Provenance,
    SequenceAnnotation,
    SequenceAnnotationAnchor,
    SequenceFlowEntry,
    SourceDescriptor,
    StartPosition,
    UnresolvedItem,
    ccef_schema_canonical_json,
    ccef_schema_document,
    ccef_v1_1_schema_canonical_json,
    ccef_v1_1_schema_document,
)
from .decoder import (
    CcefDecodeError,
    CcefDecodeErrorCode,
    decode_extraction_response,
    decode_extraction_response_v1_1,
)
from .evidence import (
    EvidenceOrigin,
    NormalizedBox,
    OcrAdapter,
    OcrPageResult,
    OcrRequest,
    PdfEvidenceError,
    PdfPageRenderer,
    PixelBox,
    RenderedPage,
    RenderProfile,
    ScriptedOcrAdapter,
    SourceEvidenceFragment,
    TextFragment,
    source_fragment_sha256,
)
from .paddleocr import (
    PADDLE_OCR_RUNNER_PROTOCOL,
    PaddleOcrJsonAdapter,
    normalize_paddle_ocr_response,
)
from .pdfium import PdfiumPageRenderer
from .prompting import (
    CCEF_PROMPT_VERSION,
    CCEF_PROMPT_VERSION_1_1,
    CCEF_SEMANTIC_PROMPT_VERSION_1_1,
    CcefPromptContext,
    CcefPromptError,
    CcefPromptErrorCode,
    PromptEvidenceFragment,
    PromptEvidencePage,
    build_ccef_generation_request,
    build_ccef_v1_1_generation_request,
    build_ccef_v1_1_semantic_generation_request,
)
from .provider import (
    GenerationFinishReason,
    ProviderErrorCode,
    ScriptedStructuredGenerationProvider,
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
    TokenUsage,
)

if TYPE_CHECKING:
    from .candidates import (
        CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA,
        CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1,
        CcefCandidateArtifacts,
        CcefCandidateError,
        CcefCandidateErrorCode,
        CcefCandidateSummary,
        assemble_ccef_candidate_artifacts,
        assemble_ccef_candidate_artifacts_v1_1,
        assemble_ccef_candidate_artifacts_v1_1_semantic,
    )
    from .consolidation import consolidate_move_sequences, consolidate_move_sequences_v1_1
    from .deepseek import DeepSeekV4FlashProvider
    from .validation import normalize_chess_moves, normalize_chess_moves_v1_1


def __getattr__(name: str) -> Any:
    """Load integration-only exports without polluting contract imports."""
    if name == "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA":
        from .candidates import CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA

        return CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA
    if name == "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1":
        from .candidates import CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1

        return CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1
    if name == "CcefCandidateArtifacts":
        from .candidates import CcefCandidateArtifacts

        return CcefCandidateArtifacts
    if name == "CcefCandidateError":
        from .candidates import CcefCandidateError

        return CcefCandidateError
    if name == "CcefCandidateErrorCode":
        from .candidates import CcefCandidateErrorCode

        return CcefCandidateErrorCode
    if name == "CcefCandidateSummary":
        from .candidates import CcefCandidateSummary

        return CcefCandidateSummary
    if name == "assemble_ccef_candidate_artifacts":
        from .candidates import assemble_ccef_candidate_artifacts

        return assemble_ccef_candidate_artifacts
    if name == "assemble_ccef_candidate_artifacts_v1_1":
        from .candidates import assemble_ccef_candidate_artifacts_v1_1

        return assemble_ccef_candidate_artifacts_v1_1
    if name == "assemble_ccef_candidate_artifacts_v1_1_semantic":
        from .candidates import assemble_ccef_candidate_artifacts_v1_1_semantic

        return assemble_ccef_candidate_artifacts_v1_1_semantic
    if name == "DeepSeekV4FlashProvider":
        from .deepseek import DeepSeekV4FlashProvider

        return DeepSeekV4FlashProvider
    if name == "consolidate_move_sequences":
        from .consolidation import consolidate_move_sequences

        return consolidate_move_sequences
    if name == "consolidate_move_sequences_v1_1":
        from .consolidation import consolidate_move_sequences_v1_1

        return consolidate_move_sequences_v1_1
    if name == "normalize_chess_moves":
        from .validation import normalize_chess_moves

        return normalize_chess_moves
    if name == "normalize_chess_moves_v1_1":
        from .validation import normalize_chess_moves_v1_1

        return normalize_chess_moves_v1_1
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CCEF_VERSION",
    "CCEF_VERSION_1_1",
    "SCHEMA_DIALECT",
    "SCHEMA_ID",
    "SCHEMA_ID_1_1",
    "AnnotationFlowRef",
    "Diagnostic",
    "EvidenceRef",
    "ExtractionItemV1_1",
    "ExtractionPackage",
    "ExtractionPackageV1_1",
    "ExtractionWarning",
    "FenPosition",
    "FigureItem",
    "HeadingItem",
    "MoveFlowRef",
    "MoveNode",
    "MoveNodeAnchor",
    "MoveNodeAnnotationAnchor",
    "MoveSequenceItem",
    "MoveSequenceItemV1_1",
    "PageRange",
    "PositionAnchor",
    "PositionAnnotationAnchor",
    "ProseItem",
    "Provenance",
    "SequenceAnnotation",
    "SequenceAnnotationAnchor",
    "SequenceFlowEntry",
    "SourceDescriptor",
    "StartPosition",
    "UnresolvedItem",
    "ccef_schema_canonical_json",
    "ccef_schema_document",
    "ccef_v1_1_schema_canonical_json",
    "ccef_v1_1_schema_document",
    "CcefDecodeError",
    "CcefDecodeErrorCode",
    "decode_extraction_response",
    "decode_extraction_response_v1_1",
    "consolidate_move_sequences",
    "consolidate_move_sequences_v1_1",
    "normalize_chess_moves_v1_1",
    "EvidenceOrigin",
    "NormalizedBox",
    "OcrAdapter",
    "OcrPageResult",
    "OcrRequest",
    "PdfEvidenceError",
    "PdfPageRenderer",
    "PdfiumPageRenderer",
    "PADDLE_OCR_RUNNER_PROTOCOL",
    "PaddleOcrJsonAdapter",
    "normalize_paddle_ocr_response",
    "PixelBox",
    "RenderedPage",
    "RenderProfile",
    "ScriptedOcrAdapter",
    "SourceEvidenceFragment",
    "TextFragment",
    "source_fragment_sha256",
    "DeepSeekV4FlashProvider",
    "normalize_chess_moves",
    "GenerationFinishReason",
    "ProviderErrorCode",
    "ScriptedStructuredGenerationProvider",
    "StructuredGenerationProvider",
    "StructuredGenerationProviderError",
    "StructuredGenerationRequest",
    "StructuredGenerationResponse",
    "StructuredMessage",
    "TokenUsage",
    "CCEF_PROMPT_VERSION",
    "CCEF_PROMPT_VERSION_1_1",
    "CCEF_SEMANTIC_PROMPT_VERSION_1_1",
    "CcefPromptContext",
    "CcefPromptError",
    "CcefPromptErrorCode",
    "PromptEvidenceFragment",
    "PromptEvidencePage",
    "build_ccef_generation_request",
    "build_ccef_v1_1_generation_request",
    "build_ccef_v1_1_semantic_generation_request",
    "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA",
    "CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1",
    "CcefCandidateArtifacts",
    "CcefCandidateError",
    "CcefCandidateErrorCode",
    "CcefCandidateSummary",
    "assemble_ccef_candidate_artifacts",
    "assemble_ccef_candidate_artifacts_v1_1",
    "assemble_ccef_candidate_artifacts_v1_1_semantic",
]
