"""Bounded repair protocol for a locally retained CCEF 1.1 response.

The repair provider is never asked to regenerate source content.  It receives
only a compact topology snapshot, deterministic local diagnostics and the
trusted source fragments cited by the affected sequences.  Its authority is
limited to changing ``parent_id`` and ``sibling_order`` of existing nodes.
The original reading flow remains the source-presentation authority; local
code reorders the parallel node/annotation arrays to that flow and then the
ordinary CCEF and python-chess gates run again.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Annotated, Any, Literal, Self

import chess
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from .contracts import (
    ExtractionPackageV1_1,
    LocalId,
    MoveSequenceItemV1_1,
    Sha256Hex,
)
from .decoder import CcefDecodeError, _parse_payload
from .prompting import CcefPromptContext
from .provider import (
    StructuredGenerationRequest,
    StructuredGenerationResponse,
    StructuredMessage,
)
from .validation import _clean_move_token, normalize_chess_moves_v1_1

CCEF_TOPOLOGY_REPAIR_SCHEMA = "chess-workbench/ccef-topology-repair/1.0"
_REPAIR_SCHEMA_NAME = "chess_workbench_ccef_topology_repair_v1"
_MAX_REPAIR_OUTPUT_TOKENS = 16_384


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CcefNodeTopologyUpdate(_StrictModel):
    node_id: LocalId
    parent_id: LocalId | None
    sibling_order: Annotated[int, Field(ge=0)]


class CcefSequenceTopologyRepair(_StrictModel):
    sequence_id: LocalId
    node_updates: list[CcefNodeTopologyUpdate] = Field(default_factory=list, max_length=512)

    @model_validator(mode="after")
    def updates_are_unique(self) -> Self:
        ids = [update.node_id for update in self.node_updates]
        if len(ids) != len(set(ids)):
            raise ValueError("node topology updates must be unique")
        return self


class CcefTopologyRepair(_StrictModel):
    repair_schema: Literal["chess-workbench/ccef-topology-repair/1.0"]
    base_response_sha256: Sha256Hex
    sequences: list[CcefSequenceTopologyRepair] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def sequences_are_unique(self) -> Self:
        ids = [sequence.sequence_id for sequence in self.sequences]
        if len(ids) != len(set(ids)):
            raise ValueError("sequence topology repairs must be unique")
        return self


class CcefRepairError(ValueError):
    """Fixed, non-sensitive failure raised when bounded repair is unavailable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _response_sha256(response: StructuredGenerationResponse) -> str:
    return hashlib.sha256(response.content.encode("utf-8")).hexdigest()


def _sequence_members(
    sequence: dict[str, Any],
) -> tuple[list[str], list[str], list[str], list[str]]:
    nodes = sequence.get("nodes")
    annotations = sequence.get("annotations", [])
    flow = sequence.get("reading_flow")
    if (
        not isinstance(nodes, list)
        or not isinstance(annotations, list)
        or not isinstance(flow, list)
    ):
        raise CcefRepairError("not_repairable", "CCEF failure is not a topology-only repair case")
    node_ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    annotation_ids = [item.get("id") for item in annotations if isinstance(item, dict)]
    move_refs = [
        entry.get("node_id")
        for entry in flow
        if isinstance(entry, dict) and entry.get("kind") == "move"
    ]
    annotation_refs = [
        entry.get("annotation_id")
        for entry in flow
        if isinstance(entry, dict) and entry.get("kind") == "annotation"
    ]
    collections = (node_ids, annotation_ids, move_refs, annotation_refs)
    if any(any(type(value) is not str for value in values) for values in collections):
        raise CcefRepairError("not_repairable", "CCEF failure is not a topology-only repair case")
    return node_ids, annotation_ids, move_refs, annotation_refs  # type: ignore[return-value]


def _affected_sequence_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise CcefRepairError("not_repairable", "CCEF failure is not a topology-only repair case")
    affected: list[str] = []
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "move_sequence":
            continue
        sequence_id = item.get("id")
        if type(sequence_id) is not str:
            raise CcefRepairError(
                "not_repairable", "CCEF failure is not a topology-only repair case"
            )
        node_ids, annotation_ids, move_refs, annotation_refs = _sequence_members(item)
        if (
            len(node_ids) != len(set(node_ids))
            or len(annotation_ids) != len(set(annotation_ids))
            or len(move_refs) != len(set(move_refs))
            or len(annotation_refs) != len(set(annotation_refs))
            or Counter(node_ids) != Counter(move_refs)
            or Counter(annotation_ids) != Counter(annotation_refs)
        ):
            raise CcefRepairError(
                "not_repairable", "CCEF failure is not a topology-only repair case"
            )
        if node_ids != move_refs or annotation_ids != annotation_refs:
            affected.append(sequence_id)
    if not affected:
        raise CcefRepairError("not_repairable", "CCEF failure is not a topology-only repair case")
    try:
        ExtractionPackageV1_1.model_validate(payload)
    except ValidationError as error:
        messages = [
            detail.get("msg")
            for detail in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        ]
        if not messages or any(
            type(message) is not str
            or not (
                message.startswith("Value error, move flow projection differs from nodes")
                or message.startswith(
                    "Value error, annotation flow projection differs from annotations"
                )
            )
            for message in messages
        ):
            raise CcefRepairError(
                "not_repairable", "CCEF failure is not a topology-only repair case"
            ) from None
    else:
        raise CcefRepairError("not_repairable", "CCEF failure is not a topology-only repair case")
    return tuple(affected)


def topology_repair_sequence_ids(response: StructuredGenerationResponse) -> tuple[str, ...]:
    """Return exact sequence identities eligible for the bounded repair protocol."""

    return _affected_sequence_ids(_parse_payload(response))


def _canonical_projection_copy(payload: dict[str, Any]) -> dict[str, Any]:
    """Make a diagnostic-only package whose flow projections follow array order."""

    projected = copy.deepcopy(payload)
    items = projected.get("items")
    assert isinstance(items, list)
    for item in items:
        if not isinstance(item, dict) or item.get("kind") != "move_sequence":
            continue
        nodes = item.get("nodes")
        annotations = item.get("annotations", [])
        if not isinstance(nodes, list) or not isinstance(annotations, list):
            continue
        item["reading_flow"] = [
            {"kind": "move", "node_id": node["id"]}
            for node in nodes
            if isinstance(node, dict) and type(node.get("id")) is str
        ] + [
            {"kind": "annotation", "annotation_id": annotation["id"]}
            for annotation in annotations
            if isinstance(annotation, dict) and type(annotation.get("id")) is str
        ]
    return projected


def _normalized_diagnostics(payload: dict[str, Any]) -> dict[str, dict[str, object]]:
    try:
        diagnostic_package = ExtractionPackageV1_1.model_validate(
            _canonical_projection_copy(payload)
        )
        normalized = normalize_chess_moves_v1_1(diagnostic_package)
    except (ValidationError, ValueError):
        return {}
    result: dict[str, dict[str, object]] = {}
    for item in normalized.items:
        if not isinstance(item, MoveSequenceItemV1_1):
            continue
        for node in item.nodes:
            result[node.id] = {
                "validation_status": node.validation_status,
                "validation_codes": [
                    warning.code
                    for warning in node.warnings
                    if warning.code.startswith("ccef_chess_")
                ],
                "fen_before": node.fen_before,
                "fen_after": node.fen_after,
            }
    return result


def _is_legal_after(node: dict[str, Any], fen_after_parent: object) -> bool:
    if type(fen_after_parent) is not str:
        return False
    move_text = node.get("move_text")
    if type(move_text) is not str:
        return False
    token = _clean_move_token(move_text)
    if token is None:
        return False
    try:
        board = chess.Board(fen_after_parent, chess960=False)
        side = node.get("side_to_move")
        move_number = node.get("move_number")
        if side is not None and side != ("w" if board.turn else "b"):
            return False
        if move_number is not None and move_number != board.fullmove_number:
            return False
        move = board.parse_san(token)
        return move != chess.Move.null()
    except ValueError:
        return False


def _legal_preceding_parents(
    node: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    flow_positions: dict[str, int],
    diagnostics: dict[str, dict[str, object]],
) -> tuple[list[str], int]:
    node_position = flow_positions[node["id"]]
    candidates = [
        candidate["id"]
        for candidate in nodes
        if flow_positions[candidate["id"]] < node_position
        and diagnostics.get(candidate["id"], {}).get("validation_status") == "valid"
        and _is_legal_after(node, diagnostics[candidate["id"]].get("fen_after"))
    ]
    # Nearest source-order candidates are the most useful hints. Preserve the
    # total so truncation is explicit rather than silently pretending the list
    # is exhaustive.
    candidates.sort(key=flow_positions.__getitem__, reverse=True)
    return candidates[:16], len(candidates)


def _owner_evidence(owner: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    evidence = owner.get("evidence")
    if isinstance(evidence, list):
        result.extend(reference for reference in evidence if isinstance(reference, dict))
    warnings = owner.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict):
                result.extend(_owner_evidence(warning))
    return result


def _sequence_evidence_keys(sequence: dict[str, Any]) -> set[tuple[int, str]]:
    owners: list[dict[str, Any]] = [sequence]
    for member_name in ("nodes", "annotations"):
        members = sequence.get(member_name, [])
        if isinstance(members, list):
            owners.extend(member for member in members if isinstance(member, dict))
    keys: set[tuple[int, str]] = set()
    for owner in owners:
        for reference in _owner_evidence(owner):
            page = reference.get("page")
            digest = reference.get("fragment_sha256")
            if type(page) is int and type(digest) is str:
                keys.add((page, digest))
    return keys


def _repair_case_document(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
) -> dict[str, object]:
    payload = _parse_payload(response)
    affected_ids = _affected_sequence_ids(payload)
    affected = set(affected_ids)
    diagnostics = _normalized_diagnostics(payload)
    items = payload.get("items")
    assert isinstance(items, list)
    sequence_documents: list[dict[str, object]] = []
    evidence_keys: set[tuple[int, str]] = set()
    for sequence in items:
        if (
            not isinstance(sequence, dict)
            or sequence.get("kind") != "move_sequence"
            or sequence.get("id") not in affected
        ):
            continue
        node_ids, annotation_ids, move_refs, annotation_refs = _sequence_members(sequence)
        flow_positions = {node_id: index for index, node_id in enumerate(move_refs)}
        nodes = sequence["nodes"]
        assert isinstance(nodes, list)
        typed_nodes = [node for node in nodes if isinstance(node, dict)]
        compact_nodes: list[dict[str, object]] = []
        forward_parents: list[dict[str, object]] = []
        suspect_ids: set[str] = set()
        for node in typed_nodes:
            node_id = node["id"]
            parent_id = node.get("parent_id")
            local = diagnostics.get(node_id, {})
            compact_nodes.append(
                {
                    "id": node_id,
                    "parent_id": parent_id,
                    "sibling_order": node.get("sibling_order"),
                    "move_text": node.get("move_text"),
                    "move_number": node.get("move_number"),
                    "side_to_move": node.get("side_to_move"),
                    "flow_index": flow_positions[node_id],
                    **local,
                }
            )
            if (
                type(parent_id) is str
                and parent_id in flow_positions
                and flow_positions[parent_id] >= flow_positions[node_id]
            ):
                forward_parents.append(
                    {
                        "node_id": node_id,
                        "parent_id": parent_id,
                        "node_flow_index": flow_positions[node_id],
                        "parent_flow_index": flow_positions[parent_id],
                    }
                )
                suspect_ids.add(node_id)
            parent_local = diagnostics.get(parent_id, {}) if type(parent_id) is str else {}
            if (
                local.get("validation_status") != "valid"
                and parent_local.get("validation_status") == "valid"
            ):
                suspect_ids.add(node_id)
        legal_parent_hints = []
        nodes_by_id = {node["id"]: node for node in typed_nodes}
        for node_id in sorted(suspect_ids, key=flow_positions.__getitem__):
            candidates, candidate_count = _legal_preceding_parents(
                nodes_by_id[node_id],
                nodes=typed_nodes,
                flow_positions=flow_positions,
                diagnostics=diagnostics,
            )
            legal_parent_hints.append(
                {
                    "node_id": node_id,
                    "current_parent_id": nodes_by_id[node_id].get("parent_id"),
                    "legal_preceding_parent_ids_nearest_first": candidates,
                    "candidate_count": candidate_count,
                }
            )
        sequence_documents.append(
            {
                "sequence_id": sequence["id"],
                "title": sequence.get("title"),
                "initial_position": sequence.get("initial_position"),
                "continuation_binding": (
                    sequence.get("extensions", {}).get("chess-workbench.continuation")
                    if isinstance(sequence.get("extensions"), dict)
                    else None
                ),
                "issues": {
                    "move_projection_position_mismatches": sum(
                        left != right for left, right in zip(node_ids, move_refs, strict=True)
                    ),
                    "annotation_projection_position_mismatches": sum(
                        left != right
                        for left, right in zip(annotation_ids, annotation_refs, strict=True)
                    ),
                    "forward_parents_in_reading_flow": forward_parents,
                    "legal_parent_hints": legal_parent_hints,
                    "locally_invalid_nodes": [
                        {
                            "node_id": node_id,
                            "validation_status": local["validation_status"],
                            "validation_codes": local["validation_codes"],
                        }
                        for node_id, local in diagnostics.items()
                        if local.get("validation_status") != "valid" and node_id in node_ids
                    ],
                },
                "nodes": compact_nodes,
                "annotations": [
                    {
                        "id": annotation.get("id"),
                        "text": annotation.get("text"),
                        "anchor": annotation.get("anchor"),
                    }
                    for annotation in sequence.get("annotations", [])
                    if isinstance(annotation, dict)
                ],
                "reading_flow": sequence.get("reading_flow"),
            }
        )
        evidence_keys.update(_sequence_evidence_keys(sequence))

    fragments: list[dict[str, object]] = []
    for page in context.pages:
        for entry in page.fragments:
            fragment = entry.fragment
            key = (fragment.physical_page, fragment.fragment_sha256)
            if key not in evidence_keys:
                continue
            fragments.append(
                {
                    "physical_page": fragment.physical_page,
                    "order": entry.order,
                    "fragment_sha256": fragment.fragment_sha256,
                    "text": fragment.text,
                }
            )
    return {
        "repair_protocol": CCEF_TOPOLOGY_REPAIR_SCHEMA,
        "base_response_sha256": _response_sha256(response),
        "rules": {
            "reading_flow_is_source_order_authority": True,
            "allowed_changes": ["parent_id", "sibling_order"],
            "local_code_compacts_sibling_orders_after_parent_changes": True,
            "nodes_may_not_be_added_removed_or_renamed": True,
            "moves_annotations_and_evidence_may_not_be_changed": True,
        },
        "sequences": sequence_documents,
        "evidence_fragments": fragments,
    }


_REPAIR_SYSTEM = """\
Repair only the chess topology described in the user document. The source reading_flow is
authoritative and local code will reorder nodes and annotations to its projections. Return one
topology repair object. You may update only parent_id and sibling_order of existing node IDs; do
not add, delete or rename nodes and do not change moves, annotations, evidence or reading_flow.
Every non-null parent must be the exact preceding chess position, must occur earlier in the move
reading_flow, and must make the node legal in that branch. Under each parent, sibling_order values
express relative branch preference, with the main continuation at zero; local code deterministically
compacts any gaps after applying parent changes. Use the supplied source fragments and local chess
diagnostics to distinguish similarly numbered variations. Include one sequence repair for every
supplied sequence, even when its node_updates list is empty. An unresolved descendant may have no
legal-parent hint because its current ancestor is wrong; repair the earliest wrong ancestor and
leave a descendant's parent unchanged when their chain is already source-supported.
"""


def build_ccef_topology_repair_request(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
) -> StructuredGenerationRequest:
    """Translate one retained topology failure into a compact repair request."""

    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    case = _repair_case_document(response, context)
    return StructuredGenerationRequest(
        messages=[
            StructuredMessage(role="system", content=_REPAIR_SYSTEM),
            StructuredMessage(role="user", content=_canonical_json(case)),
        ],
        response_schema_name=_REPAIR_SCHEMA_NAME,
        response_schema=CcefTopologyRepair.model_json_schema(),
        max_output_tokens=min(context.max_output_tokens, _MAX_REPAIR_OUTPUT_TOKENS),
    )


def decode_ccef_topology_repair(
    response: StructuredGenerationResponse,
) -> CcefTopologyRepair:
    """Strictly decode a provider repair response without retaining raw errors."""

    try:
        payload = _parse_payload(response)
        return CcefTopologyRepair.model_validate(payload)
    except (CcefDecodeError, ValidationError):
        raise CcefRepairError("invalid_repair", "Topology repair response is invalid") from None


def apply_ccef_topology_repair(
    original: StructuredGenerationResponse,
    repair_response: StructuredGenerationResponse,
) -> StructuredGenerationResponse:
    """Apply an identity-bound topology patch to a copy of the original response."""

    if type(original) is not StructuredGenerationResponse:
        raise TypeError("original must be StructuredGenerationResponse")
    if type(repair_response) is not StructuredGenerationResponse:
        raise TypeError("repair_response must be StructuredGenerationResponse")
    payload = _parse_payload(original)
    affected_ids = _affected_sequence_ids(payload)
    repair = decode_ccef_topology_repair(repair_response)
    if repair.base_response_sha256 != _response_sha256(original):
        raise CcefRepairError("binding_mismatch", "Topology repair does not match failed response")
    if tuple(sequence.sequence_id for sequence in repair.sequences) != affected_ids:
        raise CcefRepairError("binding_mismatch", "Topology repair sequence binding is invalid")

    items = payload.get("items")
    assert isinstance(items, list)
    patches = {sequence.sequence_id: sequence for sequence in repair.sequences}
    repaired = copy.deepcopy(payload)
    repaired_items = repaired.get("items")
    assert isinstance(repaired_items, list)
    for sequence in repaired_items:
        if not isinstance(sequence, dict) or sequence.get("kind") != "move_sequence":
            continue
        sequence_id = sequence.get("id")
        patch = patches.get(sequence_id) if type(sequence_id) is str else None
        if patch is None:
            continue
        nodes = sequence.get("nodes")
        annotations = sequence.get("annotations", [])
        flow = sequence.get("reading_flow")
        assert isinstance(nodes, list) and isinstance(annotations, list) and isinstance(flow, list)
        nodes_by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
        annotations_by_id = {
            annotation["id"]: annotation
            for annotation in annotations
            if isinstance(annotation, dict)
        }
        for update in patch.node_updates:
            node = nodes_by_id.get(update.node_id)
            if node is None:
                raise CcefRepairError(
                    "binding_mismatch", "Topology repair references an unknown node"
                )
            if update.parent_id is not None and update.parent_id not in nodes_by_id:
                raise CcefRepairError(
                    "binding_mismatch", "Topology repair references an unknown parent"
                )
            node["parent_id"] = update.parent_id
            node["sibling_order"] = update.sibling_order
        move_order = [entry["node_id"] for entry in flow if entry.get("kind") == "move"]
        flow_positions = {node_id: index for index, node_id in enumerate(move_order)}
        sibling_groups: dict[str | None, list[dict[str, Any]]] = {}
        for node in nodes_by_id.values():
            parent_id = node.get("parent_id")
            sibling_groups.setdefault(parent_id, []).append(node)
        for siblings in sibling_groups.values():
            siblings.sort(
                key=lambda node: (
                    node["sibling_order"],
                    flow_positions[node["id"]],
                )
            )
            for sibling_order, node in enumerate(siblings):
                node["sibling_order"] = sibling_order
        annotation_order = [
            entry["annotation_id"] for entry in flow if entry.get("kind") == "annotation"
        ]
        sequence["nodes"] = [nodes_by_id[node_id] for node_id in move_order]
        sequence["annotations"] = [
            annotations_by_id[annotation_id] for annotation_id in annotation_order
        ]

    # This gate proves the repair did not exploit a partial or malformed tree.
    # Evidence geometry is intentionally left for the trusted C+D binder used
    # by the normal candidate path immediately after this function.
    try:
        ExtractionPackageV1_1.model_validate(repaired)
    except ValidationError:
        raise CcefRepairError(
            "invalid_repair", "Topology repair does not produce valid CCEF"
        ) from None
    return original.model_copy(update={"content": _canonical_json(repaired)})


def ccef_repair_chain_document(
    original: StructuredGenerationResponse,
    repair: StructuredGenerationResponse,
    repaired: StructuredGenerationResponse,
) -> dict[str, object]:
    """Return the persisted, secret-free record of one successful repair chain."""

    return {
        "artifact_schema": "chess-workbench/ccef-repair-chain/1.0",
        "original_response": original.model_dump(mode="json"),
        "repair_response": repair.model_dump(mode="json"),
        "repaired_content_sha256": _response_sha256(repaired),
    }


__all__ = [
    "CCEF_TOPOLOGY_REPAIR_SCHEMA",
    "CcefNodeTopologyUpdate",
    "CcefRepairError",
    "CcefSequenceTopologyRepair",
    "CcefTopologyRepair",
    "apply_ccef_topology_repair",
    "build_ccef_topology_repair_request",
    "ccef_repair_chain_document",
    "decode_ccef_topology_repair",
    "topology_repair_sequence_ids",
]
