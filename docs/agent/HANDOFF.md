# Agent handoff

## Current branch

`main`

## Latest relevant commits

```
<latest> feat(dpsk): finish stage 3 (PGN round-trip + MySQL gate)
<previous> feat(dpsk): finish stage 2D (dual course mode)
acc1195 feat(codex): stage 2 step 1
62c8903 feat: finish stage 1
31d8a73 init
```

## Current objective

**Stage 3 is complete.** Next: Stage 4 — three-pane course editor MVP.

The `make acceptance-stage-2` gate exits 0 on clean checkout. All individual Stage 3 sub-unit gates also pass:

```
make acceptance-stage-3a   ✅ PGN parser (61 tests, 96.77%)
make acceptance-stage-3b   ✅ PGN import (9 tests, 86.11%)
make acceptance-stage-3c   ✅ PGN export + comparator (10 tests, 88.24%)
make acceptance-stage-3d   ✅ MySQL compat (3 tests, CI only)
```

## What was completed (Stage 3 by Deep Code)

### New modules

| Module | Purpose | Line coverage |
|--------|---------|---------------|
| `logic/pgn.py` | PGN text → immutable `PgnGame`/`PgnNode` semantic tree | 97% |
| `logic/pgn_import.py` | PgnGame tree → traditional Course + Occurrence chain via `ContentService` | 86% |
| `logic/pgn_export.py` | Occurrence tree → valid PGN text (headers, variations, NAG, comments) | 90% |
| `logic/pgn_compare.py` | Semantic equivalence comparator between two PgnGame trees | 85% |
| `scripts/check_mysql.py` | Docker MySQL lifecycle for local compat testing | — |
| `tests/test_mysql_compat.py` | Migration, CRUD, position-key uniqueness on real MySQL | — |

### New test files

| File | Tests | What it covers |
|------|-------|---------------|
| `tests/test_pgn_parser.py` | 61 | All 12 golden fixtures, structural, error, ply monotonicity |
| `tests/test_pgn_import.py` | 9 | Mainline, variations, NAG/comments, position sharing, transposition, errors |
| `tests/test_pgn_export.py` | 10 | 6 round-trips across all fixture types, full-parseability sweep, 3 comparator unit tests |
| `tests/test_mysql_compat.py` | 3 | Migration, CRUD, position-key uniqueness on real MySQL |

### Golden PGN fixtures (12 files)

`backend/tests/fixtures/pgn/`:
`01_mainline.pgn` · `02_one_variation.pgn` · `03_nested_variations.pgn` · `04_nag.pgn` ·
`05_braces_comment.pgn` · `06_semicolon_comment.pgn` · `07_unicode_comment.pgn` ·
`08_setup_fen.pgn` · `09_promotion.pgn` · `10_incomplete_result.pgn` ·
`11_multiple_variations.pgn` · `12_transposition.pgn`

### Infrastructure changes

- `pyproject.toml`: Added `cryptography>=42,<45` (required by `asyncmy` for MySQL 8.0+ auth)
- `.github/workflows/ci.yml`: MySQL 8.4 service container + `--no-cov` compat test step
- `scripts/contracts.py`: Sorts OpenAPI tags by name for deterministic generation
- `Makefile`: New targets `acceptance-stage-3b`, `acceptance-stage-3c`, `acceptance-stage-3d`
- `store/database.py`: Deferred SQLite directory creation until after engine init (fixes MySQL URL parsing crash)

### Issues fixed during Stage 3

| Issue | Fix |
|-------|-----|
| PGN parser python-chess v1.x API mismatch (`game.variations`, `node.move`) | Used correct v1.x attributes |
| PGN export wrapped all children in `(...)` | Side-variation detection: only index > 0 gets `()` |
| PGN export lost original headers (Date, White, Black, Round, Result) | Importer stores headers in `Course.description` JSON |
| MySQL `cryptography` missing → `caching_sha2_password` auth failure | Added `cryptography>=42,<45` |
| MySQL compat step failed CI coverage gate (39% < 80%) | `--no-cov` on compat step, global threshold only for main suite |
| OpenAPI tag ordering drifted between runs | `contracts.py` sorts tags by name before serialization |
| `Database.__init__` called `_prepare_sqlite_directory` on MySQL URLs | Refactored: check backend after engine creation, not before |

## Verification status at handoff

```
make acceptance-stage-2        ✅ exit 0  (cumulative: 2A → 2D → contracts → verify → smoke)
make acceptance-stage-2d       ✅ exit 0  (course mode + source_note_id)
make acceptance-stage-3a       ✅ exit 0  (61 tests, 96.77%)
make acceptance-stage-3b       ✅ exit 0  (9 tests, 86.11%)
make acceptance-stage-3c       ✅ exit 0  (10 tests, 88.24%)
make acceptance-stage-3d       ✅ exit 0  (local: skip when no MySQL; CI: 3/3 passed)
```

## Important decisions (carried forward)

- `position_key = standard:v1:<canonical-fen first 4 fields>`
- `full_fen` stored separately for replay/fifty-move/tablebase
- All PATCH endpoints use `expected_version` for optimistic concurrency
- KnowledgeNote target: explicit local (`occurrence_id`) or global (`position_id`/`move_edge_id`)
- Archival via `archived_at`; no hard deletes cascade into shared graph rows
- MySQL async driver: `asyncmy 0.2.11` + `cryptography>=42`
- All API schemas use `extra="forbid"`
- **Dual course mode (ADR 0005)**: `Course.mode ∈ {traditional, opening_explorer}`
- PGN round-trip is **semantic** equivalence, not byte-identical
- PGN headers stored in `Course.description` as JSON for round-trip fidelity
- **Chapter content block format (ADR 0006)**: Chapter = ordered Block sequence (`SectionHeader | NarrativeParagraph | MoveSequence | KnowledgeNote`). Board diagrams not stored. AI extraction produces this format directly. Implementation deferred to Stage 4.

## Known risks

- Chapter content block format (section titles, narrative paragraphs, move sequences) not yet defined — should be an ADR before Stage 4 or 8
- MySQL `mysql:8.4` service container tested in CI; local uses `mysql:8.0`
- PGN export uses `sort_order` for variation ordering; re-import order matches occurrence tree, not original text order

## Recommended next action

**Codex**: Review Stage 3 deliverables (start with `logic/pgn.py` → `pgn_import.py` → `pgn_export.py` → `pgn_compare.py`),
then design the Stage 4 three-pane course editor architecture. The chapter content block format (section titles,
narrative paragraphs, move sequences) should be decided via ADR before editor implementation begins.
