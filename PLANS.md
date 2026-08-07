# Current plan

## Goal

Stage 3 complete. Next: Stage 4 — three-pane course editor MVP.

## Completed phases

| Stage | Status | Deliverables |
|-------|--------|-------------|
| 1 | ✅ | Engineering foundation, health, contracts, test harness, CI |
| 2 | ✅ | Domain model: Position, MoveEdge, Course, Occurrence, Source, Note |
| 2D | ✅ | Dual course mode (ADR 0005): `Course.mode`, `KnowledgeNote.source_note_id` |
| 3A | ✅ | Pure PGN parser → semantic tree (61 tests, 96.77%) |
| 3B | ✅ | PGN → graph/course import (9 tests, 86.11%) |
| 3C | ✅ | Course → PGN export + semantic comparator (10 tests, 88.24%) |
| 3D | ✅ | SQLite/MySQL dual-database gate (3 MySQL tests in CI) |
| 3 | ✅ | Aggregate: contracts + full verify + smoke |

## Stage 3 completion summary

### Verified by machine

```
make acceptance-stage-2        ✅ exit 0  (cumulative gate: 2A → 2D → contracts → verify → smoke)

Individual sub-unit gates:
├── make acceptance-stage-3a   ✅ 61/61 tests, 96.77% coverage  (PGN parser)
├── make acceptance-stage-3b   ✅  9/9  tests, 86.11% coverage  (PGN import)
├── make acceptance-stage-3c   ✅ 10/10 tests, 88.24% coverage  (PGN export + comparator)
└── make acceptance-stage-3d   ✅  3/3  tests                   (MySQL compat, CI only)
```

### Architecture decisions recorded

- `docs/decisions/0001` — Local-first modular monolith
- `docs/decisions/0002` — Position identity (`standard:v1:` key)
- `docs/decisions/0003` — MySQL async driver (`asyncmy 0.2.11`)
- `docs/decisions/0004` — Course context, occurrence layer, source hierarchy, lifecycle
- `docs/decisions/0005` — Dual course mode: traditional + opening_explorer

### New modules delivered in Stage 3

| Module | Purpose | Tests |
|--------|---------|-------|
| `logic/pgn.py` | Parse PGN text → immutable `PgnGame` semantic tree | 61 |
| `logic/pgn_import.py` | Atomic PGN tree → Course + Occurrence chain via `ContentService` | 9 |
| `logic/pgn_export.py` | Occurrence tree → valid PGN text (headers, variations, NAG, comments) | 10 (shared) |
| `logic/pgn_compare.py` | Semantic equivalence comparator between two `PgnGame` trees | — |
| `scripts/check_mysql.py` | Docker MySQL lifecycle management for local MySQL testing | — |
| `tests/test_mysql_compat.py` | Migration, CRUD, position-key uniqueness on real MySQL | 3 |

### Issues fixed during Stage 3

| Issue | Fix |
|-------|-----|
| PGN parser python-chess API (v1.x `game.variations`, `node.move`) | Used correct v1.x attributes |
| PGN export wrapped all children in `()` | Side-variation detection: index > 0 → `()`, main line plain |
| PGN export lost original headers | Importer stores headers in `Course.description` JSON |
| MySQL `cryptography` missing | Added `cryptography>=42,<45` to dependencies |
| MySQL coverage gate false failure in CI | `--no-cov` on MySQL compat step |
| OpenAPI tag ordering non-deterministic | `contracts.py` sorts tags by name before serialization |
| `Database.__init__` parsed MySQL URL as SQLite | Deferred SQLite dir check until after engine creation |

### Upcoming: Stage 4 — Three-pane course editor MVP

See `docs/development-plan.md` §4 for detailed breakdown.

## Agent notes

- **Codex** should review Stage 3 deliverables, then design Stage 4 editor architecture.
- **Deep Code** can implement well-specified sub-tasks once architectural decisions are recorded.
- See `docs/agent/HANDOFF.md` for detailed handoff state.
