"""Focused behavior checks for the Stage 8D-5 chess editing commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.config import Settings
from chess_workbench.extraction.contracts import ExtractionPackageV1_1
from chess_workbench.extraction.validation import normalize_chess_moves_v1_1
from chess_workbench.review.editing import apply_review_edit
from chess_workbench.review.inspection import inspect_review_candidate
from chess_workbench.schemas.review import (
    PdfReviewAddLine,
    PdfReviewCommandRequest,
    PdfReviewDeleteSubtree,
    PdfReviewDocumentRead,
    PdfReviewMakeMainline,
    PdfReviewPageRead,
    PdfReviewPromoteVariation,
    PdfReviewSetNag,
)
from chess_workbench.services.pdf_review import PdfReviewReadService
from chess_workbench.services.pdf_review_ledger import (
    PdfReviewLedgerService,
    _canonical_package_bytes,
)
from chess_workbench.services.source_storage import store_content_addressed_bytes
from chess_workbench.store.models import (
    PdfReviewEvent,
    PdfReviewRevision,
    PdfReviewSession,
    utc_now,
)


def _package() -> ExtractionPackageV1_1:
    raw = ExtractionPackageV1_1.model_validate(
        {
            "schema_version": "chess-content-extraction/1.1",
            "package_id": "6f0c6c8a-4f3d-4b2a-9c1e-5d8f7a2b3c4d",
            "source": {
                "source_ref": "synthetic-review-editing",
                "media_type": "application/pdf",
                "page_range": {"start_page": 1, "end_page": 2},
            },
            "items": [
                {
                    "kind": "move_sequence",
                    "id": "seq1",
                    "title": "Synthetic line",
                    "evidence": [{"page": 1}],
                    "warnings": [
                        {
                            "code": "synthetic_warning",
                            "message": "Synthetic warning requires acknowledgement.",
                            "evidence": [{"page": 1}],
                        }
                    ],
                    "initial_position": {"kind": "startpos"},
                    "nodes": [
                        {
                            "id": "n1",
                            "parent_id": None,
                            "sibling_order": 0,
                            "move_text": "e4",
                            "evidence": [{"page": 1}],
                        },
                        {
                            "id": "n2",
                            "parent_id": "n1",
                            "sibling_order": 0,
                            "move_text": "e5",
                            "evidence": [{"page": 1}],
                        },
                        {
                            "id": "n4",
                            "parent_id": "n1",
                            "sibling_order": 1,
                            "move_text": "c5",
                            "evidence": [{"page": 2}],
                        },
                        {
                            "id": "n5",
                            "parent_id": "n4",
                            "sibling_order": 0,
                            "move_text": "Nf3",
                            "evidence": [{"page": 2}],
                        },
                        {
                            "id": "n3",
                            "parent_id": "n2",
                            "sibling_order": 0,
                            "move_text": "Nf3",
                            "evidence": [{"page": 1}],
                        },
                    ],
                    "annotations": [
                        {
                            "id": "a1",
                            "text": "Comment on the Sicilian branch.",
                            "anchor": {
                                "kind": "move_node",
                                "node_id": "n4",
                                "relation": "after",
                            },
                            "evidence": [{"page": 2}],
                        }
                    ],
                    "reading_flow": [
                        {"kind": "move", "node_id": "n1"},
                        {"kind": "move", "node_id": "n2"},
                        {"kind": "move", "node_id": "n4"},
                        {"kind": "annotation", "annotation_id": "a1"},
                        {"kind": "move", "node_id": "n5"},
                        {"kind": "move", "node_id": "n3"},
                    ],
                }
            ],
            "provenance": {
                "created_at": "2026-08-24T00:00:00Z",
                "adapter_name": "synthetic-test",
                "adapter_version": "1.1",
            },
        }
    )
    return normalize_chess_moves_v1_1(raw)


def _sequence(package: ExtractionPackageV1_1):
    item = package.items[0]
    assert item.kind == "move_sequence"
    return item


def test_board_line_uses_mainline_when_empty_and_last_variation_when_occupied() -> None:
    package = _package()
    continued = apply_review_edit(
        package,
        PdfReviewAddLine(
            kind="add_line",
            sequence_id="seq1",
            parent_node_id="n3",
            moves=["b8c6"],
            evidence_page=1,
        ),
    ).package
    sequence = _sequence(continued)
    added = next(node for node in sequence.nodes if node.id == "manual-1")
    assert added.parent_id == "n3"
    assert added.sibling_order == 0
    assert added.san_candidate == "Nc6"

    branched = apply_review_edit(
        package,
        PdfReviewAddLine(
            kind="add_line",
            sequence_id="seq1",
            parent_node_id="n1",
            moves=["c7c6"],
            evidence_page=2,
        ),
    ).package
    branch = next(node for node in _sequence(branched).nodes if node.id == "manual-1")
    assert branch.sibling_order == 2


def test_promote_variation_moves_it_up_one_priority() -> None:
    edited = apply_review_edit(
        _package(),
        PdfReviewPromoteVariation(kind="promote_variation", sequence_id="seq1", node_id="n4"),
    ).package
    sequence = _sequence(edited)
    assert next(node for node in sequence.nodes if node.id == "n4").sibling_order == 0
    assert next(node for node in sequence.nodes if node.id == "n2").sibling_order == 1


def test_make_mainline_promotes_every_branch_on_the_selected_path() -> None:
    edited = apply_review_edit(
        _package(),
        PdfReviewMakeMainline(kind="make_mainline", sequence_id="seq1", node_id="n5"),
    ).package
    sequence = _sequence(edited)
    assert next(node for node in sequence.nodes if node.id == "n4").sibling_order == 0
    assert next(node for node in sequence.nodes if node.id == "n5").sibling_order == 0


def test_delete_from_here_removes_subtree_and_its_anchored_annotation() -> None:
    edited = apply_review_edit(
        _package(),
        PdfReviewDeleteSubtree(kind="delete_subtree", sequence_id="seq1", node_id="n4"),
    ).package
    sequence = _sequence(edited)
    assert {node.id for node in sequence.nodes} == {"n1", "n2", "n3"}
    assert sequence.annotations == []
    assert [entry.node_id for entry in sequence.reading_flow if entry.kind == "move"] == [
        "n1",
        "n2",
        "n3",
    ]


class _LedgerSession:
    def __init__(
        self,
        review_session: PdfReviewSession,
        revision: PdfReviewRevision,
        event: PdfReviewEvent,
    ) -> None:
        self.review_session = review_session
        self.revisions = [revision]
        self.events = [event]

    async def scalar(self, statement: Any) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is PdfReviewSession:
            return self.review_session
        if entity is PdfReviewRevision:
            return self.revisions[-1]
        return None

    async def scalars(self, statement: Any) -> list[object]:
        entity = statement.column_descriptions[0]["entity"]
        if entity is PdfReviewRevision:
            return list(self.revisions)
        if entity is PdfReviewEvent:
            return list(self.events)
        return []

    def add_all(self, rows: tuple[object, ...]) -> None:
        now = utc_now()
        for row in rows:
            if isinstance(row, PdfReviewRevision):
                row.created_at = now
                self.revisions.append(row)
            elif isinstance(row, PdfReviewEvent):
                row.created_at = now
                self.events.append(row)

    async def flush(self) -> None:
        return None


async def test_review_command_appends_a_new_cas_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package()

    async def _direct_to_thread(function: Any, /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _direct_to_thread)
    package_bytes = _canonical_package_bytes(package.model_dump(mode="json"))
    stored = store_content_addressed_bytes(
        tmp_path, namespace="baseline", suffix=".json", raw_bytes=package_bytes
    )
    session_id = uuid4()
    run_id = UUID(str(package.package_id))
    now = datetime.now(UTC)
    review_session = PdfReviewSession(
        id=session_id,
        extraction_run_id=run_id,
        document_id=None,
        baseline_artifact_id=uuid4(),
        baseline_document_revision_id=None,
        baseline_ccef_sha256=stored.sha256,
        status="open",
        version=1,
        created_at=now,
        updated_at=now,
    )
    revision = PdfReviewRevision(
        id=uuid4(),
        session_id=session_id,
        parent_revision_id=None,
        revision_number=1,
        relative_path=stored.relative_path,
        media_type="application/json",
        byte_size=stored.size_bytes,
        package_sha256=stored.sha256,
        created_at=now,
    )
    event = PdfReviewEvent(
        id=uuid4(),
        session_id=session_id,
        revision_id=revision.id,
        parent_version=0,
        resulting_version=1,
        kind="created",
        decisions={},
        created_at=now,
    )
    fake = _LedgerSession(review_session, revision, event)
    baseline_document = PdfReviewDocumentRead(
        run_id=run_id,
        normalized_ccef_sha256=stored.sha256,
        package=package,
        inspection=inspect_review_candidate(package),
        pages=[
            PdfReviewPageRead(
                physical_page=1,
                media_type="image/png",
                byte_size=8,
                content_sha256="b" * 64,
                content_url=f"/api/pdf-extractions/{run_id}/review/pages/1",
            ),
            PdfReviewPageRead(
                physical_page=2,
                media_type="image/png",
                byte_size=8,
                content_sha256="c" * 64,
                content_url=f"/api/pdf-extractions/{run_id}/review/pages/2",
            ),
        ],
    )

    async def _read_document(self: PdfReviewReadService, target_id: UUID):
        del self
        assert target_id == run_id
        return baseline_document

    monkeypatch.setattr(PdfReviewReadService, "read_document", _read_document)
    service = PdfReviewLedgerService(
        cast(AsyncSession, fake),
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            source_storage_root=tmp_path,
            engine_worker_enabled=False,
        ),
    )
    result = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=1,
            command={
                "kind": "edit",
                "operation": PdfReviewSetNag(
                    kind="set_nag", sequence_id="seq1", node_id="n1", nag=3
                ),
            },
        ),
    )

    assert result.session.version == 2
    assert result.session.events[-1].kind == "edited"
    assert result.document.package.items[0].kind == "move_sequence"
    assert result.document.package.items[0].nodes[0].nags == [3]
    assert fake.revisions[-1].package_sha256 != stored.sha256
    assert fake.revisions[-1].parent_revision_id == revision.id

    acknowledged = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=2,
            command={
                "kind": "acknowledge",
                "issue_ids": ["item:seq1:warning:0"],
            },
        ),
    )
    assert acknowledged.session.events[-1].kind == "acknowledged"

    approved = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=3, command={"kind": "approve"}),
    )
    assert approved.session.status == "approved"

    reopened = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=4, command={"kind": "reopen", "reason": None}),
    )
    assert reopened.session.status == "open"

    rejected = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=5,
            command={"kind": "reject", "reason": "Not suitable for publication"},
        ),
    )
    assert rejected.session.status == "rejected"
    assert [event.kind for event in rejected.session.events[-5:]] == [
        "edited",
        "acknowledged",
        "approved",
        "reopened",
        "rejected",
    ]
