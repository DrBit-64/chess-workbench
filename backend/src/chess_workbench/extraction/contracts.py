"""Strict Pydantic implementation of the CCEF v1 portable contract.

Field-level semantics are frozen by ``docs/architecture/ccef-v1.md``.
This module is the Python source of the deterministic Draft 2020-12 JSON
Schema artifact ``contracts/chess-content-extraction-v1.schema.json``.

Every object boundary uses ``extra="forbid"`` and strict typing.
Cross-referencing invariants (unique IDs, dangling anchors, sibling-order
contiguity, page-range containment) are enforced by package-level
validators.  This packet validates structure and references only; it does
not decide whether a FEN or move is chess-legal.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

CCEF_VERSION: Literal["chess-content-extraction/1.0"] = "chess-content-extraction/1.0"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "urn:chess-content-extraction:schema:1.0"

_LOCAL_ID = r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$"
_DIAGNOSTIC_CODE = r"^[a-z][a-z0-9_]{0,63}$"
_EXTENSION_KEY = r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$"
_SHA256 = r"^[0-9a-f]{64}$"
_UCI = r"^[a-h][1-8][a-h][1-8][qrbn]?$"


def _non_empty(min_length: int, max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


LocalId = Annotated[str, StringConstraints(pattern=_LOCAL_ID)]
DiagnosticCode = Annotated[str, StringConstraints(pattern=_DIAGNOSTIC_CODE)]
ExtensionKey = Annotated[str, StringConstraints(pattern=_EXTENSION_KEY)]
Sha256Hex = Annotated[str, StringConstraints(pattern=_SHA256)]
UciCandidate = Annotated[str, StringConstraints(pattern=_UCI)]


def _validate_fen(value: str) -> str:
    if len(value) > 200:
        raise ValueError("FEN exceeds 200 characters")
    if len(value.split()) != 6:
        raise ValueError("FEN must contain exactly six whitespace-separated fields")
    return value


Fen = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    AfterValidator(_validate_fen),
]


def _validate_bbox(value: list[float]) -> list[float]:
    if len(value) != 4:
        raise ValueError("bbox must contain exactly four numbers")
    x0, y0, x1, y1 = value
    if any(not 0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)):
        raise ValueError("bbox coordinates must lie in [0, 1]")
    if not (x0 < x1 and y0 < y1):
        raise ValueError("bbox must have positive area")
    return value


Bbox = Annotated[
    list[float],
    Field(min_length=4, max_length=4),
    AfterValidator(_validate_bbox),
]

Confidence = Annotated[float | None, Field(ge=0.0, le=1.0)]

# RFC3339 UTC date-time: explicit UTC designator only (Z/z/+00:00),
# no surrounding whitespace, optional fractional seconds. -00:00 and any
# non-zero offset are rejected. This single pattern is reused verbatim in
# the generated JSON Schema (see ccef_schema_document).
_DATETIME_STRING = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|z|\+00:00)$"
)


def _reject_non_finite(value: JsonValue) -> JsonValue:
    """Reject NaN/Infinity anywhere inside a JSON value."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("extension values must be finite JSON numbers")
        return value
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
        return value
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
        return value
    return value


FiniteJsonValue = Annotated[JsonValue, AfterValidator(_reject_non_finite)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# ---------------------------------------------------------------------------
# Evidence and diagnostics
# ---------------------------------------------------------------------------


class EvidenceRef(_StrictModel):
    page: Annotated[int, Field(ge=1)]
    bbox: Bbox | None = None
    start_offset: Annotated[int | None, Field(ge=0)] = None
    end_offset: Annotated[int | None, Field(gt=0)] = None
    fragment_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _check_offsets(self) -> EvidenceRef:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("text offsets must be both present or both absent")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and not (self.start_offset < self.end_offset)
        ):
            raise ValueError("start_offset must be less than end_offset")
        return self


class ExtractionWarning(_StrictModel):
    code: DiagnosticCode
    message: Annotated[str, _non_empty(1, 2000)]
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Diagnostic(_StrictModel):
    severity: Literal["info", "warning", "error"]
    code: DiagnosticCode
    message: Annotated[str, _non_empty(1, 4000)]
    item_id: LocalId | None = None
    node_id: LocalId | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Source descriptor
# ---------------------------------------------------------------------------


class PageRange(_StrictModel):
    start_page: Annotated[int, Field(ge=1)]
    end_page: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def _check_ordering(self) -> PageRange:
        if self.end_page < self.start_page:
            raise ValueError("end_page must be greater than or equal to start_page")
        return self


class SourceDescriptor(_StrictModel):
    source_ref: Annotated[str, _non_empty(1, 1024)]
    media_type: Annotated[str, _non_empty(1, 255)]
    language: Annotated[str, _non_empty(1, 35)] | None = None
    page_range: PageRange | None = None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Provenance(_StrictModel):
    created_at: datetime
    adapter_name: Annotated[str, _non_empty(1, 128)]
    adapter_version: Annotated[str, _non_empty(1, 64)]
    provider: Annotated[str, _non_empty(1, 128)] | None = None
    model: Annotated[str, _non_empty(1, 128)] | None = None
    request_sha256: Sha256Hex | None = None
    response_sha256: Sha256Hex | None = None

    @field_validator("created_at", mode="before")
    @classmethod
    def _datetime_instance_or_iso_string(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            # No strip(): the pattern anchors reject surrounding whitespace.
            if _DATETIME_STRING.match(value):
                return datetime.fromisoformat(value.replace("z", "Z").replace("Z", "+00:00"))
            raise ValueError("created_at must be an RFC3339 UTC date-time string")
        raise ValueError(
            "created_at must be a datetime instance or an RFC3339 UTC date-time string"
        )

    @field_validator("created_at")
    @classmethod
    def _utc_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be expressed in UTC")
        return value


# ---------------------------------------------------------------------------
# Common item fields and item variants
# ---------------------------------------------------------------------------


class _ItemBase(_StrictModel):
    id: LocalId
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence: Confidence = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    extensions: dict[ExtensionKey, FiniteJsonValue] = Field(default_factory=dict)


class HeadingItem(_ItemBase):
    kind: Literal["heading"]
    level: Annotated[int, Field(ge=1, le=6)]
    text: Annotated[str, _non_empty(1, 2000)]


class MoveNodeAnchor(_StrictModel):
    kind: Literal["move_node"]
    sequence_id: LocalId
    node_id: LocalId


class PositionAnchor(_StrictModel):
    kind: Literal["position"]
    fen: Fen


ProseAnchor = Annotated[MoveNodeAnchor | PositionAnchor, Field(discriminator="kind")]


class ProseItem(_ItemBase):
    kind: Literal["prose"]
    text: Annotated[str, _non_empty(1, 200_000)]
    text_format: Literal["plain", "markdown"] = "plain"
    anchor: ProseAnchor | None = None


class StartPosition(_StrictModel):
    kind: Literal["startpos"]


class FenPosition(_StrictModel):
    kind: Literal["fen"]
    fen: Fen


InitialPosition = Annotated[StartPosition | FenPosition, Field(discriminator="kind")]


class MoveNode(_StrictModel):
    id: LocalId
    parent_id: LocalId | None = None
    sibling_order: Annotated[int, Field(ge=0)]
    move_text: Annotated[str, _non_empty(1, 100)]
    move_number: Annotated[int | None, Field(ge=1)] = None
    side_to_move: Literal["w", "b"] | None = None
    san_candidate: Annotated[str, _non_empty(1, 100)] | None = None
    uci_candidate: UciCandidate | None = None
    nags: list[Annotated[int, Field(ge=0, le=255)]] = Field(default_factory=list)
    validation_status: Literal["unvalidated", "valid", "invalid", "ambiguous"] = "unvalidated"
    fen_before: Fen | None = None
    fen_after: Fen | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    confidence: Confidence = None
    warnings: list[ExtractionWarning] = Field(default_factory=list)
    extensions: dict[ExtensionKey, FiniteJsonValue] = Field(default_factory=dict)

    @field_validator("nags")
    @classmethod
    def _nags_unique(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("NAG values must be unique")
        return value

    @model_validator(mode="after")
    def _status_normalization_fields(self) -> MoveNode:
        normalization = ("san_candidate", "uci_candidate", "fen_before", "fen_after")
        if self.validation_status == "valid":
            for name in normalization:
                if getattr(self, name) is None:
                    raise ValueError(f"valid node requires {name}")
        elif self.validation_status == "unvalidated":
            for name in normalization:
                if getattr(self, name) is not None:
                    raise ValueError(f"unvalidated node forbids {name}")
        return self


class MoveSequenceItem(_ItemBase):
    kind: Literal["move_sequence"]
    title: Annotated[str, _non_empty(1, 2000)] | None = None
    initial_position: InitialPosition
    nodes: list[MoveNode] = Field(min_length=1)


class FigureItem(_ItemBase):
    kind: Literal["figure"]
    figure_type: Literal["chessboard", "photo", "illustration", "other"]
    caption: Annotated[str, _non_empty(1, 10_000)] | None = None
    alt_text: Annotated[str, _non_empty(1, 10_000)] | None = None
    position_fen_candidate: Annotated[str, _non_empty(1, 200)] | None = None


class UnresolvedItem(_ItemBase):
    kind: Literal["unresolved"]
    unresolved_type: Literal["text", "figure", "mixed"]
    reason_code: DiagnosticCode
    raw_text: Annotated[str, _non_empty(1, 200_000)] | None = None
    details: Annotated[str, _non_empty(1, 10_000)] | None = None

    @model_validator(mode="after")
    def _requires_text_or_details(self) -> UnresolvedItem:
        if self.raw_text is None and self.details is None:
            raise ValueError("unresolved item requires raw_text or details")
        return self


ExtractionItem = Annotated[
    HeadingItem | ProseItem | MoveSequenceItem | FigureItem | UnresolvedItem,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------


class ExtractionPackage(_StrictModel):
    schema_version: Literal["chess-content-extraction/1.0"]
    package_id: UUID
    source: SourceDescriptor
    items: list[ExtractionItem] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    provenance: Provenance
    extensions: dict[ExtensionKey, FiniteJsonValue] = Field(default_factory=dict)

    @field_validator("package_id", mode="before")
    @classmethod
    def _uuid_instance_or_string(cls, value: Any) -> Any:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        raise ValueError("package_id must be a UUID instance or UUID string")

    def _all_evidence(self) -> list[EvidenceRef]:
        refs: list[EvidenceRef] = []
        for item in self.items:
            refs.extend(item.evidence)
            for warning in item.warnings:
                refs.extend(warning.evidence)
            if isinstance(item, MoveSequenceItem):
                for node in item.nodes:
                    refs.extend(node.evidence)
                    for warning in node.warnings:
                        refs.extend(warning.evidence)
        for diagnostic in self.diagnostics:
            refs.extend(diagnostic.evidence)
        return refs

    @model_validator(mode="after")
    def _referential_integrity(self) -> ExtractionPackage:
        item_ids: set[str] = set()
        sequences: dict[str, MoveSequenceItem] = {}
        for item in self.items:
            if item.id in item_ids:
                raise ValueError(f"duplicate item id {item.id!r}")
            item_ids.add(item.id)
            if isinstance(item, MoveSequenceItem):
                sequences[item.id] = item

        page_range = self.source.page_range
        if page_range is not None:
            for ref in self._all_evidence():
                if not (page_range.start_page <= ref.page <= page_range.end_page):
                    raise ValueError(
                        f"evidence page {ref.page} outside declared page range "
                        f"{page_range.start_page}..{page_range.end_page}"
                    )

        for item in self.items:
            if isinstance(item, ProseItem) and isinstance(item.anchor, MoveNodeAnchor):
                sequence = sequences.get(item.anchor.sequence_id)
                if sequence is None:
                    raise ValueError(
                        f"dangling move_node anchor sequence {item.anchor.sequence_id!r}"
                    )
                if not any(node.id == item.anchor.node_id for node in sequence.nodes):
                    raise ValueError(f"dangling move_node anchor node {item.anchor.node_id!r}")

        for diagnostic in self.diagnostics:
            if diagnostic.item_id is not None and diagnostic.item_id not in item_ids:
                raise ValueError(f"diagnostic item_id {diagnostic.item_id!r} does not resolve")
            if diagnostic.node_id is not None:
                if diagnostic.item_id is None:
                    raise ValueError("diagnostic node_id requires item_id")
                sequence = sequences.get(diagnostic.item_id)
                if sequence is None:
                    raise ValueError(
                        f"diagnostic node_id requires a move_sequence item {diagnostic.item_id!r}"
                    )
                if not any(node.id == diagnostic.node_id for node in sequence.nodes):
                    raise ValueError(
                        f"diagnostic node_id {diagnostic.node_id!r} not in sequence "
                        f"{diagnostic.item_id!r}"
                    )

        for sequence_id, sequence in sequences.items():
            self._check_move_tree(sequence_id, sequence)
        return self

    @staticmethod
    def _check_move_tree(sequence_id: str, sequence: MoveSequenceItem) -> None:
        node_ids: set[str] = set()
        sibling_orders: dict[str | None, list[int]] = {}
        for node in sequence.nodes:
            if node.id in node_ids:
                raise ValueError(f"duplicate node id {node.id!r} in sequence {sequence_id!r}")
            # parent must have appeared before the current node: check before
            # adding node.id so a self-parent is rejected too.
            if node.parent_id is not None and node.parent_id not in node_ids:
                raise ValueError(
                    f"dangling or forward parent {node.parent_id!r} for node "
                    f"{node.id!r} in sequence {sequence_id!r}"
                )
            node_ids.add(node.id)
            sibling_orders.setdefault(node.parent_id, []).append(node.sibling_order)
        for parent, orders in sibling_orders.items():
            if sorted(orders) != list(range(len(orders))):
                raise ValueError(
                    f"non-contiguous sibling_order under parent {parent!r} "
                    f"in sequence {sequence_id!r}"
                )


# ---------------------------------------------------------------------------
# Deterministic JSON Schema artifact
# ---------------------------------------------------------------------------


def ccef_schema_document() -> dict[str, Any]:
    """Return the portable Draft 2020-12 schema as a plain dict."""
    schema = ExtractionPackage.model_json_schema()
    _close_extension_maps(schema)
    # Expose the same UTC-only restriction on the created_at property that
    # the runtime validator enforces; format: date-time is retained.
    created_at = schema["$defs"]["Provenance"]["properties"]["created_at"]
    created_at["pattern"] = _DATETIME_STRING.pattern
    schema["$schema"] = SCHEMA_DIALECT
    schema["$id"] = SCHEMA_ID
    schema["title"] = "Chess Content Extraction Format v1"
    return schema


def _close_extension_maps(value: Any) -> None:
    """Make the key constraint on every namespaced extension map exhaustive."""
    if isinstance(value, dict):
        pattern_properties = value.get("patternProperties")
        if isinstance(pattern_properties, dict) and set(pattern_properties) == {_EXTENSION_KEY}:
            value["additionalProperties"] = False
        for child in value.values():
            _close_extension_maps(child)
    elif isinstance(value, list):
        for child in value:
            _close_extension_maps(child)


def ccef_schema_canonical_json() -> str:
    """Canonical schema bytes per ccef-v1.md section 'Identity and canonical Schema'."""
    return (
        json.dumps(
            ccef_schema_document(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
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
]
