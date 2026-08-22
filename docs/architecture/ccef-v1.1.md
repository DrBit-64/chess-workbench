# CCEF 1.1 annotated move-sequence profile

This document is normative for ADR 0017. CCEF 1.1 preserves every CCEF 1.0 rule except where this
document adds fields and cross-reference invariants to `move_sequence`.

## Identity

- Version literal: `chess-content-extraction/1.1`.
- JSON Schema dialect: `https://json-schema.org/draft/2020-12/schema`.
- JSON Schema ID: `urn:chess-content-extraction:schema:1.1`.
- Checked-in artifact: `contracts/chess-content-extraction-v1.1.schema.json`.
- CCEF 1.0 models, Schema bytes and artifacts remain unchanged.

Every object remains strict and rejects unknown fields. All inherited field constraints, evidence
rules, defaults, package references, diagnostic references, topology rules and normalization-state
rules are exactly those of `docs/architecture/ccef-v1.md`.

## Sequence annotation

```text
SequenceAnnotation
  id: LocalId
  text: str, 1..200000 chars
  text_format: Literal["plain", "markdown"]       # default "plain"
  anchor: SequenceAnnotationAnchor | null           # default null
  evidence: non-empty list[EvidenceRef]
  confidence: float in [0,1] | null
  warnings: list[ExtractionWarning]                 # default []
  extensions: dict[ExtensionKey, JsonValue]         # default {}

MoveNodeAnnotationAnchor
  kind: Literal["move_node"]
  node_id: LocalId
  relation: Literal["before", "after"]

PositionAnnotationAnchor
  kind: Literal["position"]
  fen: Fen                                           # exact six-field structural rule
```

`anchor=null` is allowed when a note belongs inside the source reading flow but cannot be bound to
one chess position without guessing. The move-node anchor is semantic; it does not control where
the note appears in source order. Annotation IDs are local to one sequence. Annotation evidence is
never inherited from the sequence or an adjacent move.

An annotation is one atomic source assertion, normally one sentence. This is a producer semantic
requirement, not a punctuation validation rule: consumers MUST NOT split annotations with a naive
period/ellipsis regular expression.

## Reading flow

```text
MoveFlowRef
  kind: Literal["move"]
  node_id: LocalId

AnnotationFlowRef
  kind: Literal["annotation"]
  annotation_id: LocalId

SequenceFlowEntry = MoveFlowRef | AnnotationFlowRef  # discriminator: kind
```

CCEF 1.1 replaces only the `MoveSequenceItem` shape in the extraction-item union:

```text
MoveSequenceItemV1_1(kind="move_sequence")
  # all CCEF 1.0 common item fields
  title: str, 1..2000 chars | null
  initial_position: InitialPosition
  nodes: non-empty list[MoveNode]
  annotations: list[SequenceAnnotation]              # default []
  reading_flow: non-empty list[SequenceFlowEntry]
```

Within one sequence:

1. node IDs are unique and retain all CCEF 1.0 topology invariants;
2. annotation IDs are unique and disjoint from node IDs;
3. every move-node annotation anchor resolves to a node in this sequence;
4. every flow reference resolves to the matching collection;
5. flow entry identities are unique;
6. filtering `reading_flow` to move entries yields exactly the `nodes` IDs in array order;
7. filtering `reading_flow` to annotation entries yields exactly the `annotations` IDs in array
   order.

The two exact-cover rules guarantee that source presentation cannot hide, duplicate or reorder a
move or annotation. Parent links and sibling order remain the sole chess-topology authority.
`reading_flow` is the sole sequence-internal source-presentation authority.

## Package rules

`ExtractionPackageV1_1` has the CCEF 1.0 package fields with the 1.1 version literal and an item
union containing `MoveSequenceItemV1_1`. Top-level prose move-node anchors and diagnostic node
references resolve against the 1.1 move sequence exactly as in 1.0. Evidence page-range checks also
include annotation evidence and annotation-warning evidence.

The provider decoder creates unvalidated moves as in 1.0. Contract validation does not import
`python-chess`, infer sentence boundaries, attach partial variations or derive FEN. Those actions
belong to later explicit producer/consumer stages.

## Portable synthetic oracle

Contract tests MUST use invented text and a legal synthetic tree demonstrating:

- a primary line through White's sixth move;
- an atomic note displayed after that move;
- an alternative White sixth move whose parent is the earlier common fifth-move node;
- at least one nested variation;
- a later primary Black sixth move whose parent remains the primary White sixth move;
- exact move/annotation flow coverage, evidence preservation and JSON round trip.

The oracle proves structure only. It MUST NOT contain user-book text, titles, page-specific special
cases or a real provider call.
