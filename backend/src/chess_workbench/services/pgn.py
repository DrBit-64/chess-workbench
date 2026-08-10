"""Atomic, idempotent PGN import application service and source CAS."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from chess_workbench.logic.pgn import (
    PgnDocument,
    PgnError,
    PgnGame,
    PgnNode,
    parse_pgn_document,
    semantic_hash,
)
from chess_workbench.schemas.domain import (
    CourseCreate,
    CourseModuleCreate,
    OccurrenceMoveCreate,
    OccurrenceUpdate,
    SourceCreate,
    SourceFileCreate,
    SourceSpanCreate,
    SourceVersionCreate,
    TextSpan,
    WholeSpan,
)
from chess_workbench.schemas.pgn import (
    ExistingCourseDestination,
    PgnDestination,
    PgnImportGameRead,
    PgnImportRead,
)
from chess_workbench.services.content import ContentService, ServiceError
from chess_workbench.store.models import (
    Course,
    CourseModule,
    PgnAsset,
    PgnImport,
    PgnImportGame,
    PgnOccurrenceAnnotation,
    utc_now,
)

MAX_PGN_BYTES = 5 * 1024 * 1024
MAPPING_VERSION = "pgn-occurrence:v1"


@dataclass(frozen=True, slots=True)
class PreparedPgnImport:
    raw_bytes: bytes
    document: PgnDocument
    content_sha256: str
    logical_fingerprint: str
    effective_key_hash: str
    destination: PgnDestination
    source_title: str | None
    game_titles: tuple[str, ...] | None
    relative_path: str
    replay_key_explicit: bool


@dataclass(frozen=True, slots=True)
class PgnImportOutcome:
    receipt: PgnImportRead
    replayed: bool


def prepare_pgn_import(
    raw_bytes: bytes,
    *,
    destination: PgnDestination,
    source_title: str | None,
    game_titles: list[str] | None,
    idempotency_key: str | None,
    storage_root: Path,
) -> PreparedPgnImport:
    if not raw_bytes:
        raise ServiceError("invalid_pgn", 422, "PGN payload must not be empty")
    if len(raw_bytes) > MAX_PGN_BYTES:
        raise ServiceError(
            "payload_too_large",
            413,
            f"PGN payload exceeds {MAX_PGN_BYTES} bytes",
            {"limit_bytes": MAX_PGN_BYTES, "actual_bytes": len(raw_bytes)},
        )
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ServiceError(
            "invalid_pgn",
            422,
            "PGN payload must be strict UTF-8",
            {"reason": "invalid_utf8", "start": error.start, "end": error.end},
        ) from error
    try:
        document = parse_pgn_document(text)
    except PgnError as error:
        raise ServiceError(
            error.kind,
            422,
            str(error),
            cast(dict[str, JsonValue], error.details()),
        ) from error
    if game_titles is not None and len(game_titles) != len(document.games):
        raise ServiceError(
            "validation_error",
            422,
            "game_titles length must equal the number of PGN games",
            {"expected": len(document.games), "actual": len(game_titles)},
        )

    content_hash = sha256(raw_bytes).hexdigest()
    destination_identity = destination.model_dump(mode="json")
    destination_identity.pop("expected_version", None)
    identity = {
        "destination": destination_identity,
        "source_title": source_title,
        "game_titles": game_titles,
        "mapping_version": MAPPING_VERSION,
    }
    canonical_options = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    fingerprint = sha256(
        ("pgn-import:v1" + content_hash + canonical_options).encode("utf-8")
    ).hexdigest()
    explicit = idempotency_key is not None
    effective_key = fingerprint
    if idempotency_key is not None:
        try:
            key_bytes = idempotency_key.encode("ascii", errors="strict")
        except UnicodeEncodeError as error:
            raise ServiceError(
                "validation_error",
                422,
                "Idempotency-Key must contain visible ASCII only",
            ) from error
        if not 1 <= len(key_bytes) <= 128 or any(byte < 0x21 or byte > 0x7E for byte in key_bytes):
            raise ServiceError(
                "validation_error",
                422,
                "Idempotency-Key must be 1..128 visible ASCII bytes",
            )
        effective_key = sha256(key_bytes).hexdigest()

    relative_path = f"sources/pgn/{content_hash[:2]}/{content_hash}.pgn"
    _store_cas(storage_root, relative_path, raw_bytes, content_hash)
    return PreparedPgnImport(
        raw_bytes=raw_bytes,
        document=document,
        content_sha256=content_hash,
        logical_fingerprint=fingerprint,
        effective_key_hash=effective_key,
        destination=destination,
        source_title=source_title,
        game_titles=tuple(game_titles) if game_titles is not None else None,
        relative_path=relative_path,
        replay_key_explicit=explicit,
    )


class PgnImportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        fault_injector: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self.session = session
        self.content = ContentService(session)
        self._fault_injector = fault_injector

    async def import_prepared(self, prepared: PreparedPgnImport) -> PgnImportOutcome:
        existing = await self._by_effective_key(prepared.effective_key_hash)
        if existing is not None:
            if existing.logical_fingerprint != prepared.logical_fingerprint:
                raise ServiceError(
                    "idempotency_conflict",
                    409,
                    "Idempotency-Key is already bound to a different logical import",
                )
            return PgnImportOutcome(await self._read(existing), replayed=True)

        course = await self._target_course(prepared)
        asset = await self._asset(prepared)
        self._fault("source", {"asset_id": asset.id})
        maximum_sort_order = await self.session.scalar(
            select(func.max(CourseModule.sort_order)).where(
                CourseModule.course_id == course.id,
                CourseModule.parent_id.is_(None),
            )
        )
        starting_sort_order = (maximum_sort_order if maximum_sort_order is not None else -1) + 1

        receipt = PgnImport(
            effective_key_hash=prepared.effective_key_hash,
            logical_fingerprint=prepared.logical_fingerprint,
            asset_id=asset.id,
            course_id=course.id,
            mapping_version=MAPPING_VERSION,
            game_count=len(prepared.document.games),
            occurrence_count=len(prepared.document.games),
            course_version=course.version,
        )
        self.session.add(receipt)
        await self.session.flush()

        total_occurrences = 0
        for game_index, game in enumerate(prepared.document.games):
            title = self._module_title(prepared, game, game_index)
            module = await self.content.create_module(
                CourseModuleCreate(
                    course_id=course.id,
                    title=title,
                    start_fen=game.root.fen,
                    sort_order=starting_sort_order + game_index,
                )
            )
            self._fault("module", {"game_index": game_index, "module_id": module.id})
            assert module.start_occurrence_id is not None
            span = await self.content.create_source_span(
                SourceSpanCreate(
                    source_version_id=asset.source_version_id,
                    source_file_id=asset.source_file_id,
                    locator=(
                        WholeSpan()
                        if len(prepared.document.games) == 1
                        else TextSpan(
                            start_offset=game.source_start,
                            end_offset=game.source_end,
                        )
                    ),
                )
            )
            game_row = PgnImportGame(
                pgn_import_id=receipt.id,
                game_index=game_index,
                module_id=module.id,
                root_occurrence_id=module.start_occurrence_id,
                source_span_id=span.id,
                headers=[
                    {"name": header.name, "value": header.value} for header in game.header_items
                ],
                movetext_result=game.result,
                semantic_hash=semantic_hash(game),
                occurrence_count=1,
            )
            self.session.add(game_row)
            await self.session.flush()
            occurrence_count = await self._import_game_tree(
                game,
                game_row,
                module.start_occurrence_id,
            )
            game_row.occurrence_count = occurrence_count
            self._fault("annotation", {"game_index": game_index})
            total_occurrences += occurrence_count

        if isinstance(prepared.destination, ExistingCourseDestination):
            # Mutating updated_at guarantees one actual ORM-versioned UPDATE;
            # assigning the existing title is optimized away and would leave
            # the Course version unchanged.
            course.updated_at = utc_now()
            await self.session.flush()
            receipt.course_version = course.version
        else:
            receipt.course_version = course.version
        receipt.occurrence_count = total_occurrences
        self._fault("receipt", {"receipt_id": receipt.id})
        await self.session.flush()
        return PgnImportOutcome(await self._read(receipt), replayed=False)

    async def get_import(self, import_id: UUID) -> PgnImportRead:
        row = await self.session.get(PgnImport, import_id)
        if row is None:
            raise ServiceError(
                "not_found",
                404,
                "PGN import receipt was not found",
                {"resource": "pgn_import", "id": str(import_id)},
            )
        return await self._read(row)

    async def _asset(self, prepared: PreparedPgnImport) -> PgnAsset:
        existing = await self.session.scalar(
            select(PgnAsset).where(PgnAsset.content_sha256 == prepared.content_sha256)
        )
        if existing is not None:
            return existing
        source = await self.content.create_source(
            SourceCreate(
                kind="pgn",
                title=self._safe_title(
                    prepared.source_title or f"PGN {prepared.content_sha256[:12]}"
                ),
            )
        )
        version = await self.content.create_source_version(
            SourceVersionCreate(source_id=source.id, label=prepared.content_sha256)
        )
        source_file = await self.content.create_source_file(
            SourceFileCreate(
                source_version_id=version.id,
                filename=f"paste-{prepared.content_sha256[:12]}.pgn",
                relative_path=prepared.relative_path,
                media_type="application/x-chess-pgn",
                size_bytes=len(prepared.raw_bytes),
                sha256=prepared.content_sha256,
            )
        )
        asset = PgnAsset(
            content_sha256=prepared.content_sha256,
            byte_size=len(prepared.raw_bytes),
            source_id=source.id,
            source_version_id=version.id,
            source_file_id=source_file.id,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def _target_course(self, prepared: PreparedPgnImport) -> Course:
        if isinstance(prepared.destination, ExistingCourseDestination):
            course = await self.session.get(Course, prepared.destination.course_id)
            if course is None:
                raise ServiceError("not_found", 404, "target Course was not found")
            if course.archived_at is not None or course.mode != "traditional":
                raise ServiceError(
                    "course_mode_conflict",
                    409,
                    "PGN imports require an active traditional Course",
                )
            if course.version != prepared.destination.expected_version:
                raise ServiceError(
                    "stale_version",
                    409,
                    "expected version does not match the target Course",
                    {
                        "expected": prepared.destination.expected_version,
                        "actual": course.version,
                    },
                )
            return course
        first_game = prepared.document.games[0]
        title = prepared.destination.title or prepared.source_title or first_game.header("event")
        created = await self.content.create_course(
            CourseCreate(title=self._safe_title(title or "Imported PGN"), mode="traditional")
        )
        row = await self.session.get(Course, created.id)
        assert row is not None
        return row

    async def _import_game_tree(
        self,
        game: PgnGame,
        game_row: PgnImportGame,
        root_occurrence_id: UUID,
    ) -> int:
        root = await self.content.get_occurrence(root_occurrence_id)
        context = self._compatibility_context(game.root)
        if game.root.nag is not None or context:
            await self.content.update_occurrence(
                root.id,
                OccurrenceUpdate(
                    expected_version=root.version,
                    nag=game.root.nag,
                    context=context,
                ),
            )
        self.session.add(self._annotation(game_row.id, root.id, game.root))

        count = 1
        stack: list[tuple[PgnNode, UUID, int]] = []
        for sort_order in range(len(game.root.children) - 1, -1, -1):
            stack.append((game.root.children[sort_order], root.id, sort_order))
        while stack:
            node, parent_id, sort_order = stack.pop()
            assert node.uci is not None
            occurrence = await self.content.create_move_occurrence(
                OccurrenceMoveCreate(
                    parent_occurrence_id=parent_id,
                    uci=node.uci,
                    nag=node.nag,
                    sort_order=sort_order,
                    context=self._compatibility_context(node),
                )
            )
            self.session.add(self._annotation(game_row.id, occurrence.id, node))
            count += 1
            self._fault(
                "occurrence",
                {"occurrence_id": occurrence.id, "ply": node.ply},
            )
            for child_order in range(len(node.children) - 1, -1, -1):
                stack.append((node.children[child_order], occurrence.id, child_order))
        await self.session.flush()
        return count

    async def _by_effective_key(self, key_hash: str) -> PgnImport | None:
        return cast(
            PgnImport | None,
            await self.session.scalar(
                select(PgnImport).where(PgnImport.effective_key_hash == key_hash)
            ),
        )

    async def _read(self, row: PgnImport) -> PgnImportRead:
        asset = await self.session.get(PgnAsset, row.asset_id)
        assert asset is not None
        games = list(
            await self.session.scalars(
                select(PgnImportGame)
                .where(PgnImportGame.pgn_import_id == row.id)
                .order_by(PgnImportGame.game_index)
            )
        )
        return PgnImportRead(
            id=row.id,
            created_at=row.created_at,
            asset_id=asset.id,
            source_id=asset.source_id,
            source_version_id=asset.source_version_id,
            source_file_id=asset.source_file_id,
            course_id=row.course_id,
            course_version=row.course_version,
            game_count=row.game_count,
            occurrence_count=row.occurrence_count,
            games=[
                PgnImportGameRead(
                    id=game.id,
                    game_index=game.game_index,
                    module_id=game.module_id,
                    root_occurrence_id=game.root_occurrence_id,
                    source_span_id=game.source_span_id,
                    occurrence_count=game.occurrence_count,
                )
                for game in games
            ],
        )

    @staticmethod
    def _annotation(
        game_id: UUID,
        occurrence_id: UUID,
        node: PgnNode,
    ) -> PgnOccurrenceAnnotation:
        return PgnOccurrenceAnnotation(
            occurrence_id=occurrence_id,
            pgn_import_game_id=game_id,
            nags=list(node.nags),
            starting_comment=node.starting_comment,
            comment=node.comment,
        )

    @staticmethod
    def _compatibility_context(node: PgnNode) -> dict[str, JsonValue]:
        context: dict[str, JsonValue] = {}
        if node.starting_comment:
            context["pgn_starting_comment"] = node.starting_comment
        if node.comment:
            context["pgn_comment"] = node.comment
        return context

    @staticmethod
    def _module_title(prepared: PreparedPgnImport, game: PgnGame, game_index: int) -> str:
        if prepared.game_titles is not None:
            return prepared.game_titles[game_index]
        event = game.header("event")
        if event and event != "?":
            return PgnImportService._safe_title(event)
        white = game.header("white")
        black = game.header("black")
        if white and black and (white != "?" or black != "?"):
            return PgnImportService._safe_title(f"{white} vs {black}")
        return f"Game {game_index + 1}"

    @staticmethod
    def _safe_title(value: str) -> str:
        stripped = value.strip()
        return (stripped or "Imported PGN")[:200]

    def _fault(self, phase: str, details: dict[str, object]) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase, details)


def _store_cas(
    storage_root: Path, relative_path: str, raw_bytes: bytes, expected_hash: str
) -> None:
    destination = storage_root / relative_path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = destination.read_bytes()
            if len(existing) != len(raw_bytes) or sha256(existing).hexdigest() != expected_hash:
                raise OSError("existing PGN CAS blob failed size/hash verification")
            return
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{expected_hash}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as handle:
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            if temporary_path.stat().st_size != len(raw_bytes):
                raise OSError("temporary PGN CAS blob size mismatch")
            if sha256(temporary_path.read_bytes()).hexdigest() != expected_hash:
                raise OSError("temporary PGN CAS blob hash mismatch")
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as error:
        raise ServiceError(
            "source_storage_unavailable",
            503,
            "PGN source storage is unavailable",
        ) from error
