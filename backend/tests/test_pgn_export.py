"""Adversarial semantic PGN export and comparator tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import chess
import pytest
from chess_workbench.api.app import ChessWorkbenchApp, create_app
from chess_workbench.config import Settings
from chess_workbench.logic.pgn import PgnHeader, PgnNode, parse_pgn, parse_pgn_document
from chess_workbench.logic.pgn_compare import compare_documents, compare_games
from chess_workbench.logic.pgn_export import (
    PgnExportError,
    _ExportNode,
    _headers,
    _move_tokens,
    _selected_occurrences,
    _validated_tree,
    export_import_pgn,
    export_module_pgn,
    export_pgn,
)
from chess_workbench.store.base import Base
from chess_workbench.store.models import (
    CourseModule,
    CourseOccurrence,
    MoveEdge,
    PgnImport,
    PgnOccurrenceAnnotation,
)
from sqlalchemy import select

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pgn"


def build_test_app(tmp_path: Path) -> ChessWorkbenchApp:
    return create_app(
        Settings(
            service_name=f"chess-workbench-pgn-export-{tmp_path.name}",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'pgn-export.db'}",
            source_storage_root=tmp_path / "data",
        )
    )


async def create_schema(app: ChessWorkbenchApp) -> None:
    async with app.ctx.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def import_text(client: Any, text: str) -> dict[str, Any]:
    _, response = await client.post("/api/pgn/imports", json={"pgn": text})
    assert response.status == 201, response.json
    return cast(dict[str, Any], response.json["import_receipt"])


async def test_all_twelve_golden_fixtures_round_trip_every_semantic_field(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)

    for path in sorted(FIXTURE_DIR.glob("*.pgn")):
        text = path.read_text()
        receipt = await import_text(client, text)
        game = receipt["games"][0]
        _, response = await client.get(
            f"/api/courses/{receipt['course_id']}/pgn?module_id={game['module_id']}"
        )
        assert response.status == 200, (path.name, response.json)
        comparison = compare_games(parse_pgn(text), parse_pgn(response.text))
        assert comparison.equivalent, (path.name, comparison.differences)
        assert response.text.rstrip().endswith(parse_pgn(text).result)


async def test_leaf_export_is_one_path_and_cross_module_leaf_is_rejected(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    receipt = await import_text(client, (FIXTURE_DIR / "02_one_variation.pgn").read_text())
    game = receipt["games"][0]

    async with app.ctx.database.session() as session:
        occurrences = list(
            await session.scalars(
                select(CourseOccurrence).where(
                    CourseOccurrence.module_id == UUID(game["module_id"])
                )
            )
        )
    children: dict[UUID, list[CourseOccurrence]] = {}
    for occurrence in occurrences:
        if occurrence.parent_id is not None:
            children.setdefault(occurrence.parent_id, []).append(occurrence)
    current = next(item for item in occurrences if item.parent_id is None)
    while children.get(current.id):
        current = min(children[current.id], key=lambda item: item.sort_order)
    leaf = current

    _, path_response = await client.get(
        f"/api/courses/{receipt['course_id']}/pgn?module_id={game['module_id']}"
        f"&leaf_occurrence_id={leaf.id}"
    )
    assert path_response.status == 200
    path_game = parse_pgn(path_response.text)
    assert path_game.result == "*"
    node = path_game.root
    while node.children:
        assert len(node.children) == 1
        node = node.children[0]

    other = await import_text(client, (FIXTURE_DIR / "01_mainline.pgn").read_text())
    foreign_root = other["games"][0]["root_occurrence_id"]
    _, cross_scope = await client.get(
        f"/api/courses/{receipt['course_id']}/pgn?module_id={game['module_id']}"
        f"&leaf_occurrence_id={foreign_root}"
    )
    assert cross_scope.status == 409
    assert cross_scope.json["code"] == "pgn_not_exportable"
    assert cross_scope.json["details"]["reason"] == "leaf_scope"


async def test_corrupted_occurrence_structure_fails_without_recursion(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    receipt = await import_text(client, (FIXTURE_DIR / "01_mainline.pgn").read_text())
    game = receipt["games"][0]
    async with app.ctx.database.session() as session, session.begin():
        occurrences = list(
            await session.scalars(
                select(CourseOccurrence).where(
                    CourseOccurrence.module_id == UUID(game["module_id"])
                )
            )
        )
        parent_ids = {item.parent_id for item in occurrences if item.parent_id is not None}
        leaf = next(
            item for item in occurrences if item.parent_id is not None and item.id not in parent_ids
        )
        leaf.parent_id = leaf.id

    _, response = await client.get(
        f"/api/courses/{receipt['course_id']}/pgn?module_id={game['module_id']}"
    )
    assert response.status == 409
    assert response.json["code"] == "pgn_not_exportable"
    assert response.json["details"]["reason"] in {"cycle", "unreachable"}


def test_comparator_detects_every_required_semantic_field_mutation() -> None:
    original = parse_pgn(
        '[Event "Compare"]\n[X-Custom "value"]\n[Result "*"]\n\n'
        "{root} 1. e4 $1 $3 {main} e5 ( {start} 1... c5 $2 {side} ) *"
    )
    first = original.root.children[0]
    main_reply = first.children[0]
    side_reply = first.children[1]

    mutations = [
        replace(
            original,
            header_items=(*original.header_items[:-1], PgnHeader("X-Changed", "v")),
        ),
        replace(original, result="1-0"),
        replace(original, root=replace(original.root, fen=original.root.fen.replace(" w ", " b "))),
        replace(original, root=replace(original.root, comment="changed root")),
        replace(original, root=replace(original.root, children=(replace(first, ply=99),))),
        replace(original, root=replace(original.root, children=(replace(first, san="d4"),))),
        replace(original, root=replace(original.root, children=(replace(first, uci="d2d4"),))),
        replace(original, root=replace(original.root, children=(replace(first, nags=(2,)),))),
        replace(
            original,
            root=replace(
                original.root,
                children=(
                    replace(first, children=(replace(main_reply, comment="changed"), side_reply)),
                ),
            ),
        ),
        replace(
            original,
            root=replace(
                original.root,
                children=(
                    replace(
                        first,
                        children=(main_reply, replace(side_reply, starting_comment="changed")),
                    ),
                ),
            ),
        ),
        replace(
            original,
            root=replace(
                original.root, children=(replace(first, children=(side_reply, main_reply)),)
            ),
        ),
        replace(original, root=replace(original.root, children=())),
    ]
    for mutation in mutations:
        comparison = compare_games(original, mutation)
        assert not comparison.equivalent, mutation
        assert comparison.differences


def test_comparator_handles_deep_tree_iteratively() -> None:
    moves: list[str] = []
    for fullmove in range(1, 751):
        moves.append(f"{fullmove}. Nf3 Nf6" if fullmove % 2 else f"{fullmove}. Ng1 Ng8")
    game = parse_pgn('[Result "*"]\n\n' + " ".join(moves) + " *")
    comparison = compare_games(game, game)
    assert comparison.equivalent

    two_games = parse_pgn_document('[Result "*"]\n\n*\n\n[Result "*"]\n\n*')
    document_comparison = compare_documents(two_games, parse_pgn_document('[Result "*"]\n\n*'))
    assert not document_comparison.equivalent
    assert document_comparison.differences == ("document: 2 vs 1 games",)


async def test_export_resource_bounds_and_receipt_corruption_are_stable(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)
    await create_schema(app)
    client = cast(Any, app.asgi_client)
    receipt = await import_text(client, (FIXTURE_DIR / "01_mainline.pgn").read_text())
    course_id = UUID(receipt["course_id"])
    module_id = UUID(receipt["games"][0]["module_id"])

    async with app.ctx.database.session() as session:
        with pytest.raises(PgnExportError, match="Course was not found") as missing_course:
            await export_module_pgn(session, uuid4(), module_id)
        assert missing_course.value.reason == "course_not_found"
        with pytest.raises(PgnExportError, match="Module was not found") as missing_module:
            await export_module_pgn(session, course_id, uuid4())
        assert missing_module.value.reason == "module_not_found"
        with pytest.raises(PgnExportError, match="node limit") as bounded:
            await export_module_pgn(session, course_id, module_id, max_nodes=0)
        assert bounded.value.reason == "node_limit"
        with pytest.raises(PgnExportError, match="leaf occurrence") as missing_leaf:
            await export_module_pgn(
                session,
                course_id,
                module_id,
                leaf_occurrence_id=uuid4(),
            )
        assert missing_leaf.value.reason == "leaf_not_found"
        with pytest.raises(PgnExportError, match="receipt") as missing_receipt:
            await export_import_pgn(session, uuid4())
        assert missing_receipt.value.reason == "import_not_found"
        with pytest.raises(PgnExportError, match="module_id") as module_required:
            await export_pgn(cast(Any, type("Service", (), {"session": session})()), course_id)
        assert module_required.value.reason == "module_required"

    async with app.ctx.database.session() as session, session.begin():
        imported = await session.get(PgnImport, UUID(receipt["id"]))
        assert imported is not None
        imported.game_count += 1
    async with app.ctx.database.session() as session:
        with pytest.raises(PgnExportError, match="inconsistent game set") as inconsistent:
            await export_import_pgn(session, UUID(receipt["id"]))
        assert inconsistent.value.reason == "game_count"


def _occurrence(
    *,
    occurrence_id: UUID | None = None,
    parent_id: UUID | None = None,
    edge_id: UUID | None = None,
    sort_order: int = 0,
    context: dict[str, object] | None = None,
    full_fen: str = chess.STARTING_FEN,
) -> CourseOccurrence:
    return CourseOccurrence(
        id=occurrence_id or uuid4(),
        course_id=uuid4(),
        module_id=uuid4(),
        parent_id=parent_id,
        position_id=uuid4(),
        inbound_move_edge_id=edge_id,
        full_fen=full_fen,
        sort_order=sort_order,
        context=context or {},
    )


def _edge(edge_id: UUID) -> MoveEdge:
    return MoveEdge(
        id=edge_id,
        from_position_id=uuid4(),
        to_position_id=uuid4(),
        uci="e2e4",
        san="e4",
    )


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("root_edge", "root_edge"),
        ("broken_parent", "broken_parent"),
        ("missing_edge", "missing_edge"),
        ("sibling_order", "sibling_order"),
        ("unreachable", "unreachable"),
    ],
)
def test_validated_tree_rejects_each_corrupt_shape(case: str, reason: str) -> None:
    root = _occurrence()
    edge_id = uuid4()
    child = _occurrence(parent_id=root.id, edge_id=edge_id)
    occurrences = {root.id: root, child.id: child}
    edges = {edge_id: _edge(edge_id)}
    if case == "root_edge":
        root.inbound_move_edge_id = edge_id
    elif case == "broken_parent":
        child.parent_id = uuid4()
    elif case == "missing_edge":
        edges.clear()
    elif case == "sibling_order":
        child.sort_order = 1
    else:
        first = _occurrence(parent_id=uuid4(), edge_id=edge_id)
        second = _occurrence(parent_id=first.id, edge_id=edge_id)
        first.parent_id = second.id
        occurrences.update({first.id: first, second.id: second})
    with pytest.raises(PgnExportError) as error:
        _validated_tree(root, occurrences, edges, {})
    assert error.value.reason == reason


def test_path_validation_headers_and_fallback_rendering() -> None:
    root = _occurrence(context={"pgn_comment": "root fallback"})
    edge_id = uuid4()
    child = _occurrence(
        parent_id=root.id,
        edge_id=edge_id,
        context={"pgn_comment": "move fallback"},
        full_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    )
    by_id = {root.id: root, child.id: child}
    assert set(_selected_occurrences(by_id, root, child.id)) == {root.id, child.id}

    broken = _occurrence(parent_id=uuid4(), edge_id=edge_id)
    with pytest.raises(PgnExportError) as broken_error:
        _selected_occurrences({root.id: root, broken.id: broken}, root, broken.id)
    assert broken_error.value.reason == "broken_parent"
    other_root = _occurrence()
    with pytest.raises(PgnExportError) as wrong_root:
        _selected_occurrences({root.id: root, other_root.id: other_root}, root, other_root.id)
    assert wrong_root.value.reason == "wrong_root"
    first = _occurrence(edge_id=edge_id)
    second = _occurrence(parent_id=first.id, edge_id=edge_id)
    first.parent_id = second.id
    with pytest.raises(PgnExportError) as cycle:
        _selected_occurrences({root.id: root, first.id: first, second.id: second}, root, second.id)
    assert cycle.value.reason == "cycle"

    module = CourseModule(
        id=uuid4(),
        course_id=uuid4(),
        title="Fallback",
        description="",
        sort_order=0,
    )
    fen = "8/8/8/8/8/8/4K3/7k w - - 0 1"
    headers = _headers(None, module, fen, "*")
    assert ("Result", "*") in headers
    assert ("FEN", fen) in headers
    assert ("SetUp", "1") in headers

    annotation = PgnOccurrenceAnnotation(
        occurrence_id=child.id,
        pgn_import_game_id=uuid4(),
        nags=[1, 3],
        starting_comment="before",
        comment="after } move",
    )
    node = _ExportNode(child, _edge(edge_id), annotation, [])
    tokens = _move_tokens(node)
    assert tokens == ["{before}", "1.", "e4", "$1", "$3", "{after ] move}"]
    fallback = _ExportNode(child, _edge(edge_id), None, [])
    assert _move_tokens(fallback)[-1] == "{move fallback}"
    with pytest.raises(PgnExportError) as missing_edge:
        _move_tokens(_ExportNode(child, None, None, []))
    assert missing_edge.value.reason == "missing_edge"


def _replace_first(root: PgnNode, child: PgnNode) -> PgnNode:
    """Kept explicit for mutation readability and type checking."""

    return replace(root, children=(child, *root.children[1:]))
