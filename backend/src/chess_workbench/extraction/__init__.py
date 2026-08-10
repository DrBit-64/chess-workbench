"""Portable Chess Content Extraction Format (CCEF) v1.

This package is the provider- and consumer-neutral recognition contract
described by ADR 0010 and frozen by ``docs/architecture/ccef-v1.md``.

It deliberately imports only the standard library and Pydantic so the
models and JSON Schema remain portable.  The dependency direction is:
providers/OCR produce CCEF JSON, deterministic validation consumes it,
and a downstream ConsumerAdapter maps it into a website's own model.
"""

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
from .provider import (
    ProviderErrorCode,
    ScriptedStructuredGenerationProvider,
    StructuredGenerationProvider,
    StructuredGenerationProviderError,
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
    TokenUsage,
)

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
    "ProviderErrorCode",
    "ScriptedStructuredGenerationProvider",
    "StructuredGenerationProvider",
    "StructuredGenerationProviderError",
    "StructuredGenerationRequest",
    "StructuredGenerationResponse",
    "StructuredMessage",
    "TokenUsage",
]
