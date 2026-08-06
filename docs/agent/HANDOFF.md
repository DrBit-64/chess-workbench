# Agent handoff

## Current branch

`main`

## Base commit

(see `git log --oneline -5` for latest)

## Latest relevant commit

(see `git log --oneline -5` for latest)

## Current objective

Stage 2: position identity kernel and domain model implementation.
Sub-unit 2B is the current focus — graph model migrations, constraints, and repository layer.

## Completed

### Stage 1 (engineering foundation)
- pnpm workspace, uv project, Node 22/Python 3.13
- React 18 + Vite 7 + Router 7 + SWR + Ant Design 6 + Tailwind 4 shell
- Sanic app factory, Pydantic config, SQLAlchemy async SQLite
- `/api/health` with real `SELECT 1`; returns 503 on DB failure
- OpenAPI → openapi-typescript → frontend types generation chain
- ESLint, tsc, Vitest, Ruff, mypy, pytest, coverage, production build
- `make bootstrap`, `make verify`, `make smoke`, `make acceptance`
- GitHub Actions calling same `make acceptance`, frozen lockfiles
- Alembic base configuration (no business tables yet)

### Stage 2A
- `position_identity.py`: FEN validation, canonical_fen computation, position_key generation
- Error models for invalid_fen, illegal_position, invalid_uci, illegal_move
- Async MySQL driver config tests (asyncmy 0.2.11 locked)
- ADR 0002, 0003 accepted and present

### Stage 2B (partial)
- Graph models: Position, MoveEdge with mixins (UUID, UTC timestamps, version, archived)
- Database session factory with async SQLAlchemy + aiosqlite
- Graph repository: create_position, find_position_by_key, create_move_edge, etc.
- Migration: initial schema with positions, move_edges tables; unique constraint on position_key
- Concurrency tests for duplicate position_key insert convergence

## Files changed (recent)

### Stage 2B work
- `backend/src/chess_workbench/store/models/graph.py`
- `backend/src/chess_workbench/store/models/mixins.py`
- `backend/src/chess_workbench/store/graph_repository.py`
- `backend/src/chess_workbench/store/database.py`
- `backend/src/chess_workbench/store/base.py`
- `backend/migrations/` (Alembic migration files)
- `backend/tests/test_models.py`
- `backend/tests/test_graph_repository.py`
- `backend/tests/test_database.py`

### Stage 2C work (in progress)
- `backend/src/chess_workbench/store/models/content.py` — Course, CourseModule, Source, SourceVersion, SourceFile, SourceSpan, Occurrence, KnowledgeNote
- `backend/src/chess_workbench/store/content_repository.py`
- `backend/src/chess_workbench/schemas/domain.py` — Pydantic request/response contracts
- `backend/src/chess_workbench/api/graph.py` — Position/MoveEdge API endpoints
- `backend/src/chess_workbench/api/content.py` — Course/Source/Note CRUD endpoints
- `backend/src/chess_workbench/api/errors.py` — error response mapping
- `backend/src/chess_workbench/api/serializers.py` — model ↔ schema conversion
- `backend/tests/test_domain_schemas.py`
- `backend/tests/test_graph_api.py`

## Verification

| Target | Status |
|--------|--------|
| `make acceptance-stage-2a` | ✅ passes |
| `make acceptance-stage-2b` | 🔄 in progress |
| `make acceptance-stage-2c` | 🔄 in progress |
| `make acceptance-stage-2` | ⬜ not yet |

## Remaining work

1. Complete Stage 2B: ensure all repository tests pass with proper coverage
2. Complete Stage 2C: content models, occurrence CRUD, error contracts, API tests
3. Wire content API routes into the Sanic app
4. Run full `make acceptance-stage-2` and fix any failures
5. Regenerate OpenAPI and TypeScript types after all schema changes stabilize
6. Update PLANS.md to mark Stage 2 complete

## Important decisions

- `position_key` format: `standard:v1:<canonical_fen first 4 fields>` — excludes halfmove clock and fullmove number
- `full_fen` stored separately for game replay, fifty-move rule, and future tablebase queries
- MySQL async driver locked to `asyncmy 0.2.11`; SQLite default for MVP
- `Occurrence` carries course-specific context (NAG, sort_order, comments); global `MoveEdge` does not
- `Source` → `SourceVersion` → `SourceFile` three-layer hierarchy
- `SourceSpan` uses discriminated union (`whole | page | video | text`)
- All PATCH endpoints use `expected_version` for optimistic concurrency
- KnowledgeNote target must be explicitly local (`occurrence_id`) or global (`global_position` / `global_move`), never ambiguous
- Archival via `archived_at` timestamp; no hard deletes that cascade into shared graph rows

## Known risks

- Occurrence model adds complexity to "parent" queries — every navigation must carry course path context
- Graph traversal must have cycle detection and depth/node limits (especially for global graph view)
- `SourceSpan` primary keys must be stable since KnowledgeNote references them
- The asyncmy 0.2.11 wheel must remain available for Python 3.13; real MySQL testing only enters in Stage 3D
- Multiple courses sharing the same Position is correct behavior but can confuse UI expectations about "parent node"
