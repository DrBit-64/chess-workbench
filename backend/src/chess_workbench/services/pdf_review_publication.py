"""Atomic one-way mapping from an approved review revision into a draft Course."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import (
    AnnotationFlowRef,
    EvidenceRef,
    MoveFlowRef,
    MoveNode,
    MoveSequenceItem,
    MoveSequenceItemV1_1,
    SequenceAnnotation,
)
from chess_workbench.schemas.domain import (
    CourseKnowledgeNoteBlockCreate,
    CourseModuleCreate,
    NormalizedBoundingBox,
    OccurrenceMoveCreate,
    PageSpan,
    RootOccurrenceCreate,
    SourceSpanCreate,
)
from chess_workbench.schemas.review import (
    PdfReviewExistingModuleTarget,
    PdfReviewModuleTarget,
    PdfReviewNewModuleTarget,
    PdfReviewPublicationPath,
    PdfReviewPublicationRead,
    PdfReviewPublicationSegment,
    PdfReviewPublishedSegmentRead,
    PdfReviewPublishRequest,
)
from chess_workbench.services.content import ContentService, ServiceError
from chess_workbench.services.pdf_review_ledger import PdfReviewLedgerService
from chess_workbench.store.models import (
    Course,
    CourseModule,
    PdfAsset,
    PdfExtractionDocument,
    PdfReviewPublication,
    PdfReviewRevision,
    PdfReviewSession,
    SourceSpan,
)

MAPPING_VERSION: Literal["review-course-publication/1.1"] = "review-course-publication/1.1"


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    publication: PdfReviewPublicationRead
    replayed: bool


@dataclass(frozen=True, slots=True)
class _Selection:
    sequence: MoveSequenceItem | MoveSequenceItemV1_1
    nodes: list[MoveNode]
    root_fen: str


class PdfReviewPublicationService:
    """Publish explicit, topology-closed move selections and their annotations."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.content = ContentService(session)

    async def publish(
        self, session_id: UUID, request: PdfReviewPublishRequest
    ) -> PublicationOutcome:
        if type(session_id) is not UUID:
            raise TypeError("session_id must be UUID")
        review_session = cast(
            PdfReviewSession | None,
            await self.session.scalar(
                select(PdfReviewSession).where(PdfReviewSession.id == session_id).with_for_update()
            ),
        )
        if review_session is None:
            raise ServiceError("not_found", 404, "PDF review session was not found")
        if review_session.version != request.expected_version:
            raise ServiceError(
                "stale_version",
                409,
                "expected version does not match the current PDF review session",
            )
        if review_session.status != "approved":
            raise ServiceError(
                "ambiguous_context",
                409,
                "only an approved PDF review revision can be published",
            )
        revision = cast(
            PdfReviewRevision | None,
            await self.session.scalar(
                select(PdfReviewRevision).where(
                    PdfReviewRevision.session_id == session_id,
                    PdfReviewRevision.revision_number == review_session.version,
                )
            ),
        )
        if revision is None:
            raise ServiceError("ambiguous_context", 409, "current review revision is unavailable")

        plan_sha256 = _plan_sha256(request)
        existing = cast(
            PdfReviewPublication | None,
            await self.session.scalar(
                select(PdfReviewPublication).where(
                    PdfReviewPublication.session_id == session_id,
                    PdfReviewPublication.revision_id == revision.id,
                    PdfReviewPublication.target_course_id == request.target_course_id,
                    PdfReviewPublication.mapping_version == request.mapping_version,
                    PdfReviewPublication.plan_sha256 == plan_sha256,
                )
            ),
        )
        if existing is not None:
            published = PdfReviewPublicationRead.model_validate(
                {**existing.result, "replayed": True}
            )
            return PublicationOutcome(publication=published, replayed=True)

        course = await self.session.get(Course, request.target_course_id)
        if course is None or course.archived_at is not None:
            raise ServiceError("not_found", 404, "target course was not found")
        if course.mode != "traditional" or course.status != "draft":
            raise ServiceError(
                "course_mode_conflict",
                409,
                "publication target must be a traditional draft course",
            )

        package = await PdfReviewLedgerService(self.session, self.settings).get_current_package(
            session_id
        )
        sequences = {
            item.id: item
            for item in package.items
            if isinstance(item, (MoveSequenceItem, MoveSequenceItemV1_1))
        }
        selections = [self._selection(sequences, segment) for segment in request.segments]
        asset = await self._source_asset(review_session)
        publication_id = uuid4()
        module_cache: dict[tuple[UUID | None, str], UUID] = {}
        used_target_modules: set[UUID] = set()
        span_cache = await self._span_cache(asset)
        published_segments: list[PdfReviewPublishedSegmentRead] = []

        for segment, selection in zip(request.segments, selections, strict=True):
            chapter_id, subsection_id, target_module_id = await self._resolve_path(
                course, segment.target, module_cache
            )
            if target_module_id in used_target_modules:
                raise ServiceError(
                    "ambiguous_context",
                    409,
                    "each publication segment must target a different chapter or subsection",
                )
            used_target_modules.add(target_module_id)
            roots = await self.content.repository.list_module_roots(target_module_id)
            if roots:
                raise ServiceError(
                    "resource_referenced",
                    409,
                    "the target chapter or subsection already contains a chess score",
                )
            result = await self._publish_selection(
                publication_id=publication_id,
                course=course,
                module_id=target_module_id,
                chapter_id=chapter_id,
                subsection_id=subsection_id,
                selection=selection,
                asset=asset,
                span_cache=span_cache,
            )
            published_segments.append(result)

        publication = PdfReviewPublicationRead(
            publication_id=publication_id,
            review_session_id=session_id,
            review_revision_number=review_session.version,
            target_course_id=course.id,
            mapping_version=MAPPING_VERSION,
            plan_sha256=plan_sha256,
            segments=published_segments,
            replayed=False,
        )
        receipt = PdfReviewPublication(
            id=publication_id,
            session_id=session_id,
            revision_id=revision.id,
            target_course_id=course.id,
            mapping_version=MAPPING_VERSION,
            plan_sha256=plan_sha256,
            result=publication.model_dump(mode="json", exclude={"replayed"}),
        )
        self.session.add(receipt)
        await self.session.flush()
        return PublicationOutcome(publication=publication, replayed=False)

    def _selection(
        self,
        sequences: dict[str, MoveSequenceItem | MoveSequenceItemV1_1],
        segment: PdfReviewPublicationSegment,
    ) -> _Selection:
        sequence = sequences.get(segment.sequence_id)
        if sequence is None:
            raise ServiceError("validation_error", 422, "publication sequence does not exist")
        selected_ids = set(segment.node_ids)
        nodes = [node for node in sequence.nodes if node.id in selected_ids]
        if len(nodes) != len(selected_ids):
            raise ServiceError("validation_error", 422, "publication node does not exist")
        external_parents = {node.parent_id for node in nodes if node.parent_id not in selected_ids}
        roots = [node for node in nodes if node.parent_id not in selected_ids]
        if len(external_parents) != 1 or not roots:
            raise ServiceError(
                "validation_error",
                422,
                "selected moves must form one parent-closed score fragment",
            )
        root_fens = {node.fen_before for node in roots}
        if None in root_fens or len(root_fens) != 1:
            raise ServiceError(
                "validation_error", 422, "selected score fragment has no unique start position"
            )
        for node in nodes:
            if (
                node.validation_status != "valid"
                or node.uci_candidate is None
                or node.fen_before is None
                or node.fen_after is None
            ):
                raise ServiceError(
                    "validation_error", 422, "selected score fragment contains an invalid move"
                )
        return _Selection(sequence=sequence, nodes=nodes, root_fen=cast(str, next(iter(root_fens))))

    async def _resolve_path(
        self,
        course: Course,
        path: PdfReviewPublicationPath,
        cache: dict[tuple[UUID | None, str], UUID],
    ) -> tuple[UUID, UUID | None, UUID]:
        chapter = await self._resolve_module(course, None, path.chapter, cache)
        if path.subsection is None:
            return chapter.id, None, chapter.id
        subsection = await self._resolve_module(course, chapter.id, path.subsection, cache)
        return chapter.id, subsection.id, subsection.id

    async def _resolve_module(
        self,
        course: Course,
        parent_id: UUID | None,
        target: PdfReviewModuleTarget,
        cache: dict[tuple[UUID | None, str], UUID],
    ) -> CourseModule:
        if isinstance(target, PdfReviewExistingModuleTarget):
            module = await self.session.get(CourseModule, target.module_id)
            if (
                module is None
                or module.archived_at is not None
                or module.course_id != course.id
                or module.parent_id != parent_id
            ):
                raise ServiceError(
                    "ambiguous_context",
                    409,
                    "selected chapter hierarchy does not belong to the target book",
                )
            return module

        assert isinstance(target, PdfReviewNewModuleTarget)
        key = (parent_id, target.title)
        cached_id = cache.get(key)
        if cached_id is not None:
            cached = await self.session.get(CourseModule, cached_id)
            assert cached is not None
            return cached
        max_sort_order = await self.session.scalar(
            select(func.max(CourseModule.sort_order)).where(
                CourseModule.course_id == course.id,
                CourseModule.parent_id.is_(None)
                if parent_id is None
                else CourseModule.parent_id == parent_id,
                CourseModule.archived_at.is_(None),
            )
        )
        sort_order = (int(max_sort_order) if max_sort_order is not None else -1) + 1
        created = await self.content.create_module(
            CourseModuleCreate(
                course_id=course.id,
                parent_id=parent_id,
                title=target.title,
                sort_order=sort_order,
            )
        )
        cache[key] = created.id
        module = await self.session.get(CourseModule, created.id)
        assert module is not None
        return module

    async def _publish_selection(
        self,
        *,
        publication_id: UUID,
        course: Course,
        module_id: UUID,
        chapter_id: UUID,
        subsection_id: UUID | None,
        selection: _Selection,
        asset: PdfAsset,
        span_cache: dict[tuple[object, ...], UUID],
    ) -> PdfReviewPublishedSegmentRead:
        selected_ids = {node.id for node in selection.nodes}
        sequence_span_ids = await self._spans(selection.sequence.evidence, asset, span_cache)
        root = await self.content.create_root_occurrence(
            RootOccurrenceCreate(
                course_id=course.id,
                module_id=module_id,
                fen=selection.root_fen,
                context={
                    "review_publication_id": str(publication_id),
                    "ccef_sequence_id": selection.sequence.id,
                    "source_span_ids": [str(value) for value in sequence_span_ids],
                },
            )
        )
        occurrence_by_node: dict[str, UUID] = {}
        children_by_parent: dict[str | None, list[MoveNode]] = {}
        for node in selection.nodes:
            parent_key = node.parent_id if node.parent_id in selected_ids else None
            children_by_parent.setdefault(parent_key, []).append(node)
        sibling_order: dict[str, int] = {}
        for children in children_by_parent.values():
            for index, child in enumerate(sorted(children, key=lambda value: value.sibling_order)):
                sibling_order[child.id] = index

        used_span_ids = set(sequence_span_ids)
        for node in selection.nodes:
            parent_occurrence_id = (
                occurrence_by_node[node.parent_id] if node.parent_id in selected_ids else root.id
            )
            node_span_ids = await self._spans(node.evidence, asset, span_cache)
            used_span_ids.update(node_span_ids)
            occurrence = await self.content.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=parent_occurrence_id,
                    uci=cast(str, node.uci_candidate),
                    nag=node.nags[0] if node.nags else None,
                    sort_order=sibling_order[node.id],
                    context={
                        "review_publication_id": str(publication_id),
                        "ccef_item_id": selection.sequence.id,
                        "ccef_node_id": node.id,
                        "source_span_ids": [str(value) for value in node_span_ids],
                    },
                )
            )
            if occurrence.full_fen != node.fen_after:
                raise ServiceError(
                    "ambiguous_context",
                    409,
                    "published move position does not match the approved review revision",
                )
            occurrence_by_node[node.id] = occurrence.id

        note_count = 0
        if isinstance(selection.sequence, MoveSequenceItemV1_1):
            for annotation, preceding_node_id in self._annotations_in_reading_order(selection):
                target_occurrence_id = self._annotation_target(
                    annotation,
                    selection,
                    selected_ids,
                    occurrence_by_node,
                    root.id,
                    preceding_node_id,
                )
                if target_occurrence_id is None:
                    continue
                annotation_span_ids = await self._spans(annotation.evidence, asset, span_cache)
                if len(annotation_span_ids) > 100:
                    raise ServiceError(
                        "validation_error", 422, "one annotation has too many source references"
                    )
                used_span_ids.update(annotation_span_ids)
                await self.content.create_course_knowledge_note_block(
                    module_id,
                    CourseKnowledgeNoteBlockCreate(
                        occurrence_id=target_occurrence_id,
                        markdown=(
                            annotation.text
                            if annotation.text_format == "markdown"
                            else _literal_markdown(annotation.text)
                        ),
                        source_span_ids=annotation_span_ids,
                        review_status="approved",
                    ),
                )
                note_count += 1

        return PdfReviewPublishedSegmentRead(
            sequence_id=selection.sequence.id,
            chapter_module_id=chapter_id,
            subsection_module_id=subsection_id,
            target_module_id=module_id,
            occurrence_count=len(selection.nodes) + 1,
            note_count=note_count,
            source_span_count=len(used_span_ids),
        )

    def _annotation_target(
        self,
        annotation: SequenceAnnotation,
        selection: _Selection,
        selected_ids: set[str],
        occurrence_by_node: dict[str, UUID],
        root_id: UUID,
        preceding_node_id: str | None,
    ) -> UUID | None:
        anchor = annotation.anchor
        if anchor is None:
            if preceding_node_id in selected_ids:
                return occurrence_by_node[preceding_node_id]
            sequence = selection.sequence
            assert isinstance(sequence, MoveSequenceItemV1_1)
            first_move = next(
                (
                    entry.node_id
                    for entry in sequence.reading_flow
                    if isinstance(entry, MoveFlowRef)
                ),
                None,
            )
            if preceding_node_id is None and first_move in selected_ids:
                return root_id
            return None
        if anchor.kind == "move_node":
            if anchor.node_id not in selected_ids:
                return None
            node = next(node for node in selection.nodes if node.id == anchor.node_id)
            if anchor.relation == "after":
                return occurrence_by_node[node.id]
            return (
                occurrence_by_node.get(node.parent_id, root_id)
                if node.parent_id is not None
                else root_id
            )
        matches = [root_id] if anchor.fen == selection.root_fen else []
        matches.extend(
            occurrence_by_node[node.id] for node in selection.nodes if node.fen_after == anchor.fen
        )
        if len(matches) != 1:
            raise ServiceError(
                "ambiguous_context",
                409,
                "position annotation does not identify one published occurrence",
            )
        return matches[0]

    @staticmethod
    def _annotations_in_reading_order(
        selection: _Selection,
    ) -> list[tuple[SequenceAnnotation, str | None]]:
        sequence = selection.sequence
        assert isinstance(sequence, MoveSequenceItemV1_1)
        annotations = {annotation.id: annotation for annotation in sequence.annotations}
        ordered: list[tuple[SequenceAnnotation, str | None]] = []
        preceding_node_id: str | None = None
        for entry in sequence.reading_flow:
            if isinstance(entry, MoveFlowRef):
                preceding_node_id = entry.node_id
            elif isinstance(entry, AnnotationFlowRef):
                ordered.append((annotations[entry.annotation_id], preceding_node_id))
        return ordered

    async def _source_asset(self, review_session: PdfReviewSession) -> PdfAsset:
        if review_session.extraction_run_id is not None:
            from chess_workbench.store.models import ExtractionRun

            run = await self.session.get(ExtractionRun, review_session.extraction_run_id)
            asset_id = run.pdf_asset_id if run is not None else None
        else:
            document = await self.session.get(PdfExtractionDocument, review_session.document_id)
            asset_id = document.pdf_asset_id if document is not None else None
        asset = await self.session.get(PdfAsset, asset_id) if asset_id is not None else None
        if asset is None:
            raise ServiceError("ambiguous_context", 409, "review source asset is unavailable")
        return asset

    async def _span_cache(self, asset: PdfAsset) -> dict[tuple[object, ...], UUID]:
        rows = list(
            await self.session.scalars(
                select(SourceSpan).where(
                    SourceSpan.source_version_id == asset.source_version_id,
                    SourceSpan.source_file_id == asset.source_file_id,
                    SourceSpan.locator_kind == "page",
                    SourceSpan.archived_at.is_(None),
                )
            )
        )
        return {_stored_span_key(row): row.id for row in rows}

    async def _spans(
        self,
        evidence: list[EvidenceRef],
        asset: PdfAsset,
        cache: dict[tuple[object, ...], UUID],
    ) -> list[UUID]:
        result: list[UUID] = []
        for ref in evidence:
            key = _evidence_key(ref)
            span_id = cache.get(key)
            if span_id is None:
                bbox = (
                    NormalizedBoundingBox(
                        x0=ref.bbox[0], y0=ref.bbox[1], x1=ref.bbox[2], y1=ref.bbox[3]
                    )
                    if ref.bbox is not None
                    else None
                )
                created = await self.content.create_source_span(
                    SourceSpanCreate(
                        source_version_id=asset.source_version_id,
                        source_file_id=asset.source_file_id,
                        locator=PageSpan(
                            page_number=ref.page,
                            bbox=bbox,
                            start_offset=ref.start_offset,
                            end_offset=ref.end_offset,
                            fragment_sha256=ref.fragment_sha256,
                        ),
                    )
                )
                span_id = created.id
                cache[key] = span_id
            if span_id not in result:
                result.append(span_id)
        return result


def _plan_sha256(request: PdfReviewPublishRequest) -> str:
    raw = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _bbox_key(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return (
            float(value["x0"]),
            float(value["y0"]),
            float(value["x1"]),
            float(value["y1"]),
        )
    values = cast(list[float], value)
    return (values[0], values[1], values[2], values[3])


def _evidence_key(ref: EvidenceRef) -> tuple[object, ...]:
    return (
        ref.page,
        _bbox_key(ref.bbox),
        ref.start_offset,
        ref.end_offset,
        ref.fragment_sha256,
    )


def _stored_span_key(row: SourceSpan) -> tuple[object, ...]:
    return (
        row.page_number,
        _bbox_key(row.bbox),
        row.start_value,
        row.end_value,
        row.fragment_sha256,
    )


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|>\-])")


def _literal_markdown(value: str) -> str:
    return _MARKDOWN_SPECIAL.sub(r"\\\1", value)


__all__ = ["MAPPING_VERSION", "PdfReviewPublicationService", "PublicationOutcome"]
