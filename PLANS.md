# Current plan

## Goal

Complete Stage 2: position identity kernel, domain model, and core CRUD APIs.
This establishes the foundation all later stages depend on — getting the data semantics
right before building PGN round-trip, course editor, or training features.

## Current phase

**Stage 2 — in progress (2026-08-06)**

Stage 2 is organized as cumulative sub-units:

- **2A** — position_key normalization, FEN/move error models, async MySQL driver config
- **2B** — Position/MoveEdge migration, constraints, repositories
- **2C** — HTTP API boundary for Course/Module/Source/Span/Note CRUD + Occurrence
- **2** (aggregate) — full verify + smoke, proving the whole chain

Four ADRs have been accepted and implemented in code:
- ADR 0001: Local-first modular monolith
- ADR 0002: Position identity (`standard:v1:` key, canonical vs full FEN)
- ADR 0003: MySQL async driver (`asyncmy 0.2.11`)
- ADR 0004: Course context, occurrence layer, source hierarchy, lifecycle contracts

## Scope (Stage 2)

### In scope

- `position_key` normalization and python-chess validation
- `Position`, `MoveEdge` graph tables with uniqueness constraints
- `Source` / `SourceVersion` / `SourceFile` three-layer model
- `SourceSpan` discriminated union (page, video, text, whole)
- `Course`, `CourseModule` with `start_occurrence_id`
- `Occurrence` as course-scoped position references (not global edges)
- `KnowledgeNote` with explicit local/global target discrimination
- CRUD APIs with Pydantic `extra="forbid"` schemas
- Optimistic concurrency (`expected_version` → `stale_version`)
- Archival (soft delete with reference protection)
- Alembic migration round-trip (upgrade → check → downgrade)
- OpenAPI → TypeScript type regeneration

### Out of scope

- PGN import/export (Stage 3)
- Board UI / course editor (Stage 4)
- Repertoire / exercises (Stage 5)
- Stockfish / engine analysis (Stage 6)
- Lichess integration (Stage 7)
- PDF OCR / AI import (Stage 8)
- Video transcription (Stage 9)
- Docker deployment (Stage 10)
- Real-time collaboration (Stage 11)

## Steps

- [x] Stage 1: engineering foundation (health, CI, contracts, smoke)
- [x] ADR 0001–0004 accepted
- [x] 2A: position_identity module, FEN validation, config/URL tests
- [ ] 2B: graph models, constraints, repository, migration round-trip
- [ ] 2C: content models, occurrence, CRUD APIs, error contracts
- [ ] Acceptance-stage-2: full verify + smoke exits 0 on clean checkout

## Completion criteria (Stage 2)

1. `make acceptance-stage-2` exits 0 on clean checkout
2. Position identity vectors cover: normal moves, castling, en-passant, promotion,
   check, illegal FEN, illegal moves
3. Two different move orders reaching the same canonical position share one `Position` row
4. Course A and Course B saving different comments/NAGs on same edge do not pollute each other
5. Concurrent insert of identical `position_key` safely converges via unique constraint
6. API rejecting an illegal move returns deterministic 422 and leaves zero Position/MoveEdge
7. SQLite integration tests all green
8. Migration: `alembic upgrade head` from empty DB succeeds; `alembic check` reports no drift
9. Property test: random legal position → make one legal move → verify saved FEN matches
   python-chess authority
10. OpenAPI and TypeScript generated types show zero drift

## Agent notes

- Deep Code should focus on 2B and 2C implementation steps — model definitions,
  repository methods, API route wiring, and test fixtures.
- Codex should review the architecture-sensitive decisions (position_key semantics,
  occurrence context model, error contract shape) and handle cross-module integration.
- See `docs/agent/HANDOFF.md` for the latest state before starting any work.
