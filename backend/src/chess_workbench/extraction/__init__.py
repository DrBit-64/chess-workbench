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
    SCHEMA_DIALECT,
    SCHEMA_ID,
    Diagnostic,
    EvidenceRef,
    ExtractionPackage,
    ExtractionWarning,
    FenPosition,
    FigureItem,
    HeadingItem,
    MoveNode,
    MoveNodeAnchor,
    MoveSequenceItem,
    PageRange,
    PositionAnchor,
    ProseItem,
    Provenance,
    SourceDescriptor,
    StartPosition,
    UnresolvedItem,
    ccef_schema_canonical_json,
    ccef_schema_document,
)
from .decoder import CcefDecodeError, CcefDecodeErrorCode, decode_extraction_response
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
    CcefPromptContext,
    CcefPromptError,
    CcefPromptErrorCode,
    PromptEvidenceFragment,
    PromptEvidencePage,
    build_ccef_generation_request,
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
    from .deepseek import DeepSeekV4FlashProvider
    from .validation import normalize_chess_moves


def __getattr__(name: str) -> Any:
    """Load integration-only exports without polluting contract imports."""
    if name == "DeepSeekV4FlashProvider":
        from .deepseek import DeepSeekV4FlashProvider

        return DeepSeekV4FlashProvider
    if name == "normalize_chess_moves":
        from .validation import normalize_chess_moves

        return normalize_chess_moves
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CCEF_VERSION",
    "SCHEMA_DIALECT",
    "SCHEMA_ID",
    "Diagnostic",
    "EvidenceRef",
    "ExtractionPackage",
    "ExtractionWarning",
    "FenPosition",
    "FigureItem",
    "HeadingItem",
    "MoveNode",
    "MoveNodeAnchor",
    "MoveSequenceItem",
    "PageRange",
    "PositionAnchor",
    "ProseItem",
    "Provenance",
    "SourceDescriptor",
    "StartPosition",
    "UnresolvedItem",
    "ccef_schema_canonical_json",
    "ccef_schema_document",
    "CcefDecodeError",
    "CcefDecodeErrorCode",
    "decode_extraction_response",
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
    "CcefPromptContext",
    "CcefPromptError",
    "CcefPromptErrorCode",
    "PromptEvidenceFragment",
    "PromptEvidencePage",
    "build_ccef_generation_request",
]
