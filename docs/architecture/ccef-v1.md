# CCEF v1 normative contract

This document is the field-level specification for ADR 0010. Keywords **MUST**, **MUST NOT**,
**SHOULD** and **MAY** are normative. The public media representation is UTF-8 JSON.

## Identity and canonical Schema

- Version literal: `chess-content-extraction/1.0`.
- JSON Schema dialect: `https://json-schema.org/draft/2020-12/schema`.
- JSON Schema ID: `urn:chess-content-extraction:schema:1.0`.
- Checked-in artifact: `contracts/chess-content-extraction-v1.schema.json`.
- Canonical Schema bytes are produced by
  `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"`.
- Every object rejects unknown fields. Non-discriminator defaults MAY be omitted on input and MUST
  appear after a Pydantic `model_dump(mode="json", exclude_none=False)` round trip. Every `kind`
  discriminator is required in portable JSON.

Local IDs MUST match `^[A-Za-z][A-Za-z0-9._:-]{0,127}$`. Diagnostic codes MUST match
`^[a-z][a-z0-9_]{0,63}$`. Extension keys MUST match
`^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$`; examples are `org.example` and
`com.example.reader`. All general text fields reject empty or whitespace-only values.

## ExtractionPackage

```text
ExtractionPackage
  schema_version: Literal["chess-content-extraction/1.0"]
  package_id: UUID
  source: SourceDescriptor
  items: list[ExtractionItem]                 # default [], order is authoritative
  diagnostics: list[Diagnostic]               # default []
  provenance: Provenance
  extensions: dict[ExtensionKey, JsonValue]   # default {}
```

Package invariants:

- item IDs are unique;
- every `EvidenceRef.page` is inside `source.page_range` when a range exists;
- move-node prose anchors resolve to a `move_sequence` item and a node inside that item;
- position anchors contain exactly six whitespace-separated FEN fields; chess legality is later;
- diagnostic `item_id` resolves when present; `node_id` requires an `item_id` that resolves to a
  move sequence and contains that node;
- unsupported version literals are rejected, not coerced.

## Source and evidence

```text
PageRange
  start_page: int >= 1
  end_page: int >= start_page

SourceDescriptor
  source_ref: str, 1..1024 chars              # opaque to the extraction core
  media_type: str, 1..255 chars               # e.g. application/pdf
  language: str | null, 1..35 chars
  page_range: PageRange | null

EvidenceRef
  page: int >= 1
  bbox: [float, float, float, float] | null    # x0,y0,x1,y1; each in [0,1]
  start_offset: int >= 0 | null
  end_offset: int > 0 | null
  fragment_sha256: str | null                 # exactly 64 lowercase hex chars
```

For bbox, `x0 < x1` and `y0 < y1`. Text offsets are both absent or both present and then
`start_offset < end_offset`. A page-only evidence reference is valid.

## Warnings and diagnostics

```text
ExtractionWarning
  code: DiagnosticCode
  message: str, 1..2000 chars
  evidence: list[EvidenceRef]                 # default []

Diagnostic
  severity: Literal["info", "warning", "error"]
  code: DiagnosticCode
  message: str, 1..4000 chars
  item_id: LocalId | null
  node_id: LocalId | null
  evidence: list[EvidenceRef]                 # default []
```

Item/node warnings intentionally omit severity: they are always warnings. Errors that affect the
package belong in `diagnostics`.

## Common item fields

Every item contains:

```text
id: LocalId
kind: discriminator literal
evidence: non-empty list[EvidenceRef]
confidence: float in [0,1] | null
warnings: list[ExtractionWarning]             # default []
extensions: dict[ExtensionKey, JsonValue]     # default {}
```

The five item variants are:

```text
HeadingItem(kind="heading")
  level: int in [1,6]
  text: str, 1..2000 chars

ProseItem(kind="prose")
  text: str, 1..200000 chars
  text_format: Literal["plain", "markdown"]  # default "plain"
  anchor: ProseAnchor | null

MoveSequenceItem(kind="move_sequence")
  title: str, 1..2000 chars | null
  initial_position: InitialPosition
  nodes: non-empty list[MoveNode]

FigureItem(kind="figure")
  figure_type: Literal["chessboard", "photo", "illustration", "other"]
  caption: str, 1..10000 chars | null
  alt_text: str, 1..10000 chars | null
  position_fen_candidate: str, 1..200 chars | null

UnresolvedItem(kind="unresolved")
  unresolved_type: Literal["text", "figure", "mixed"]
  reason_code: DiagnosticCode
  raw_text: str, 1..200000 chars | null
  details: str, 1..10000 chars | null
```

An unresolved item MUST have at least one of `raw_text` or `details`. A figure MAY contain neither
caption nor alt text because its mandatory evidence preserves the source location.

## Prose anchors

```text
MoveNodeAnchor
  kind: Literal["move_node"]
  sequence_id: LocalId
  node_id: LocalId

PositionAnchor
  kind: Literal["position"]
  fen: str, 1..200 chars                       # exactly six fields, legality later
```

An absent prose anchor means narrative content. Anchor objects reject all cross-variant fields.

## Initial position and move tree

```text
StartPosition
  kind: Literal["startpos"]

FenPosition
  kind: Literal["fen"]
  fen: str, 1..200 chars                       # exactly six fields, legality later

MoveNode
  id: LocalId
  parent_id: LocalId | null
  sibling_order: int >= 0
  move_text: str, 1..100 chars
  move_number: int >= 1 | null
  side_to_move: Literal["w", "b"] | null
  san_candidate: str, 1..100 chars | null
  uci_candidate: str | null                    # lowercase UCI regex below
  nags: list[int in 0..255]                    # default [], unique, source order
  validation_status: Literal["unvalidated", "valid", "invalid", "ambiguous"]
                                               # default "unvalidated"
  fen_before: str, 1..200 chars | null
  fen_after: str, 1..200 chars | null
  evidence: non-empty list[EvidenceRef]
  confidence: float in [0,1] | null
  warnings: list[ExtractionWarning]            # default []
  extensions: dict[ExtensionKey, JsonValue]    # default {}
```

UCI candidate regex:

```text
^[a-h][1-8][a-h][1-8][qrbn]?$
```

Within one sequence:

- node IDs are unique;
- nodes are topologically ordered: a non-null parent must already have appeared;
- for every parent identity, including the single root identity represented by null, sibling orders
  are unique and exactly `0..n-1` without gaps;
- sibling order 0 is the source mainline and higher values are source variations;
- NAG values are unique without sorting or deduplication by the parser;
- when status is `valid`, `san_candidate`, `uci_candidate`, `fen_before` and `fen_after` are all
  required; when status is `unvalidated`, all four authoritative normalization fields MUST be null;
- the provider decoder creates only `unvalidated` nodes. Only the later deterministic chess
  validator may create `valid`, `invalid` or `ambiguous` nodes.

The first contract packet validates these structural rules but does not import `python-chess` or
decide whether a FEN/move is legal.

## Provenance

```text
Provenance
  created_at: timezone-aware UTC datetime
  adapter_name: str, 1..128 chars
  adapter_version: str, 1..64 chars
  provider: str, 1..128 chars | null
  model: str, 1..128 chars | null
  request_sha256: 64 lowercase hex chars | null
  response_sha256: 64 lowercase hex chars | null
```

Non-UTC datetimes and naive datetimes are rejected. Token usage, billing, credentials, raw provider
payloads and consumer review state are deliberately outside CCEF v1.

## Import boundary

The Python implementation lives under `chess_workbench.extraction` only because Stage 8 begins in
the modular monolith. That package MUST NOT import:

- `chess_workbench.store`, `chess_workbench.services`, `chess_workbench.api` or
  `chess_workbench.schemas.domain`;
- Sanic or SQLAlchemy;
- provider clients, API key configuration or HTTP transports.

This restriction makes the checked-in JSON Schema and package models extractable into a separate
library or service later without changing their public semantics.
