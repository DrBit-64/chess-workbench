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
    PdfReviewDetachPositionAnchor,
    PdfReviewDocumentRead,
    PdfReviewExcludeItem,
    PdfReviewMakeMainline,
    PdfReviewPageRead,
    PdfReviewPromoteVariation,
    PdfReviewReattachPreviewRequest,
    PdfReviewReattachVariation,
    PdfReviewResolveUnresolved,
    PdfReviewSetInitialPosition,
    PdfReviewSetNag,
)
from chess_workbench.services.content import ServiceError
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


def test_clearing_an_old_source_suffix_is_an_explicit_nag_override() -> None:
    from chess_workbench.extraction.notation import (
        NAG_OVERRIDE_EXTENSION,
        effective_move_nags,
    )

    package = _package()
    sequence = package.items[0]
    assert sequence.kind == "move_sequence"
    sequence.nodes[0].move_text = "e4!"
    assert sequence.nodes[0].nags == []
    assert effective_move_nags(sequence.nodes[0]) == [1]

    result = apply_review_edit(
        package,
        PdfReviewSetNag(kind="set_nag", sequence_id="seq1", node_id="n1", nag=None),
    )
    edited = result.package.items[0]
    assert edited.kind == "move_sequence"
    assert edited.nodes[0].move_text == "e4!"
    assert edited.nodes[0].nags == []
    assert edited.nodes[0].extensions[NAG_OVERRIDE_EXTENSION] is True
    assert effective_move_nags(edited.nodes[0]) == []


def test_explicitly_excluding_a_non_chess_figure_clears_its_blocker() -> None:
    package = _package()
    payload = package.model_dump(mode="json")
    payload["items"].append(
        {
            "kind": "figure",
            "id": "photo1",
            "figure_type": "photo",
            "caption": "Player portrait",
            "evidence": [{"page": 2}],
        }
    )
    with_figure = ExtractionPackageV1_1.model_validate(payload)
    assert inspect_review_candidate(with_figure).blocking_issue_count == 1

    result = apply_review_edit(
        with_figure,
        PdfReviewExcludeItem(kind="exclude_item", item_id="photo1"),
    )

    assert all(item.id != "photo1" for item in result.package.items)
    assert inspect_review_candidate(result.package).blocking_issue_count == 0
    assert result.decisions["operation"] == "exclude_item"


def test_detaching_an_unmatched_annotation_anchor_keeps_the_text_in_flow() -> None:
    payload = _package().model_dump(mode="json")
    sequence_payload = payload["items"][0]
    sequence_payload["annotations"][0]["anchor"] = {
        "kind": "position",
        "fen": "8/8/8/4k3/8/8/8/4K3 w - - 0 1",
    }
    package = ExtractionPackageV1_1.model_validate(payload)
    issue = next(
        issue
        for issue in inspect_review_candidate(package).issues
        if issue.code == "position_anchor_no_match"
    )
    before_flow = _sequence(package).reading_flow

    result = apply_review_edit(
        package,
        PdfReviewDetachPositionAnchor(
            kind="detach_position_anchor",
            issue_id=issue.issue_id,
        ),
    )

    sequence = _sequence(result.package)
    assert sequence.annotations[0].text == "Comment on the Sicilian branch."
    assert sequence.annotations[0].anchor is None
    assert sequence.reading_flow == before_flow
    assert inspect_review_candidate(result.package).blocking_issue_count == 0
    assert result.decisions == {
        "operation": "detach_position_anchor",
        "issue_id": issue.issue_id,
        "item_id": "seq1",
        "annotation_id": "a1",
    }


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

    async def get(self, entity: Any, identity: UUID) -> object | None:
        if entity is PdfReviewSession and identity == self.review_session.id:
            return self.review_session
        return None

    async def scalar(self, statement: Any) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is PdfReviewSession:
            return self.review_session
        if entity is PdfReviewRevision:
            number = statement.compile().params.get("revision_number_1")
            if number is None:
                return self.revisions[-1]
            return next(
                (revision for revision in self.revisions if revision.revision_number == number),
                None,
            )
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
    preview = await service.preview_reattach(
        session_id,
        PdfReviewReattachPreviewRequest(
            expected_version=1,
            operation=PdfReviewReattachVariation(
                kind="reattach_variation",
                sequence_id="seq1",
                node_id="n5",
                parent_node_id="n2",
            ),
        ),
    )
    assert preview.issue_count >= preview.blocking_issue_count
    assert len(fake.revisions) == 1
    assert review_session.version == 1

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
    edited_sha = fake.revisions[-1].package_sha256

    undone = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=2, command={"kind": "undo"}),
    )
    assert undone.session.version == 3
    assert undone.document.package.items[0].kind == "move_sequence"
    assert undone.document.package.items[0].nodes[0].nags == []
    assert fake.revisions[-1].package_sha256 == stored.sha256

    redone = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=3, command={"kind": "redo"}),
    )
    assert redone.session.version == 4
    assert redone.document.package.items[0].kind == "move_sequence"
    assert redone.document.package.items[0].nodes[0].nags == [3]
    assert fake.revisions[-1].package_sha256 == edited_sha

    undone_again = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=4, command={"kind": "undo"}),
    )
    assert undone_again.document.package.items[0].kind == "move_sequence"
    changed = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=5,
            command={
                "kind": "edit",
                "operation": PdfReviewSetNag(
                    kind="set_nag", sequence_id="seq1", node_id="n1", nag=4
                ),
            },
        ),
    )
    assert changed.document.package.items[0].kind == "move_sequence"
    assert changed.document.package.items[0].nodes[0].nags == [4]
    with pytest.raises(ServiceError):
        await service.apply_command(
            session_id,
            PdfReviewCommandRequest(expected_version=6, command={"kind": "redo"}),
        )

    acknowledged = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=6,
            command={
                "kind": "acknowledge",
                "issue_ids": ["item:seq1:warning:0"],
            },
        ),
    )
    assert acknowledged.session.events[-1].kind == "acknowledged"

    approved = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=7, command={"kind": "approve"}),
    )
    assert approved.session.status == "approved"

    reopened = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(expected_version=8, command={"kind": "reopen", "reason": None}),
    )
    assert reopened.session.status == "open"

    rejected = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=9,
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


def test_resolve_unresolved_restores_continuous_following_line_atomically() -> None:
    payload = _package().model_dump(mode="json")
    payload["items"].extend(
        [
            {
                "id": "miss1",
                "kind": "unresolved",
                "unresolved_type": "mixed",
                "reason_code": "ambiguous_relation",
                "raw_text": "1...e6?",
                "details": None,
                "evidence": [
                    {"page": 2, "fragment_sha256": "a" * 64, "start_offset": 0, "end_offset": 7}
                ],
            },
            {
                "id": "miss2",
                "kind": "unresolved",
                "unresolved_type": "mixed",
                "reason_code": "semantic_chunk_failed",
                "raw_text": "2.Nf3!",
                "details": None,
                "evidence": [
                    {"page": 2, "fragment_sha256": "b" * 64, "start_offset": 8, "end_offset": 13}
                ],
            },
        ]
    )
    package = ExtractionPackageV1_1.model_validate(payload)
    result = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="miss1",
            as_kind="line",
            sequence_id="seq1",
            anchor_node_id="n1",
            moves=["e7e6"],
            nags=[2],
            following=[{"item_id": "miss2", "moves": ["g1f3"], "nags": [1]}],
        ),
    )
    nodes = _sequence(result.package).nodes
    first = next(node for node in nodes if node.uci_candidate == "e7e6")
    second = next(
        node for node in nodes if node.parent_id == first.id and node.uci_candidate == "g1f3"
    )
    assert first.evidence == package.items[-2].evidence
    assert second.evidence == package.items[-1].evidence
    assert first.nags == [2]
    assert second.nags == [1]
    assert result.decisions["recovered_item_ids"] == ["miss2"]
    assert all(item.id not in {"miss1", "miss2"} for item in result.package.items)
    assert [item.id for item in package.items][-2:] == ["miss1", "miss2"]

    with pytest.raises(ValueError, match="illegal in its position"):
        apply_review_edit(
            package,
            PdfReviewResolveUnresolved(
                kind="resolve_unresolved",
                item_id="miss1",
                as_kind="line",
                sequence_id="seq1",
                anchor_node_id="n1",
                moves=["e7e6"],
                following=[{"item_id": "miss2", "moves": ["e7e5"]}],
            ),
        )
    assert [item.id for item in package.items][-2:] == ["miss1", "miss2"]


def test_source_first_repairs_are_local_review_revisions() -> None:
    payload = _package().model_dump(mode="json")
    payload["items"].append(
        {
            "id": "miss1",
            "kind": "unresolved",
            "unresolved_type": "mixed",
            "reason_code": "semantic_chunk_failed",
            "raw_text": "A book comment",
            "details": None,
            "evidence": [
                {"page": 2, "fragment_sha256": "a" * 64, "start_offset": 0, "end_offset": 14}
            ],
        }
    )
    package = ExtractionPackageV1_1.model_validate(payload)
    prose = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="miss1",
            as_kind="prose",
        ),
    ).package
    assert prose.items[-1].kind == "prose"
    assert prose.items[-1].text == "A book comment"
    assert package.items[-1].kind == "unresolved"

    annotation = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="miss1",
            as_kind="annotation",
            sequence_id="seq1",
            anchor_node_id="n4",
        ),
    ).package
    assert len(_sequence(annotation).annotations) == 2
    assert all(item.id != "miss1" for item in annotation.items)

    line = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="miss1",
            as_kind="line",
            moves=["e2e4", "e7e5"],
            nags=[2, None],
            initial_fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        ),
    ).package
    assert line.items[-1].kind == "move_sequence"
    assert [node.uci_candidate for node in line.items[-1].nodes] == ["e2e4", "e7e5"]
    assert [node.nags for node in line.items[-1].nodes] == [[2], []]

    from_existing_line = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="miss1",
            as_kind="line",
            sequence_id="seq1",
            anchor_node_id="n1",
            moves=["e7e6"],
        ),
    ).package
    added = next(
        node for node in _sequence(from_existing_line).nodes if node.uci_candidate == "e7e6"
    )
    assert added.evidence == package.items[-1].evidence
    assert all(item.id != "miss1" for item in from_existing_line.items)

    repositioned = apply_review_edit(
        package,
        PdfReviewSetInitialPosition(
            kind="set_initial_position",
            sequence_id="seq1",
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        ),
    ).package
    assert _sequence(repositioned).initial_position.kind == "fen"
    assert all(node.validation_status == "valid" for node in _sequence(repositioned).nodes)

    reattached = apply_review_edit(
        package,
        PdfReviewReattachVariation(
            kind="reattach_variation",
            sequence_id="seq1",
            node_id="n5",
            parent_node_id="n2",
        ),
    ).package
    moved = next(node for node in _sequence(reattached).nodes if node.id == "n5")
    assert moved.parent_id == "n2"
    assert moved.validation_status == "valid"


def test_reattach_accepts_printed_evaluation_suffix_on_legal_san() -> None:
    package = _package()
    move = next(node for node in _sequence(package).nodes if node.id == "n5")
    move.move_text = "Nf3!"
    assert move.san_candidate == "Nf3"
    changed = apply_review_edit(
        package,
        PdfReviewReattachVariation(
            kind="reattach_variation", sequence_id="seq1", node_id="n5", parent_node_id="n2"
        ),
    ).package
    moved = next(node for node in _sequence(changed).nodes if node.id == "n5")
    assert moved.parent_id == "n2"
    assert moved.validation_status == "valid"


def test_cross_sequence_reattachment_keeps_branch_note_and_source_order() -> None:
    payload = _package().model_dump(mode="json")
    other = payload["items"][0].copy()
    other["id"] = "seq2"
    other["nodes"] = [node for node in other["nodes"] if node["id"] in {"n1", "n2"}]
    other["annotations"] = []
    other["reading_flow"] = [
        {"kind": "move", "node_id": "n1"},
        {"kind": "move", "node_id": "n2"},
    ]
    payload["items"].append(other)
    package = ExtractionPackageV1_1.model_validate(payload)

    changed = apply_review_edit(
        package,
        PdfReviewReattachVariation(
            kind="reattach_variation",
            sequence_id="seq1",
            node_id="n4",
            target_sequence_id="seq2",
            parent_node_id="n1",
        ),
    ).package
    source, target = changed.items
    assert source.kind == target.kind == "move_sequence"
    assert {node.id for node in source.nodes} == {"n1", "n2", "n3"}
    assert next(node for node in target.nodes if node.id == "n4").parent_id == "n1"
    assert next(node for node in target.nodes if node.id == "n5").parent_id == "n4"
    assert all(node.validation_status == "valid" for node in target.nodes)
    assert [
        entry.node_id if entry.kind == "move" else entry.annotation_id
        for entry in target.reading_flow
    ] == ["n1", "n2", "n4", "a1", "n5"]
    assert target.annotations[0].anchor.node_id == "n4"
    assert source.annotations == []
    assert [entry.node_id for entry in source.reading_flow if entry.kind == "move"] == [
        "n1",
        "n2",
        "n3",
    ]


async def test_recovery_preview_confirms_exact_candidate_and_undoes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preview is read-only; a changed candidate cannot be silently saved."""
    from chess_workbench.review.recovery import RecoveryResult
    from chess_workbench.schemas.review import PdfReviewRecoveryPreviewRequest

    baseline = _package()
    candidate = apply_review_edit(
        baseline,
        PdfReviewSetNag(kind="set_nag", sequence_id="seq1", node_id="n1", nag=3),
    ).package
    assert isinstance(candidate, ExtractionPackageV1_1)
    raw = _canonical_package_bytes(baseline.model_dump(mode="json"))
    stored = store_content_addressed_bytes(
        tmp_path, namespace="baseline", suffix=".json", raw_bytes=raw
    )
    session_id = uuid4()
    run_id = UUID(str(baseline.package_id))
    now = datetime.now(UTC)
    row = PdfReviewSession(
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
    fake = _LedgerSession(row, revision, event)
    document = PdfReviewDocumentRead(
        run_id=run_id,
        normalized_ccef_sha256=stored.sha256,
        package=baseline,
        inspection=inspect_review_candidate(baseline),
        pages=[
            PdfReviewPageRead(
                physical_page=page,
                byte_size=8,
                content_sha256="b" * 64,
                content_url=f"/api/pdf-extractions/{run_id}/review/pages/{page}",
            )
            for page in (1, 2)
        ],
    )

    async def read_document(self: PdfReviewReadService, target_id: UUID):
        assert target_id == run_id
        return document

    async def fake_recovery(
        self: PdfReviewLedgerService,
        review_session: PdfReviewSession,
        current: ExtractionPackageV1_1,
    ) -> RecoveryResult:
        assert review_session.id == session_id
        assert current.package_id == baseline.package_id
        return RecoveryResult(candidate, ["source correction"], [(1, "e4", "seq1", "n1")], 0, 1, [])

    monkeypatch.setattr(PdfReviewReadService, "read_document", read_document)
    monkeypatch.setattr(PdfReviewLedgerService, "_recovery", fake_recovery)
    service = PdfReviewLedgerService(
        cast(AsyncSession, fake),
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            source_storage_root=tmp_path,
            engine_worker_enabled=False,
        ),
    )
    preview = await service.preview_recovery(
        session_id, PdfReviewRecoveryPreviewRequest(expected_version=1)
    )
    assert preview.candidate == candidate
    assert len(fake.revisions) == 1 and row.version == 1
    with pytest.raises(ServiceError) as stale:
        await service.apply_command(
            session_id,
            PdfReviewCommandRequest(
                expected_version=1,
                command={"kind": "recover_dependencies", "preview_sha256": "0" * 64},
            ),
        )
    assert stale.value.status == 409
    assert len(fake.revisions) == 1
    saved = await service.apply_command(
        session_id,
        PdfReviewCommandRequest(
            expected_version=1,
            command={"kind": "recover_dependencies", "preview_sha256": preview.preview_sha256},
        ),
    )
    assert saved.session.version == 2
    assert saved.session.events[-1].decisions["operation"] == "recover_dependencies"
    assert saved.document.package == candidate
    undone = await service.apply_command(
        session_id, PdfReviewCommandRequest(expected_version=2, command={"kind": "undo"})
    )
    assert undone.document.package == baseline


def test_source_prose_can_become_a_move_while_retaining_other_words() -> None:
    from chess_workbench.extraction.contracts import EvidenceRef, ProseItem

    package = _package()
    package.items.append(
        ProseItem(
            kind="prose",
            id="source-score",
            text="3...Nc6 is a developing move.",
            evidence=[EvidenceRef(page=2)],
        )
    )
    result = apply_review_edit(
        package,
        PdfReviewResolveUnresolved(
            kind="resolve_unresolved",
            item_id="source-score",
            as_kind="line",
            text="is a developing move.",
            sequence_id="seq1",
            anchor_node_id="n3",
            moves=["b8c6"],
        ),
    )
    sequence = next(item for item in result.package.items if item.kind == "move_sequence")
    assert any(node.uci_candidate == "b8c6" and node.parent_id == "n3" for node in sequence.nodes)
    assert any(
        item.kind == "prose" and item.text == "is a developing move."
        for item in result.package.items
    )
