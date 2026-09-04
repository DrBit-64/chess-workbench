"""Generic, bounded repair for a complete but locally rejected CCEF response.

The provider returns a small JSON patch, never a regenerated extraction.  The
patch is bound to the exact failed response and may correct fields inside the
existing package, while local guards preserve item/node/annotation/evidence
cardinality and the caller-owned metadata.  The normal extraction pipeline is
still the final authority after the patch is applied.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Iterator
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .contracts import (
    ExtractionItemV1_1,
    ExtractionPackageV1_1,
    FiniteJsonValue,
    MoveSequenceItemV1_1,
    Sha256Hex,
)
from .decoder import CcefDecodeError, _parse_payload
from .prompting import CcefPromptContext
from .provider import StructuredGenerationRequest, StructuredGenerationResponse, StructuredMessage

CCEF_GENERAL_REPAIR_SCHEMA = "chess-workbench/ccef-repair/2.0"
_REPAIR_SCHEMA_NAME = "chess_workbench_ccef_repair_v2"
_MAX_REPAIR_OUTPUT_TOKENS = 32_768
_MAX_DIAGNOSTICS = 32
_MAX_AFFECTED_ITEMS = 8
_MAX_OPERATIONS = 64
_MAX_PATCH_BYTES = 256_000
_MAX_TEXT_CHANGE = 4_096
_ITEM_ADAPTER: TypeAdapter[ExtractionItemV1_1] = TypeAdapter(ExtractionItemV1_1)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CcefRepairDiagnostic(_StrictModel):
    diagnostic_id: str = Field(pattern=r"^diagnostic-[1-9][0-9]*$", max_length=32)
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: str = Field(min_length=1, max_length=512)
    message: str = Field(min_length=1, max_length=1000)
    item_index: int | None = Field(default=None, ge=0)
    item_id: str | None = Field(default=None, min_length=1, max_length=128)
    node_id: str | None = Field(default=None, min_length=1, max_length=128)


class CcefRepairAdd(_StrictModel):
    op: Literal["add"]
    path: str = Field(min_length=1, max_length=512)
    value: FiniteJsonValue


class CcefRepairRemove(_StrictModel):
    op: Literal["remove"]
    path: str = Field(min_length=1, max_length=512)


class CcefRepairReplace(_StrictModel):
    op: Literal["replace"]
    path: str = Field(min_length=1, max_length=512)
    value: FiniteJsonValue


CcefRepairOperation = Annotated[
    CcefRepairAdd | CcefRepairRemove | CcefRepairReplace,
    Field(discriminator="op"),
]


class CcefRepairPatch(_StrictModel):
    repair_schema: Literal["chess-workbench/ccef-repair/2.0"]
    base_response_sha256: Sha256Hex
    resolves: list[str] = Field(min_length=1, max_length=_MAX_DIAGNOSTICS)
    operations: list[CcefRepairOperation] = Field(min_length=1, max_length=_MAX_OPERATIONS)

    @model_validator(mode="after")
    def references_are_unique(self) -> Self:
        if len(self.resolves) != len(set(self.resolves)):
            raise ValueError("repair diagnostic references must be unique")
        paths = [operation.path for operation in self.operations]
        if len(paths) != len(set(paths)):
            raise ValueError("repair operation paths must be unique")
        return self


class CcefRepairError(ValueError):
    """Fixed, non-sensitive failure raised by the bounded repair boundary."""

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


def _pointer(parts: Iterable[str | int]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


_ITEM_VARIANTS = {"heading", "prose", "move_sequence", "figure", "unresolved"}
_NESTED_VARIANTS = {"startpos", "fen", "move_node", "position", "move", "annotation"}


def _json_location(location: Iterable[object]) -> tuple[str | int, ...]:
    """Remove Pydantic discriminated-union labels that are not JSON keys."""

    result: list[str | int] = []
    for raw_part in location:
        part: str | int = raw_part if isinstance(raw_part, (str, int)) else str(raw_part)
        if (
            isinstance(part, str)
            and part in _ITEM_VARIANTS
            and len(result) >= 2
            and result[-2] == "items"
            and type(result[-1]) is int
        ):
            continue
        if isinstance(part, str) and part in _NESTED_VARIANTS:
            follows_named_union = bool(result and result[-1] in {"initial_position", "anchor"})
            follows_flow_entry = (
                len(result) >= 2 and result[-2] == "reading_flow" and type(result[-1]) is int
            )
            if follows_named_union or follows_flow_entry:
                continue
        result.append(part)
    return tuple(result)


def _safe_message(value: object, fallback: str) -> str:
    if type(value) is not str or not value.strip():
        return fallback
    return value[:1000]


def _item_identity(item: object) -> str | None:
    if isinstance(item, dict):
        value = item.get("id")
        if type(value) is str:
            return value
    return None


def _node_identity(item: object, location: tuple[object, ...]) -> str | None:
    if not isinstance(item, dict):
        return None
    try:
        position = location.index("nodes")
        node_index = location[position + 1]
    except (ValueError, IndexError):
        return None
    nodes = item.get("nodes")
    if type(node_index) is int and isinstance(nodes, list) and node_index < len(nodes):
        node = nodes[node_index]
        if isinstance(node, dict):
            value = node.get("id")
            if type(value) is str:
                return value
    return None


def _append_diagnostic(
    target: list[dict[str, object]],
    *,
    code: str,
    path: str,
    message: str,
    item_index: int | None = None,
    item_id: str | None = None,
    node_id: str | None = None,
) -> None:
    key = (code, path, message)
    if any((entry["code"], entry["path"], entry["message"]) == key for entry in target):
        return
    target.append(
        {
            "code": code,
            "path": path,
            "message": message,
            "item_index": item_index,
            "item_id": item_id,
            "node_id": node_id,
        }
    )


def _validation_diagnostics(
    error: ValidationError,
    target: list[dict[str, object]],
    *,
    prefix: tuple[str | int, ...] = (),
    item_index: int | None = None,
    item: object = None,
    payload: dict[str, Any] | None = None,
) -> None:
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        location = tuple(detail.get("loc", ()))
        full_location = _json_location((*prefix, *location))
        current_index = item_index
        current_item = item
        if (
            current_index is None
            and len(full_location) >= 2
            and full_location[0] == "items"
            and type(full_location[1]) is int
            and payload is not None
            and isinstance(payload.get("items"), list)
            and full_location[1] < len(payload["items"])
        ):
            current_index = full_location[1]
            current_item = payload["items"][current_index]
        _append_diagnostic(
            target,
            code=f"schema_{detail.get('type', 'validation_error')}".replace(".", "_")[:64],
            path=_pointer(full_location),
            message=_safe_message(detail.get("msg"), "CCEF schema validation failed"),
            item_index=current_index,
            item_id=_item_identity(current_item),
            node_id=_node_identity(current_item, full_location),
        )


def _scan_sequence(item: dict[str, Any], item_index: int, target: list[dict[str, object]]) -> None:
    nodes = item.get("nodes")
    annotations = item.get("annotations", [])
    flow = item.get("reading_flow")
    if (
        not isinstance(nodes, list)
        or not isinstance(annotations, list)
        or not isinstance(flow, list)
    ):
        return
    item_id = _item_identity(item)
    node_positions: dict[str, int] = {}
    sibling_groups: dict[str | None, list[tuple[int, int, str | None]]] = {}
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") if type(node.get("id")) is str else None
        parent_id = node.get("parent_id") if type(node.get("parent_id")) is str else None
        if node_id is not None:
            if node_id in node_positions:
                _append_diagnostic(
                    target,
                    code="duplicate_node_id",
                    path=_pointer(("items", item_index, "nodes", node_index, "id")),
                    message="Node identity is duplicated within the sequence",
                    item_index=item_index,
                    item_id=item_id,
                    node_id=node_id,
                )
            else:
                node_positions[node_id] = node_index
        if parent_id is not None and parent_id not in node_positions:
            _append_diagnostic(
                target,
                code="dangling_or_forward_parent",
                path=_pointer(("items", item_index, "nodes", node_index, "parent_id")),
                message="Parent identity must name an earlier node in the same sequence",
                item_index=item_index,
                item_id=item_id,
                node_id=node_id,
            )
        sibling_order = node.get("sibling_order")
        if type(sibling_order) is int:
            sibling_groups.setdefault(parent_id, []).append((node_index, sibling_order, node_id))
    for siblings in sibling_groups.values():
        orders = [entry[1] for entry in siblings]
        if sorted(orders) == list(range(len(orders))):
            continue
        for node_index, _sibling_order, node_id in siblings:
            _append_diagnostic(
                target,
                code="non_contiguous_sibling_order",
                path=_pointer(("items", item_index, "nodes", node_index, "sibling_order")),
                message=(
                    "Sibling orders under one parent must be unique and contiguous from zero; "
                    f"observed {sorted(orders)}"
                ),
                item_index=item_index,
                item_id=item_id,
                node_id=node_id,
            )

    annotation_ids = {
        annotation.get("id")
        for annotation in annotations
        if isinstance(annotation, dict) and type(annotation.get("id")) is str
    }
    node_ids = [
        node.get("id") for node in nodes if isinstance(node, dict) and type(node.get("id")) is str
    ]
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
    if node_ids != move_refs:
        _append_diagnostic(
            target,
            code="move_flow_projection_mismatch",
            path=_pointer(("items", item_index, "reading_flow")),
            message="Move references in reading_flow must exactly project the nodes array",
            item_index=item_index,
            item_id=item_id,
        )
    expected_annotations = [
        annotation.get("id")
        for annotation in annotations
        if isinstance(annotation, dict) and type(annotation.get("id")) is str
    ]
    if expected_annotations != annotation_refs:
        _append_diagnostic(
            target,
            code="annotation_flow_projection_mismatch",
            path=_pointer(("items", item_index, "reading_flow")),
            message="Annotation references in reading_flow must exactly project annotations",
            item_index=item_index,
            item_id=item_id,
        )
    for annotation_index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            continue
        anchor = annotation.get("anchor")
        if (
            isinstance(anchor, dict)
            and anchor.get("kind") == "move_node"
            and anchor.get("node_id") not in node_positions
        ):
            _append_diagnostic(
                target,
                code="annotation_anchor_missing",
                path=_pointer(
                    ("items", item_index, "annotations", annotation_index, "anchor", "node_id")
                ),
                message="Move annotation anchor must name a node in the same sequence",
                item_index=item_index,
                item_id=item_id,
            )
    if any(value not in node_positions for value in move_refs):
        _append_diagnostic(
            target,
            code="flow_move_reference_missing",
            path=_pointer(("items", item_index, "reading_flow")),
            message="Every move flow reference must name an existing node exactly once",
            item_index=item_index,
            item_id=item_id,
        )
    if any(value not in annotation_ids for value in annotation_refs):
        _append_diagnostic(
            target,
            code="flow_annotation_reference_missing",
            path=_pointer(("items", item_index, "reading_flow")),
            message="Every annotation flow reference must name an existing annotation exactly once",
            item_index=item_index,
            item_id=item_id,
        )


def _failure_diagnostic(failure: BaseException | None) -> tuple[str, str] | None:
    if failure is None:
        return None
    if isinstance(failure, CcefDecodeError):
        return ("decoder_rejected_package", "The response does not satisfy the CCEF 1.1 contract")
    message = str(failure)
    if message == "incremental response metadata mismatch":
        return ("metadata_mismatch", "Package metadata must exactly match trusted request metadata")
    if "continuation binding" in message:
        return (
            "continuation_binding_invalid",
            "Continuation binding must name one supplied predecessor anchor and aggregate hash",
        )
    if "evidence binding" in message:
        return (
            "evidence_binding_invalid",
            "Every evidence selector must resolve to one supplied trusted fragment",
        )
    return (
        "pipeline_validation_failed",
        "The repaired package must pass the complete local pipeline",
    )


def _trusted_evidence_diagnostics(
    payload: dict[str, Any],
    context: CcefPromptContext,
    target: list[dict[str, object]],
) -> None:
    trusted = {
        (entry.fragment.physical_page, entry.fragment.fragment_sha256)
        for page in context.pages
        for entry in page.fragments
    }
    items = payload.get("items")
    if not isinstance(items, list):
        return

    def walk(
        owner: object, path: tuple[str | int, ...], item_index: int, item_id: str | None
    ) -> None:
        if isinstance(owner, dict):
            for key, value in owner.items():
                next_path = (*path, key)
                if key == "evidence" and isinstance(value, list):
                    for evidence_index, reference in enumerate(value):
                        if not isinstance(reference, dict):
                            continue
                        page = reference.get("page")
                        digest = reference.get("fragment_sha256")
                        if type(page) is int and type(digest) is str and (page, digest) in trusted:
                            continue
                        _append_diagnostic(
                            target,
                            code="untrusted_evidence_selector",
                            path=_pointer((*next_path, evidence_index)),
                            message=(
                                "Evidence page and fragment hash must name one supplied fragment"
                            ),
                            item_index=item_index,
                            item_id=item_id,
                        )
                walk(value, next_path, item_index, item_id)
        elif isinstance(owner, list):
            for index, value in enumerate(owner):
                walk(value, (*path, index), item_index, item_id)

    for item_index, item in enumerate(items):
        walk(item, ("items", item_index), item_index, _item_identity(item))


def ccef_repair_diagnostics(
    response: StructuredGenerationResponse,
    failure: BaseException | None = None,
    *,
    context: CcefPromptContext | None = None,
) -> tuple[CcefRepairDiagnostic, ...]:
    """Translate a complete JSON response and local failure into bounded diagnostics."""

    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")
    payload = _parse_payload(response)
    items = payload.get("items")
    if not isinstance(items, list):
        raise CcefRepairError("not_repairable", "CCEF failure has no repairable item collection")
    diagnostics: list[dict[str, object]] = []
    try:
        ExtractionPackageV1_1.model_validate(payload)
    except ValidationError as error:
        _validation_diagnostics(error, diagnostics, payload=payload)
    for item_index, item in enumerate(items):
        try:
            typed_item = _ITEM_ADAPTER.validate_python(item)
        except ValidationError as error:
            _validation_diagnostics(
                error,
                diagnostics,
                prefix=("items", item_index),
                item_index=item_index,
                item=item,
            )
        else:
            if isinstance(typed_item, MoveSequenceItemV1_1) and isinstance(item, dict):
                _scan_sequence(item, item_index, diagnostics)
    if context is not None:
        if type(context) is not CcefPromptContext:
            raise TypeError("context must be CcefPromptContext")
        _trusted_evidence_diagnostics(payload, context, diagnostics)
    external = _failure_diagnostic(failure)
    if external is not None:
        _append_diagnostic(
            diagnostics,
            code=external[0],
            path="/",
            message=external[1],
        )
    if not diagnostics:
        raise CcefRepairError("not_repairable", "CCEF response has no bounded repair diagnostic")
    if len(diagnostics) > _MAX_DIAGNOSTICS:
        raise CcefRepairError(
            "repair_too_large", "CCEF repair has too many independent diagnostics"
        )
    return tuple(
        CcefRepairDiagnostic.model_validate(
            {
                "diagnostic_id": f"diagnostic-{index}",
                **diagnostic,
            }
        )
        for index, diagnostic in enumerate(diagnostics, 1)
    )


def _expected_metadata(context: CcefPromptContext) -> dict[str, object]:
    created_at = context.created_at.isoformat(timespec="microseconds").removesuffix("+00:00") + "Z"
    return {
        "schema_version": "chess-content-extraction/1.1",
        "package_id": str(context.package_id),
        "source": {
            "source_ref": context.source_ref,
            "media_type": context.media_type,
            "language": context.language,
            "page_range": {"start_page": context.first_page, "end_page": context.last_page},
        },
        "provenance": {
            "created_at": created_at,
            "adapter_name": "chess-workbench-ccef-prompt",
            "adapter_version": "1.1",
            "provider": None,
            "model": None,
            "request_sha256": None,
            "response_sha256": None,
        },
        "extensions": {},
    }


def _evidence_keys(owner: object) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    if isinstance(owner, dict):
        for key, value in owner.items():
            if key == "evidence" and isinstance(value, list):
                for reference in value:
                    if not isinstance(reference, dict):
                        continue
                    page = reference.get("page")
                    digest = reference.get("fragment_sha256")
                    if type(page) is int and type(digest) is str:
                        keys.add((page, digest))
            keys.update(_evidence_keys(value))
    elif isinstance(owner, list):
        for value in owner:
            keys.update(_evidence_keys(value))
    return keys


def _affected_item_indices(
    payload: dict[str, Any], diagnostics: tuple[CcefRepairDiagnostic, ...]
) -> tuple[int, ...]:
    items = payload.get("items")
    assert isinstance(items, list)
    result = {
        diagnostic.item_index for diagnostic in diagnostics if diagnostic.item_index is not None
    }
    messages = "\n".join(diagnostic.message for diagnostic in diagnostics)
    for index, item in enumerate(items):
        item_id = _item_identity(item)
        if item_id is not None and item_id in messages:
            result.add(index)
    if not result and any(diagnostic.path != "/" for diagnostic in diagnostics):
        result.update(range(min(len(items), _MAX_AFFECTED_ITEMS)))
    if len(result) > _MAX_AFFECTED_ITEMS:
        raise CcefRepairError("repair_too_large", "CCEF repair affects too many content items")
    return tuple(sorted(result))


_TOPOLOGY_DIAGNOSTICS = {
    "duplicate_node_id",
    "dangling_or_forward_parent",
    "non_contiguous_sibling_order",
    "move_flow_projection_mismatch",
    "annotation_flow_projection_mismatch",
    "annotation_anchor_missing",
    "flow_move_reference_missing",
    "flow_annotation_reference_missing",
    "continuation_binding_invalid",
}
_TRUSTED_CONTEXT_DIAGNOSTICS = {"continuation_binding_invalid"}


def _diagnostic_collection_indices(
    diagnostics: tuple[CcefRepairDiagnostic, ...],
    *,
    item_index: int,
    collection: str,
) -> set[int]:
    result: set[int] = set()
    for diagnostic in diagnostics:
        if diagnostic.item_index != item_index:
            continue
        parts = diagnostic.path.removeprefix("/").split("/")
        for position, part in enumerate(parts[:-1]):
            if part != collection:
                continue
            candidate = parts[position + 1]
            if candidate.isdigit():
                result.add(int(candidate))
    return result


def _affected_item_excerpt(
    item: object,
    item_index: int,
    diagnostics: tuple[CcefRepairDiagnostic, ...],
) -> tuple[dict[str, object], list[object]]:
    if not isinstance(item, dict):
        return {
            "item_index": item_index,
            "values_by_json_pointer": {_pointer(("items", item_index)): item},
        }, [item]
    if item.get("kind") != "move_sequence":
        values = {_pointer(("items", item_index, key)): value for key, value in item.items()}
        return {"item_index": item_index, "values_by_json_pointer": values}, [item]
    item_diagnostics = tuple(
        diagnostic for diagnostic in diagnostics if diagnostic.item_index == item_index
    )
    topology = any(diagnostic.code in _TOPOLOGY_DIAGNOSTICS for diagnostic in item_diagnostics)
    nodes = item.get("nodes")
    annotations = item.get("annotations", [])
    flow = item.get("reading_flow")
    if (
        not isinstance(nodes, list)
        or not isinstance(annotations, list)
        or not isinstance(flow, list)
    ):
        values = {_pointer(("items", item_index, key)): value for key, value in item.items()}
        return {"item_index": item_index, "values_by_json_pointer": values}, [item]

    node_indices = _diagnostic_collection_indices(
        item_diagnostics, item_index=item_index, collection="nodes"
    )
    annotation_indices = _diagnostic_collection_indices(
        item_diagnostics, item_index=item_index, collection="annotations"
    )
    flow_indices = _diagnostic_collection_indices(
        item_diagnostics, item_index=item_index, collection="reading_flow"
    )
    if topology or (not node_indices and not annotation_indices and not flow_indices):
        node_indices.update(range(len(nodes)))
        annotation_indices.update(range(len(annotations)))
        flow_indices.update(range(len(flow)))
    else:
        selected_node_ids = {
            nodes[index].get("id")
            for index in node_indices
            if index < len(nodes) and isinstance(nodes[index], dict)
        }
        for flow_index, entry in enumerate(flow):
            if not isinstance(entry, dict):
                continue
            if entry.get("node_id") in selected_node_ids:
                flow_indices.add(flow_index)
        for flow_index in tuple(flow_indices):
            if flow_index > 0:
                flow_indices.add(flow_index - 1)
            if flow_index + 1 < len(flow):
                flow_indices.add(flow_index + 1)

    header = {
        key: value
        for key, value in item.items()
        if key not in {"nodes", "annotations", "reading_flow"}
    }
    values_by_pointer: dict[str, object] = {
        _pointer(("items", item_index, key)): value for key, value in header.items()
    }
    selected_nodes = [nodes[index] for index in sorted(node_indices) if index < len(nodes)]
    selected_annotations = [
        annotations[index] for index in sorted(annotation_indices) if index < len(annotations)
    ]
    for index in sorted(node_indices):
        if index < len(nodes):
            values_by_pointer[_pointer(("items", item_index, "nodes", index))] = nodes[index]
    for index in sorted(annotation_indices):
        if index < len(annotations):
            values_by_pointer[_pointer(("items", item_index, "annotations", index))] = annotations[
                index
            ]
    for index in sorted(flow_indices):
        if index < len(flow):
            values_by_pointer[_pointer(("items", item_index, "reading_flow", index))] = flow[index]
    evidence_owners: list[object] = list(header.values())
    evidence_owners.extend(selected_nodes)
    evidence_owners.extend(selected_annotations)
    return (
        {
            "item_index": item_index,
            "values_by_json_pointer": values_by_pointer,
        },
        evidence_owners,
    )


def _repair_case_document(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
    failure: BaseException | None,
    trusted_context: dict[str, object] | None,
) -> dict[str, object]:
    payload = _parse_payload(response)
    diagnostics = ccef_repair_diagnostics(response, failure, context=context)
    indices = _affected_item_indices(payload, diagnostics)
    items = payload["items"]
    affected_items: list[dict[str, object]] = []
    evidence_owners: list[object] = []
    for index in indices:
        excerpt, owners = _affected_item_excerpt(items[index], index, diagnostics)
        affected_items.append(excerpt)
        evidence_owners.extend(owners)
    cited_keys = _evidence_keys(evidence_owners)
    cited_pages = {page for page, _digest in cited_keys}
    fragments: list[dict[str, object]] = []
    for page in context.pages:
        for entry in page.fragments:
            fragment = entry.fragment
            key = (fragment.physical_page, fragment.fragment_sha256)
            if key not in cited_keys and fragment.physical_page not in cited_pages:
                continue
            fragments.append(
                {
                    "physical_page": fragment.physical_page,
                    "order": entry.order,
                    "fragment_sha256": fragment.fragment_sha256,
                    "text": fragment.text,
                }
            )
    document: dict[str, object] = {
        "repair_protocol": CCEF_GENERAL_REPAIR_SCHEMA,
        "base_response_sha256": _response_sha256(response),
        "diagnostics": [diagnostic.model_dump(mode="json") for diagnostic in diagnostics],
        "rules": {
            "patch_paths_are_json_pointers_into_the_original_response": True,
            "allowed_operations": ["add", "remove", "replace"],
            "preserve_item_node_annotation_and_evidence_counts": True,
            "do_not_rewrite_unaffected_content": True,
            "trusted_metadata_after_repair": _expected_metadata(context),
            "all_evidence_selectors_must_name_supplied_fragments": True,
            "excerpt_map_keys_are_original_json_pointers": True,
            "excerpt_map_values_are_exact_original_values": True,
            "do_not_replace_or_resize_reading_flow_entries": True,
        },
        "current_metadata": {
            key: payload.get(key)
            for key in ("schema_version", "package_id", "source", "provenance", "extensions")
        },
        "affected_items": affected_items,
        "trusted_evidence_fragments": fragments,
        "trusted_context": (
            trusted_context
            if any(diagnostic.code in _TRUSTED_CONTEXT_DIAGNOSTICS for diagnostic in diagnostics)
            else {}
        )
        or {},
    }
    encoded = _canonical_json(document)
    if len(encoded) > context.max_prompt_chars:
        raise CcefRepairError("repair_too_large", "CCEF repair prompt exceeds configured limit")
    return document


_REPAIR_SYSTEM = """\
Repair a complete but locally rejected CCEF 1.1 response by returning only one bounded JSON
patch. Use the structured diagnostics to find root causes; do not patch every downstream
symptom. Paths are JSON Pointers into the original response and operations are applied in order.
Preserve source wording unless a cited trusted fragment proves a small transcription correction.
Do not remove or replace an entire item, move-node array, annotation array, or evidence array.
Do not replace, add, or remove a reading_flow entry. Patch only a specific scalar field inside an
existing entry when a diagnostic requires it. affected_items maps original JSON Pointer strings
directly to exact original values; its pointer keys are never part of a replacement value.
Do not invent source evidence. Never copy a rejected value back unchanged: each operation must
directly address a supplied diagnostic or one shared root cause. The package metadata after repair
must equal trusted_metadata_after_repair exactly. Prefer the smallest set of operations that
resolves the supplied diagnostics, and list every diagnostic ID the patch is intended to resolve.
Local code will reject unauthorized changes and rerun the complete CCEF, trusted-evidence,
continuation, chess-legality and composition pipeline.
"""


def build_ccef_repair_request(
    response: StructuredGenerationResponse,
    context: CcefPromptContext,
    *,
    failure: BaseException | None = None,
    trusted_context: dict[str, object] | None = None,
) -> StructuredGenerationRequest:
    """Build one generic repair request for a small, complete CCEF failure."""

    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    case = _repair_case_document(response, context, failure, trusted_context)
    return StructuredGenerationRequest(
        messages=[
            StructuredMessage(role="system", content=_REPAIR_SYSTEM),
            StructuredMessage(role="user", content=_canonical_json(case)),
        ],
        response_schema_name=_REPAIR_SCHEMA_NAME,
        response_schema=CcefRepairPatch.model_json_schema(),
        max_output_tokens=min(context.max_output_tokens, _MAX_REPAIR_OUTPUT_TOKENS),
    )


def decode_ccef_repair(response: StructuredGenerationResponse) -> CcefRepairPatch:
    try:
        return CcefRepairPatch.model_validate(_parse_payload(response))
    except (CcefDecodeError, ValidationError):
        raise CcefRepairError("invalid_repair", "CCEF repair response is invalid") from None


def _decode_pointer(path: str) -> list[str]:
    if path == "/" or not path.startswith("/"):
        raise CcefRepairError("invalid_repair", "CCEF repair path is invalid")
    parts = path[1:].split("/")
    decoded: list[str] = []
    for part in parts:
        index = 0
        value = ""
        while index < len(part):
            if part[index] != "~":
                value += part[index]
                index += 1
                continue
            if index + 1 >= len(part) or part[index + 1] not in {"0", "1"}:
                raise CcefRepairError("invalid_repair", "CCEF repair path is invalid")
            value += "~" if part[index + 1] == "0" else "/"
            index += 2
        decoded.append(value)
    return decoded


def _list_index(value: str, *, allow_end: bool, length: int) -> int:
    if value == "-" and allow_end:
        return length
    if not value.isdigit() or (len(value) > 1 and value.startswith("0")):
        raise CcefRepairError("invalid_repair", "CCEF repair list index is invalid")
    index = int(value)
    upper = length if allow_end else length - 1
    if index < 0 or index > upper:
        raise CcefRepairError("invalid_repair", "CCEF repair list index is out of range")
    return index


def _resolve_parent(document: object, parts: list[str]) -> tuple[dict[str, Any] | list[Any], str]:
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                raise CcefRepairError("invalid_repair", "CCEF repair path does not exist")
            current = current[part]
        elif isinstance(current, list):
            current = current[_list_index(part, allow_end=False, length=len(current))]
        else:
            raise CcefRepairError("invalid_repair", "CCEF repair path crosses a scalar")
    if not isinstance(current, (dict, list)):
        raise CcefRepairError("invalid_repair", "CCEF repair path has no container")
    return current, parts[-1]


def _authorize_path(parts: list[str], operation: CcefRepairOperation) -> None:
    if not parts:
        raise CcefRepairError("unauthorized_repair", "CCEF repair may not replace the package")
    if parts[0] not in {
        "schema_version",
        "items",
        "diagnostics",
        "package_id",
        "source",
        "provenance",
        "extensions",
    }:
        raise CcefRepairError("unauthorized_repair", "CCEF repair path is outside its authority")
    if parts[-1] in {"items", "nodes", "annotations", "evidence", "reading_flow"}:
        raise CcefRepairError(
            "unauthorized_repair", "CCEF repair may not replace content collections"
        )
    if parts[-1].isdigit() or parts[-1] == "-":
        protected_parent = next(
            (part for part in reversed(parts[:-1]) if not part.isdigit()),
            None,
        )
        if protected_parent in {"items", "nodes", "annotations", "evidence", "reading_flow"}:
            raise CcefRepairError("unauthorized_repair", "CCEF repair may not resize core content")
    if isinstance(operation, CcefRepairRemove) and parts[0] in {
        "schema_version",
        "package_id",
        "source",
        "provenance",
    }:
        raise CcefRepairError("unauthorized_repair", "CCEF repair may not remove trusted metadata")


def _apply_operation(document: dict[str, Any], operation: CcefRepairOperation) -> None:
    parts = _decode_pointer(operation.path)
    _authorize_path(parts, operation)
    parent, leaf = _resolve_parent(document, parts)
    if isinstance(parent, dict):
        exists = leaf in parent
        if isinstance(operation, CcefRepairAdd):
            if exists:
                raise CcefRepairError("invalid_repair", "CCEF repair add path already exists")
            parent[leaf] = copy.deepcopy(operation.value)
        elif isinstance(operation, CcefRepairRemove):
            if not exists:
                raise CcefRepairError("invalid_repair", "CCEF repair remove path does not exist")
            del parent[leaf]
        else:
            if not exists:
                raise CcefRepairError("invalid_repair", "CCEF repair replace path does not exist")
            parent[leaf] = copy.deepcopy(operation.value)
        return
    index = _list_index(
        leaf,
        allow_end=isinstance(operation, CcefRepairAdd),
        length=len(parent),
    )
    if isinstance(operation, CcefRepairAdd):
        parent.insert(index, copy.deepcopy(operation.value))
    elif isinstance(operation, CcefRepairRemove):
        del parent[index]
    else:
        parent[index] = copy.deepcopy(operation.value)


def _footprint(payload: object) -> tuple[int, tuple[tuple[object, int, int], ...], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise CcefRepairError("invalid_repair", "CCEF repair produced an invalid item collection")
    items = payload["items"]
    member_counts: list[tuple[object, int, int]] = []
    for item in items:
        if not isinstance(item, dict):
            member_counts.append((None, 0, 0))
            continue
        nodes = item.get("nodes", [])
        annotations = item.get("annotations", [])
        member_counts.append(
            (
                item.get("kind"),
                len(nodes) if isinstance(nodes, list) else -1,
                len(annotations) if isinstance(annotations, list) else -1,
            )
        )
    return len(items), tuple(member_counts), len(_all_evidence_refs(payload))


def _all_evidence_refs(owner: object) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(owner, dict):
        for key, value in owner.items():
            if key == "evidence" and isinstance(value, list):
                refs.extend(reference for reference in value if isinstance(reference, dict))
            refs.extend(_all_evidence_refs(value))
    elif isinstance(owner, list):
        for value in owner:
            refs.extend(_all_evidence_refs(value))
    return refs


def _text_size(owner: object) -> int:
    total = 0
    if isinstance(owner, dict):
        for key, value in owner.items():
            if key in {
                "text",
                "move_text",
                "raw_text",
                "details",
                "caption",
                "alt_text",
                "title",
            } and isinstance(value, str):
                total += len(value)
            total += _text_size(value)
    elif isinstance(owner, list):
        total += sum(_text_size(value) for value in owner)
    return total


def _validate_authority(
    original: dict[str, Any], repaired: dict[str, Any], context: CcefPromptContext
) -> None:
    if _footprint(original) != _footprint(repaired):
        raise CcefRepairError("unauthorized_repair", "CCEF repair changed core content cardinality")
    if abs(_text_size(repaired) - _text_size(original)) > _MAX_TEXT_CHANGE:
        raise CcefRepairError("unauthorized_repair", "CCEF repair changed too much source text")
    expected = _expected_metadata(context)
    for key, value in expected.items():
        if repaired.get(key) != value:
            raise CcefRepairError("invalid_repair", "CCEF repair does not restore trusted metadata")
    trusted_evidence = {
        (entry.fragment.physical_page, entry.fragment.fragment_sha256)
        for page in context.pages
        for entry in page.fragments
    }
    for reference in _all_evidence_refs(repaired):
        page = reference.get("page")
        digest = reference.get("fragment_sha256")
        if (
            type(page) is not int
            or type(digest) is not str
            or (page, digest) not in trusted_evidence
        ):
            raise CcefRepairError("unauthorized_repair", "CCEF repair cites untrusted evidence")


def apply_ccef_repair(
    original: StructuredGenerationResponse,
    repair_response: StructuredGenerationResponse,
    context: CcefPromptContext,
    *,
    failure: BaseException | None = None,
) -> StructuredGenerationResponse:
    """Apply an identity-bound patch; the caller must rerun its complete validation chain."""

    if type(original) is not StructuredGenerationResponse:
        raise TypeError("original must be StructuredGenerationResponse")
    if type(repair_response) is not StructuredGenerationResponse:
        raise TypeError("repair_response must be StructuredGenerationResponse")
    if type(context) is not CcefPromptContext:
        raise TypeError("context must be CcefPromptContext")
    payload = _parse_payload(original)
    diagnostics = ccef_repair_diagnostics(original, failure, context=context)
    expected_diagnostics = {diagnostic.diagnostic_id for diagnostic in diagnostics}
    repair = decode_ccef_repair(repair_response)
    if repair.base_response_sha256 != _response_sha256(original):
        raise CcefRepairError("binding_mismatch", "CCEF repair does not match failed response")
    if not set(repair.resolves).issubset(expected_diagnostics):
        raise CcefRepairError("binding_mismatch", "CCEF repair references unknown diagnostics")
    if len(_canonical_json(repair.model_dump(mode="json")).encode("utf-8")) > _MAX_PATCH_BYTES:
        raise CcefRepairError("repair_too_large", "CCEF repair patch exceeds its byte limit")
    repaired = copy.deepcopy(payload)
    for operation in repair.operations:
        _apply_operation(repaired, operation)
    _validate_authority(payload, repaired, context)
    return original.model_copy(update={"content": _canonical_json(repaired)})


def _unique_objects_by_id(values: object) -> dict[str, dict[str, Any]] | None:
    if not isinstance(values, list):
        return None
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict) or type(value.get("id")) is not str:
            return None
        identity = value["id"]
        if identity in result:
            return None
        result[identity] = value
    return result


def _flow_projections(flow: object) -> tuple[list[str], list[str]] | None:
    if not isinstance(flow, list):
        return None
    moves: list[str] = []
    annotations: list[str] = []
    for entry in flow:
        if not isinstance(entry, dict):
            return None
        if entry.get("kind") == "move" and type(entry.get("node_id")) is str:
            moves.append(entry["node_id"])
        elif entry.get("kind") == "annotation" and type(entry.get("annotation_id")) is str:
            annotations.append(entry["annotation_id"])
        else:
            return None
    return moves, annotations


def _parents_precede_children(nodes: list[dict[str, Any]]) -> bool:
    seen: set[str] = set()
    for node in nodes:
        identity = node.get("id")
        parent = node.get("parent_id")
        if type(identity) is not str:
            return False
        if parent is not None and (type(parent) is not str or parent not in seen):
            return False
        seen.add(identity)
    return True


def _iter_owner_evidence(owner: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    evidence = owner.get("evidence")
    if isinstance(evidence, list):
        for index, reference in enumerate(evidence):
            if isinstance(reference, dict):
                yield reference, f"evidence/{index}"
    warnings = owner.get("warnings")
    if isinstance(warnings, list):
        for warning_index, warning in enumerate(warnings):
            if not isinstance(warning, dict):
                continue
            for reference, suffix in _iter_owner_evidence(warning):
                yield reference, f"warnings/{warning_index}/{suffix}"


def iter_ccef_evidence_refs(
    payload: dict[str, Any],
) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield only contract-owned EvidenceRef objects and their JSON Pointer suffixes."""

    items = payload.get("items")
    if isinstance(items, list):
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            for reference, suffix in _iter_owner_evidence(item):
                yield reference, f"items/{item_index}/{suffix}"
            if item.get("kind") != "move_sequence":
                continue
            for member_name in ("nodes", "annotations"):
                members = item.get(member_name)
                if not isinstance(members, list):
                    continue
                for member_index, member in enumerate(members):
                    if not isinstance(member, dict):
                        continue
                    for reference, suffix in _iter_owner_evidence(member):
                        yield reference, f"items/{item_index}/{member_name}/{member_index}/{suffix}"
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic_index, diagnostic in enumerate(diagnostics):
            if not isinstance(diagnostic, dict):
                continue
            for reference, suffix in _iter_owner_evidence(diagnostic):
                yield reference, f"diagnostics/{diagnostic_index}/{suffix}"


def canonicalize_ccef_response(
    response: StructuredGenerationResponse,
) -> tuple[StructuredGenerationResponse, tuple[dict[str, object], ...]]:
    """Canonicalize source-preserving redundancies before strict CCEF validation.

    This pass is deliberately narrow.  It canonicalizes mathematical-set NAGs
    and aligns node/annotation arrays to an exact-cover reading flow only when
    both sides contain the same unique identities and the resulting node order
    remains topological.  Anything requiring a choice between competing values
    remains work for the bounded model-repair path.
    """

    if type(response) is not StructuredGenerationResponse:
        raise TypeError("response must be StructuredGenerationResponse")
    payload = _parse_payload(response)
    repaired = copy.deepcopy(payload)
    items = repaired.get("items")
    if not isinstance(items, list):
        return response, ()

    operations: list[dict[str, object]] = []
    for evidence, suffix in iter_ccef_evidence_refs(repaired):
        if "physical_page" not in evidence:
            continue
        physical_page = evidence["physical_page"]
        if "page" not in evidence:
            evidence["page"] = physical_page
            del evidence["physical_page"]
            operations.append(
                {
                    "rule": "canonicalize_evidence_page_alias",
                    "path": f"/{suffix}",
                    "removed_field": "physical_page",
                }
            )
        elif evidence["page"] == physical_page:
            del evidence["physical_page"]
            operations.append(
                {
                    "rule": "remove_redundant_evidence_page_alias",
                    "path": f"/{suffix}",
                    "removed_field": "physical_page",
                }
            )
    for item_index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("kind") != "move_sequence":
            continue
        nodes = item.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            nags = node.get("nags")
            if not isinstance(nags, list) or not all(type(value) is int for value in nags):
                continue
            unique = list(dict.fromkeys(nags))
            if unique == nags:
                continue
            node["nags"] = unique
            operations.append(
                {
                    "rule": "deduplicate_nags",
                    "path": _pointer(("items", item_index, "nodes", node_index, "nags")),
                    "removed_count": len(nags) - len(unique),
                }
            )

        node_map = _unique_objects_by_id(nodes)
        annotations = item.get("annotations", [])
        annotation_map = _unique_objects_by_id(annotations)
        projections = _flow_projections(item.get("reading_flow"))
        if node_map is None or annotation_map is None or projections is None:
            continue
        move_refs, annotation_refs = projections
        if (
            len(move_refs) == len(node_map)
            and len(set(move_refs)) == len(move_refs)
            and set(move_refs) == set(node_map)
        ):
            projected_nodes = [node_map[identity] for identity in move_refs]
            if projected_nodes != nodes and _parents_precede_children(projected_nodes):
                moved_count = sum(
                    current.get("id") != projected.get("id")
                    for current, projected in zip(nodes, projected_nodes, strict=True)
                )
                item["nodes"] = projected_nodes
                nodes = projected_nodes
                operations.append(
                    {
                        "rule": "align_nodes_to_reading_flow",
                        "path": _pointer(("items", item_index, "nodes")),
                        "moved_count": moved_count,
                    }
                )
        if (
            len(annotation_refs) == len(annotation_map)
            and len(set(annotation_refs)) == len(annotation_refs)
            and set(annotation_refs) == set(annotation_map)
        ):
            projected_annotations = [annotation_map[identity] for identity in annotation_refs]
            if projected_annotations != annotations:
                moved_count = sum(
                    current.get("id") != projected.get("id")
                    for current, projected in zip(annotations, projected_annotations, strict=True)
                )
                item["annotations"] = projected_annotations
                operations.append(
                    {
                        "rule": "align_annotations_to_reading_flow",
                        "path": _pointer(("items", item_index, "annotations")),
                        "moved_count": moved_count,
                    }
                )

    if not operations:
        return response, ()
    return (
        response.model_copy(update={"content": _canonical_json(repaired)}),
        tuple(operations),
    )


def apply_deterministic_ccef_repairs(
    response: StructuredGenerationResponse,
) -> tuple[StructuredGenerationResponse, tuple[dict[str, object], ...]]:
    """Backward-compatible name for the shared pre-validation canonicalizer."""

    return canonicalize_ccef_response(response)


def ccef_repair_chain_document(
    original: StructuredGenerationResponse,
    repaired: StructuredGenerationResponse,
    *,
    deterministic_operations: tuple[dict[str, object], ...] = (),
    repair: StructuredGenerationResponse | None = None,
    repair_base: StructuredGenerationResponse | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "artifact_schema": "chess-workbench/ccef-repair-chain/2.1",
        "original_response": original.model_dump(mode="json"),
        "deterministic_operations": copy.deepcopy(list(deterministic_operations)),
        "repaired_content_sha256": _response_sha256(repaired),
    }
    if repair is not None:
        document["repair_base_content_sha256"] = _response_sha256(repair_base or original)
        document["repair_response"] = repair.model_dump(mode="json")
    return document


__all__ = [
    "CCEF_GENERAL_REPAIR_SCHEMA",
    "CcefRepairAdd",
    "CcefRepairDiagnostic",
    "CcefRepairError",
    "CcefRepairPatch",
    "CcefRepairRemove",
    "CcefRepairReplace",
    "apply_ccef_repair",
    "apply_deterministic_ccef_repairs",
    "build_ccef_repair_request",
    "canonicalize_ccef_response",
    "iter_ccef_evidence_refs",
    "ccef_repair_chain_document",
    "ccef_repair_diagnostics",
    "decode_ccef_repair",
]
