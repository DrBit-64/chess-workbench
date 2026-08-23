"""Continuation-context value model for incremental PDF extraction (ADR 0018).

ADR 0018 lets one logical source document continue from an accepted
baseline: a later provider request is handed an explicit catalog of legal
positions it may continue from.  This module implements only the pure
consumer-side half of that protocol:

- strict, frozen internal value models describing one continuation context;
- a deterministic projection of legal continuation anchors from one exact,
  locally normalized CCEF 1.1 baseline package.

The context performs no stitching, no merge, no trust establishment and no
I/O.  It is internal ChessWorkbench transport, not a new CCEF version, a
database schema or an API contract.  Later binding/composition code must
independently validate the exact baseline hash and every chess edge before
use.  The input package is never mutated.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .contracts import (
    ExtractionPackageV1_1,
    Fen,
    LocalId,
    MoveNode,
    MoveSequenceItemV1_1,
    PageRange,
    Sha256Hex,
    UciCandidate,
)
from .validation import normalize_chess_moves_v1_1

CCEF_CONTINUATION_CONTEXT_VERSION: Literal["chess-workbench/ccef-continuation-context/1.0"] = (
    "chess-workbench/ccef-continuation-context/1.0"
)

_MAX_PAGE = 20_000
_MAX_TAIL = 8
_ANCHOR_ID = r"^anchor-[1-9][0-9]*$"


def _canonical_package_bytes(package: ExtractionPackageV1_1) -> bytes:
    """Canonical CCEF bytes of one normalized package.

    The repository's accepted candidate format is compact, sorted-key,
    non-escaped UTF-8 JSON plus a single trailing newline; this must stay
    byte-for-byte identical to the canonical form used when committing
    normalized CCEF artifacts.
    """
    return (
        json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _check_page_relations(base_range: PageRange, next_range: PageRange) -> None:
    """Enforce the frozen continuation range relations.

    Shared by the model validator and the builder so direct construction and
    builder behavior cannot drift.  Check order is frozen: overlap first, then
    non-adjacency/gap, then the maximum page bound.
    """
    if next_range.start_page <= base_range.end_page:
        raise ValueError("next page range overlaps the base page range")
    if next_range.start_page != base_range.end_page + 1:
        raise ValueError("next page range is not adjacent to the base page range")
    if next_range.end_page > _MAX_PAGE:
        raise ValueError("next page range exceeds the maximum page number")


def _non_empty(min_length: int, max_length: int) -> StringConstraints:
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


def _non_null(value: str | None) -> str:
    assert value is not None
    return value


class _ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContinuationMove(_ContextModel):
    node_id: LocalId
    san: Annotated[str, _non_empty(1, 100)]
    uci: UciCandidate


class ContinuationAnchor(_ContextModel):
    id: Annotated[str, StringConstraints(pattern=_ANCHOR_ID, max_length=32)]
    sequence_id: LocalId
    after_node_id: LocalId | None
    position_fen: Fen
    path_tail: list[ContinuationMove] = Field(max_length=_MAX_TAIL)

    @model_validator(mode="after")
    def _check_tail_relation(self) -> ContinuationAnchor:
        if self.after_node_id is None:
            if self.path_tail:
                raise ValueError("root anchor must have an empty path tail")
        elif not self.path_tail or self.path_tail[-1].node_id != self.after_node_id:
            raise ValueError("node anchor path tail must end with the anchor node")
        return self


class ContinuationSequence(_ContextModel):
    sequence_id: LocalId
    title: Annotated[str, _non_empty(1, 2000)] | None = None
    anchors: list[ContinuationAnchor] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_anchor_relations(self) -> ContinuationSequence:
        if self.anchors[0].after_node_id is not None:
            raise ValueError("sequence root anchor must come first")
        seen: set[str] = set()
        for anchor in self.anchors:
            if anchor.after_node_id is not None:
                if anchor.after_node_id in seen:
                    raise ValueError("duplicate after_node_id within a sequence")
                seen.add(anchor.after_node_id)
            elif anchor is not self.anchors[0]:
                raise ValueError("sequence must have exactly one root anchor")
        return self


class CcefContinuationContext(_ContextModel):
    schema_version: Literal["chess-workbench/ccef-continuation-context/1.0"]
    base_package_id: UUID
    base_normalized_ccef_sha256: Sha256Hex
    source_ref: Annotated[str, _non_empty(1, 1024)]
    base_page_range: PageRange
    next_page_range: PageRange
    sequences: list[ContinuationSequence]

    @field_validator("base_package_id", mode="before")
    @classmethod
    def _uuid_instance_or_string(cls, value: Any) -> Any:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        raise ValueError("base_package_id must be a UUID instance or UUID string")

    @model_validator(mode="after")
    def _check_context_relations(self) -> CcefContinuationContext:
        _check_page_relations(self.base_page_range, self.next_page_range)
        sequence_ids = [sequence.sequence_id for sequence in self.sequences]
        if len(set(sequence_ids)) != len(sequence_ids):
            raise ValueError("duplicate sequence id")
        anchor_ids: list[str] = []
        for sequence in self.sequences:
            for anchor in sequence.anchors:
                if anchor.sequence_id != sequence.sequence_id:
                    raise ValueError("anchor sequence mismatch")
                anchor_ids.append(anchor.id)
        expected = [f"anchor-{index}" for index in range(1, len(anchor_ids) + 1)]
        if anchor_ids != expected:
            raise ValueError("anchor ids must be globally contiguous and unique")
        return self


def _node_move(node: MoveNode) -> ContinuationMove:
    san = _non_null(node.san_candidate)
    uci = _non_null(node.uci_candidate)
    return ContinuationMove(node_id=node.id, san=san, uci=uci)


def _project_sequence(
    sequence: MoveSequenceItemV1_1,
    first_anchor_index: int,
) -> tuple[ContinuationSequence, int] | None:
    """Project all anchors of one normalized sequence, or ``None``.

    A sequence is projected only when it has at least one eligible locally
    valid root node.  The first anchor is always the sequence root anchor;
    node anchors follow in source/topological order for every ``valid`` node
    whose complete parent chain is eligible and whose declared ``fen_before``
    matches the anchor position of its real parent.  Parents are never
    guessed from FENs.
    """
    valid_roots = [
        node
        for node in sequence.nodes
        if node.parent_id is None and node.validation_status == "valid"
    ]
    if not valid_roots:
        return None
    root_fen = _non_null(valid_roots[0].fen_before)

    eligible: dict[str, bool] = {}
    parent_position: dict[str, str] = {}
    tails: dict[str, list[MoveNode]] = {}
    anchors: list[ContinuationAnchor] = [
        ContinuationAnchor(
            id=f"anchor-{first_anchor_index}",
            sequence_id=sequence.id,
            after_node_id=None,
            position_fen=root_fen,
            path_tail=[],
        )
    ]
    next_anchor_index = first_anchor_index + 1

    for node in sequence.nodes:
        parent_id = node.parent_id
        if parent_id is None:
            chain_eligible = node.validation_status == "valid"
        else:
            chain_eligible = eligible.get(parent_id, False)
        if not chain_eligible or node.validation_status != "valid":
            eligible[node.id] = False
            continue
        fen_before = _non_null(node.fen_before)
        if parent_id is None:
            consistent = fen_before == root_fen
        else:
            consistent = fen_before == parent_position[parent_id]
        if not consistent:
            eligible[node.id] = False
            continue
        eligible[node.id] = True
        fen_after = _non_null(node.fen_after)
        parent_position[node.id] = fen_after
        if parent_id is None:
            parent_tail: list[MoveNode] = []
        else:
            parent_tail = tails[parent_id]
        tail = [*parent_tail, node][-_MAX_TAIL:]
        tails[node.id] = tail
        anchors.append(
            ContinuationAnchor(
                id=f"anchor-{next_anchor_index}",
                sequence_id=sequence.id,
                after_node_id=node.id,
                position_fen=fen_after,
                path_tail=[_node_move(item) for item in tail],
            )
        )
        next_anchor_index += 1

    return (
        ContinuationSequence(sequence_id=sequence.id, title=sequence.title, anchors=anchors),
        next_anchor_index,
    )


def build_ccef_continuation_context(
    package: ExtractionPackageV1_1,
    *,
    base_normalized_ccef_sha256: str,
    next_page_range: PageRange,
) -> CcefContinuationContext:
    """Build the hash-bound continuation context for one exact baseline.

    The baseline must be the exact locally normalized CCEF 1.1 package whose
    canonical JSON SHA-256 equals ``base_normalized_ccef_sha256``.  The
    supplied SHA is compared against the locally recomputed canonical hash of
    the proven normalized package: a well-formed but wrong value raises the
    fixed content-free ``ValueError``, while a malformed SHA still raises
    ``ValidationError`` from the returned strict model.  ``next_page_range``
    must continue immediately after the baseline source page range.  The input
    package is never repaired or mutated.
    """
    if type(package) is not ExtractionPackageV1_1:
        raise TypeError("package must be ExtractionPackageV1_1")
    if type(next_page_range) is not PageRange:
        raise TypeError("next_page_range must be PageRange")

    base_range = package.source.page_range
    if base_range is None:
        raise ValueError("base package must declare a source page range")
    _check_page_relations(base_range, next_page_range)

    normalized = normalize_chess_moves_v1_1(package)
    if normalized.model_dump(mode="json") != package.model_dump(mode="json"):
        raise ValueError("base package must be locally normalized")

    computed_sha = hashlib.sha256(_canonical_package_bytes(normalized)).hexdigest()

    sequences: list[ContinuationSequence] = []
    next_anchor_index = 1
    for item in package.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        projected = _project_sequence(item, next_anchor_index)
        if projected is None:
            continue
        sequence, next_anchor_index = projected
        sequences.append(sequence)

    context = CcefContinuationContext(
        schema_version=CCEF_CONTINUATION_CONTEXT_VERSION,
        base_package_id=package.package_id,
        base_normalized_ccef_sha256=base_normalized_ccef_sha256,
        source_ref=package.source.source_ref,
        base_page_range=PageRange(start_page=base_range.start_page, end_page=base_range.end_page),
        next_page_range=PageRange(
            start_page=next_page_range.start_page, end_page=next_page_range.end_page
        ),
        sequences=sequences,
    )
    if context.base_normalized_ccef_sha256 != computed_sha:
        raise ValueError("base normalized CCEF SHA-256 does not match package")
    return context


def compose_incremental_ccef(
    base: ExtractionPackageV1_1,
    incremental: ExtractionPackageV1_1,
    *,
    context: CcefContinuationContext,
    document_id: UUID,
) -> ExtractionPackageV1_1:
    """Graft one verified adjacent package onto a normalized document prefix.

    Continuation bindings are explicit and hash-bound.  The composer never
    guesses a parent from matching FENs: every continued sequence names one
    anchor from ``context``.  Independent items are appended in source order,
    while continued move trees and their annotation reading flow are folded
    into the named baseline sequence.
    """

    if type(base) is not ExtractionPackageV1_1:
        raise TypeError("base must be ExtractionPackageV1_1")
    if type(incremental) is not ExtractionPackageV1_1:
        raise TypeError("incremental must be ExtractionPackageV1_1")
    if type(context) is not CcefContinuationContext:
        raise TypeError("context must be CcefContinuationContext")
    if type(document_id) is not UUID:
        raise TypeError("document_id must be UUID")

    rebuilt_context = build_ccef_continuation_context(
        base,
        base_normalized_ccef_sha256=context.base_normalized_ccef_sha256,
        next_page_range=context.next_page_range,
    )
    if rebuilt_context != context:
        raise ValueError("continuation context does not match the base package")
    normalized_incremental = normalize_chess_moves_v1_1(incremental)
    if normalized_incremental.model_dump(mode="json") != incremental.model_dump(mode="json"):
        raise ValueError("incremental package must be locally normalized")
    if (
        incremental.source.source_ref != base.source.source_ref
        or incremental.source.media_type != base.source.media_type
        or incremental.source.language != base.source.language
        or incremental.source.page_range != context.next_page_range
    ):
        raise ValueError("incremental source does not continue the base package")

    document = deepcopy(base.model_dump(mode="json"))
    incoming = deepcopy(incremental.model_dump(mode="json"))
    document_items = document["items"]
    assert isinstance(document_items, list)
    incoming_items = incoming["items"]
    assert isinstance(incoming_items, list)
    sequences = {
        item["id"]: item
        for item in document_items
        if isinstance(item, dict) and item.get("kind") == "move_sequence"
    }
    existing_item_ids = {item["id"] for item in document_items if isinstance(item, dict)}
    anchors = {anchor.id: anchor for sequence in context.sequences for anchor in sequence.anchors}
    item_targets: dict[str, str] = {}
    node_targets: dict[tuple[str, str], str] = {}
    independent_items: list[dict[str, Any]] = []
    binding_index = 0

    for item in incoming_items:
        assert isinstance(item, dict)
        if item.get("kind") != "move_sequence":
            if item["id"] in existing_item_ids:
                raise ValueError("incremental item id collides with the base package")
            independent_items.append(item)
            existing_item_ids.add(item["id"])
            continue
        extensions = item.get("extensions")
        binding = (
            extensions.get("chess-workbench.continuation") if isinstance(extensions, dict) else None
        )
        if binding is None:
            if item["id"] in existing_item_ids:
                raise ValueError("incremental item id collides with the base package")
            independent_items.append(item)
            existing_item_ids.add(item["id"])
            continue
        if not isinstance(binding, dict) or set(binding) != {
            "base_normalized_ccef_sha256",
            "anchor_id",
        }:
            raise ValueError("incremental continuation binding is malformed")
        anchor_id = binding.get("anchor_id")
        anchor = anchors.get(anchor_id) if isinstance(anchor_id, str) else None
        if (
            binding.get("base_normalized_ccef_sha256") != context.base_normalized_ccef_sha256
            or anchor is None
        ):
            raise ValueError("incremental continuation binding is unknown")
        target = sequences.get(anchor.sequence_id)
        if target is None:
            raise ValueError("incremental continuation target is absent")

        binding_index += 1
        prefix = f"p{context.next_page_range.start_page}s{binding_index}"
        source_sequence_id = str(item["id"])
        item_targets[source_sequence_id] = anchor.sequence_id
        target_nodes = target["nodes"]
        target_annotations = target["annotations"]
        target_flow = target["reading_flow"]
        assert isinstance(target_nodes, list)
        assert isinstance(target_annotations, list)
        assert isinstance(target_flow, list)

        child_counts: dict[str | None, int] = {}
        for node in target_nodes:
            assert isinstance(node, dict)
            parent = node.get("parent_id")
            child_counts[parent] = child_counts.get(parent, 0) + 1

        source_nodes = item["nodes"]
        assert isinstance(source_nodes, list)
        node_map = {
            str(node["id"]): f"{prefix}n{index}"
            for index, node in enumerate(source_nodes, start=1)
            if isinstance(node, dict)
        }
        for node in source_nodes:
            assert isinstance(node, dict)
            old_id = str(node["id"])
            old_parent = node.get("parent_id")
            transformed = deepcopy(node)
            transformed["id"] = node_map[old_id]
            if old_parent is None:
                parent_id = anchor.after_node_id
                if transformed.get("fen_before") != anchor.position_fen:
                    raise ValueError("incremental root does not match its continuation anchor")
                transformed["parent_id"] = parent_id
                transformed["sibling_order"] = child_counts.get(parent_id, 0)
                child_counts[parent_id] = transformed["sibling_order"] + 1
            else:
                if old_parent not in node_map:
                    raise ValueError("incremental sequence has an unknown parent")
                transformed["parent_id"] = node_map[str(old_parent)]
            node_targets[(source_sequence_id, old_id)] = transformed["id"]
            target_nodes.append(transformed)

        source_annotations = item["annotations"]
        assert isinstance(source_annotations, list)
        annotation_map = {
            str(annotation["id"]): f"{prefix}a{index}"
            for index, annotation in enumerate(source_annotations, start=1)
            if isinstance(annotation, dict)
        }
        for annotation in source_annotations:
            assert isinstance(annotation, dict)
            transformed = deepcopy(annotation)
            old_id = str(annotation["id"])
            transformed["id"] = annotation_map[old_id]
            annotation_anchor = transformed.get("anchor")
            if isinstance(annotation_anchor, dict) and annotation_anchor.get("kind") == "move_node":
                old_node_id = str(annotation_anchor["node_id"])
                annotation_anchor["node_id"] = node_map[old_node_id]
            target_annotations.append(transformed)

        source_flow = item["reading_flow"]
        assert isinstance(source_flow, list)
        for entry in source_flow:
            assert isinstance(entry, dict)
            transformed = deepcopy(entry)
            if transformed.get("kind") == "move":
                transformed["node_id"] = node_map[str(transformed["node_id"])]
            else:
                transformed["annotation_id"] = annotation_map[str(transformed["annotation_id"])]
            target_flow.append(transformed)

        target_evidence = target["evidence"]
        assert isinstance(target_evidence, list)
        for evidence in item["evidence"]:
            if evidence not in target_evidence:
                target_evidence.append(deepcopy(evidence))
        assert isinstance(extensions, dict)
        target_extensions = target["extensions"]
        assert isinstance(target_extensions, dict)
        for key, value in extensions.items():
            if key == "chess-workbench.continuation":
                continue
            if key in target_extensions and target_extensions[key] != value:
                raise ValueError("incremental sequence extension conflicts with the base")
            target_extensions[key] = deepcopy(value)

    for item in independent_items:
        anchor = item.get("anchor")
        if isinstance(anchor, dict) and anchor.get("kind") == "move_node":
            source_sequence_id = str(anchor["sequence_id"])
            if source_sequence_id in item_targets:
                anchor["sequence_id"] = item_targets[source_sequence_id]
                anchor["node_id"] = node_targets[(source_sequence_id, str(anchor["node_id"]))]
        document_items.append(item)

    diagnostics = document["diagnostics"]
    assert isinstance(diagnostics, list)
    for diagnostic in incoming["diagnostics"]:
        assert isinstance(diagnostic, dict)
        transformed = deepcopy(diagnostic)
        source_item_id = transformed.get("item_id")
        if isinstance(source_item_id, str) and source_item_id in item_targets:
            transformed["item_id"] = item_targets[source_item_id]
            source_node_id = transformed.get("node_id")
            if isinstance(source_node_id, str):
                transformed["node_id"] = node_targets[(source_item_id, source_node_id)]
        diagnostics.append(transformed)

    source = document["source"]
    assert isinstance(source, dict)
    source["page_range"] = {
        "start_page": context.base_page_range.start_page,
        "end_page": context.next_page_range.end_page,
    }
    document["package_id"] = str(document_id)
    incremental_provenance = incremental.provenance
    document["provenance"] = {
        "created_at": incremental_provenance.created_at.isoformat().replace("+00:00", "Z"),
        "adapter_name": "chess-workbench-incremental-compose",
        "adapter_version": "1.0",
        "provider": None,
        "model": None,
        "request_sha256": None,
        "response_sha256": None,
    }
    return ExtractionPackageV1_1.model_validate(document)


__all__ = [
    "CCEF_CONTINUATION_CONTEXT_VERSION",
    "ContinuationMove",
    "ContinuationAnchor",
    "ContinuationSequence",
    "CcefContinuationContext",
    "build_ccef_continuation_context",
    "compose_incremental_ccef",
]
