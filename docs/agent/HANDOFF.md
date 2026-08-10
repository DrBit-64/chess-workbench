# Agent handoff

## Current branch and ownership

- Branch: `main`
- Review baseline: `0705701 feat(codex): pass DS-MYSQL-01`
- Worktree: uncommitted Codex changes spanning the accepted Stage 2/3 remediation and Stage 4
  editor MVP. Preserve the complete worktree; do not treat individual uncommitted files as
  independent patches.
- User-authorized boundary: Stage 4 implementation and both interactive-review fix sets are
  complete. Continue product review on request; otherwise the revised AI-book-first route starts at
  Stage 6A. Stage 4E remains optional backlog.

## Accepted status

| Unit | Status and evidence |
|---|---|
| 2A–2D | Accepted: position identity, graph persistence, content HTTP boundary, dual-course and citation/reference-card invariants |
| 3A–3D | Accepted: bounded semantic PGN parse/import/export, idempotent CAS/receipts, SQLite/MySQL parity |
| Stage 4 prerequisite | Accepted: ADR 0006 ordered content blocks, deterministic legacy/PGN backfill, lifecycle coupling |
| 4A | Accepted: real Dashboard, searchable/filterable Learn catalog, Sources page and navigation |
| 4B | Accepted: three-column editor, initial/FEN roots, board/click/UCI moves, Lichess-style legal targets, 100 ms animation, current path, branches, transpositions and reload |
| 4C | Accepted: readable ordered prose, SourceSpan citations, atomic note/block creation, sanitized Markdown, undo/redo, failure recovery, immutable history, source-context drawers and atomic position/path-merged Explorer publication |
| 4D | Accepted: fresh-database Chromium path, backend bypass rejection, retry/idempotency, accessibility and desktop viewports |

Required Stage 4 items remaining: **0**.

## Final cumulative verification (2026-08-10)

`make acceptance-stage-4` exited 0 with isolated ports and repository-pinned toolchains.

- Stage 2/3 focused cumulative gates passed; real pinned MySQL 8.4 ran 4/4 tests with no
  skip/xfail and stopped its disposable container.
- Backend full suite: 247 passed, 4 expected conditional MySQL skips in the ordinary SQLite run.
- Backend coverage: 92.47% line / 75.06% branch (floors: 80% / 75%).
- Frontend: format, ESLint, strict TypeScript, 26/26 Vitest tests and production build passed;
  frontend statement/branch coverage is 95.37% / 85.47%.
- OpenAPI/TypeScript drift check and SQLite empty→head→metadata check→base migration round-trip
  passed.
- Direct API and Vite-proxy smoke passed.
- Playwright: 1/1 full Chromium editor scenario passed against a fresh temporary SQLite database;
  it asserts readable/cited narrative persistence, atomic position notes, source-context navigation,
  merged publication, hidden source chapter names, real-board legal-target markers, axe
  serious/critical scan and 1280×720, 1440×900, 1920×1080 layouts.
- `make acceptance` is the stable alias for the same cumulative Stage 4 gate.

## First interactive-review delta

- `backend/src/chess_workbench/services/content.py` and
  `backend/tests/test_stage4_authoring.py`: merge publications by root Position and shared
  parent/MoveEdge path, preserve idempotent live note references, and cover empty/existing Explorer
  publication.
- `frontend/src/app/CourseEditor.tsx`, `boardInteraction.ts` and their tests: aggregate Explorer
  components into one course-level view, hide source Module titles, show legal-target feedback and
  use the 100 ms animation.
- `frontend/e2e/editor-mvp.spec.ts` and `frontend/src/styles.css`: assert the real rendered legal
  marker and merged Explorer flow in Chromium, then fix the select-placeholder contrast issue found
  by axe.
- `docs/decisions/0005-dual-course-mode.md`, `docs/development-plan.md`, `PLANS.md` and this handoff:
  record the revised product semantics, evidence and interactive-review boundary.
- No API schema or database migration was required for this feedback set.

## Stage 4 implementation highlights

- Migrations `0006`, `0007` and `0008` add ordered `CourseModule` blocks, immutable content
  revisions, Explorer publication receipts and narrative-to-SourceSpan citations. MySQL migration
  parity is covered by the cumulative gate.
- Module roots and MoveSequence blocks remain lifecycle-coupled. Replacing an archived root reuses
  its archived move block so ordering uniqueness cannot strand a module and its history is kept.
- Every persisted move goes through the backend `python-chess` validation path. `chess.js` only
  preflights drag, click-to-move and accessible keyboard UCI entry.
- Editor navigation is path-based and preserves local occurrence comments/NAG/source context while
  global Positions/MoveEdges merge transpositions.
- Markdown is sanitized before preview. Failed saves remain recoverable; retry does not duplicate
  writes. History is immutable and Explorer publication is atomic.
- Traditional courses default to a wide ordered reading surface. Narrative blocks support one or
  more SourceSpan citations; position-linked KnowledgeNotes are inserted into that flow in the same
  database transaction as the note itself. Explorer reference cards load adjacent source blocks in
  a context drawer without copying source prose into the Explorer.
- Explorer publication now reuses any occurrence at the source root Position, then merges each
  shared child by parent occurrence plus MoveEdge. Multiple publication receipts may intentionally
  point to one internal Module/component; disconnected FEN roots use anonymous entry labels instead
  of source chapter titles.
- Explorer UI aggregates all component editors at course level and groups equal entry Positions, so
  legacy pre-fix data is also presented as one position graph without exposing source Module names.
- Board click and drag-start selection show Lichess-style destination dots/capture rings plus
  selected/last-move highlights. Programmatic movement animation is fixed at the requested 100 ms.
- PGN import supports retry identity; Module and current-path PGN downloads use the accepted Stage 3
  semantic layer.
- Frontend routes are lazy-loaded. Playwright uses system Chromium when available and otherwise the
  installed browser; temporary database/source files and server processes are cleaned up.
- Make/smoke/E2E automatically fall back to `corepack pnpm` when no global `pnpm` binary exists.
- `make dev-api` now runs Alembic `upgrade head` before serving, so a first-time interactive launch
  does not fail with missing business tables.

## Interactive handoff

From the repository root:

```bash
cp .env.example .env  # only if .env does not already exist
make bootstrap
```

Then run `make dev-api` and `make dev-web` in separate terminals and open
`http://127.0.0.1:5173`.

Suggested product review path:

1. Add a manual Source.
2. Create a traditional Course and a Module from both the initial position and a custom FEN.
3. Enter moves by board drag/click and keyboard UCI; create two branches and switch paths.
4. Add root/move Markdown and a citation; refresh and confirm persistence.
5. Exercise undo/redo, history, PGN import, Module/current-line export and Explorer publication.
6. Publish two traditional chapters sharing the initial position, open the Explorer, and confirm
   there is one merged entry with combined branches and no source chapter-name list.
7. Select and drag pieces on the board; confirm legal empty destinations use dots, captures use
   rings, and movement feels like the 100 ms “fast” setting.
8. In a traditional chapter, add cited narrative prose and a position explanation, refresh, and
   confirm both appear in the ordered reading column; publish to Explorer and open the reference
   card's original-context drawer.

## Known non-blocking risks and deferred scope

- Ant Design emits `List` deprecation warnings in component tests; current behavior and production
  build are correct, but replace it before the next Ant major upgrade. jsdom also emits a harmless
  TextArea `NaN` height warning that does not reproduce in the Chromium acceptance path.
- Existing Explorer rows created before this fix are merged at the UI/query presentation layer;
  new publications merge physically. No destructive backfill migration was introduced.
- The global graph visualization is Stage 4E backlog and intentionally does not block the editor
  MVP or Stage 5.
- Stage 5 repertoire/training, Stage 6 engine/tablebase/job infrastructure, Stage 7 Lichess,
  Stage 8 OCR/AI and collaboration have not started.
- Source CAS orphan garbage collection remains deferred to Stage 8; committed SQL references are
  still checked for valid immutable assets.

## Next action

Collect any further interaction/visual feedback. When the user is ready to advance, start Stage 6A
(SQL-backed reliable jobs), then prioritize Stage 8. Stage 5 and Stage 7 are deliberately deferred;
the Stage 5-dependent engine answer-policy wiring remains the later Stage 6E integration tail.
