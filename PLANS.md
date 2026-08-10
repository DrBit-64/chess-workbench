# Current plan

## Goal

Deliver Stage 6A–6D before Stage 8: durable SQL jobs, bounded Stockfish MultiPV analysis and
caching, Syzygy-first routing, SQL-backed invalidation, plus play-from-position and
review-to-course-draft workflows. Stage 6E remains deferred until Stage 5 provides Exercise models.

## Immediate remediation gate

Stage 6A–6D and its post-implementation remediation have passed Codex review and cumulative
acceptance. The completed gate remains documented here so future agents do not regress it.

- [x] **Codex review:** audit the current `DS-STAGE6-ACCEPTANCE-CLEAN-01` diff. In particular,
  restore the required 75% branch-coverage floor and reject any claimed success obtained by
  lowering a quality gate.
- [x] **Flash-eligible atomic packet:** replace the two known Ant Design `List` usages in
  `CourseEditor.tsx` with semantic local markup and preserve empty states, selection styling,
  ordering, accessible names and button behavior. Remove the import and prove the focused test has
  no `[antd: List]` warning. This packet may touch only the component, its focused test and test
  setup if needed.
- [x] **Flash-eligible only after Codex fixes the oracle:** eliminate the two React `NaN` textarea
  height warnings using finite jsdom measurements; never suppress `console.error` or warnings.
- [x] **Codex-owned:** determine the actual SQLite/SQLAlchemy lifecycle leak with tracemalloc and
  warnings-as-errors. The allocation root is not yet reliably established and may span test-app
  lifecycle helpers, so V4-Flash must not guess or expand this task.
- [x] **Codex final gate:** verify Make wiring, coverage, resource cleanup and frontend warning
  output, then run the cumulative Stage 6 acceptance. No Stage 6 feature changes are in scope.

Acceptance for this remediation:

- `backend/tests/test_acceptance_wiring.py` passes and explicitly protects the complete Stage 6
  chain plus the stable alias.
- `CourseEditor.test.tsx` passes with none of: `[antd: List]`, ``NaN` is an invalid value`, or a
  blanket console-warning suppression.
- The relevant backend suite passes with `ResourceWarning` promoted to an error and no unclosed
  SQLite connection; the regression itself must not recursively launch an unbounded duplicate full
  suite.
- Backend format/lint/typecheck, frontend format/lint/typecheck/test, `git diff --check`, and the
  cumulative `make acceptance-stage-6` all pass. Record exact test counts; a partial run is not a
  completed ticket.

## Implementation status

- [x] 6A: generic SQL jobs, conditional claim, lease/heartbeat recovery, retry, cancellation,
  idempotency conflict protection, durable invalidation outbox and explicit state-machine tests.
- [x] 6B: bounded UCI adapter, pinned Stockfish 18 installer, fake/real integration tests,
  MultiPV=4 analysis/cache/API and Lichess-shaped analysis workspace/settings.
- [x] 6C: local Syzygy WDL/DTZ probe with best-WDL/DTZ ordering and graceful fallback,
  engine/tablebase policy boundaries, WebSocket invalidation plus authoritative HTTP polling.
- [x] 6D: durable play from arbitrary FEN, color/strength limits, terminal-position handling,
  review report and save-to-traditional-course draft.
- [x] Add a disposable real-browser Stage 6 flow for analysis, background work, play, review,
  course-draft persistence, accessibility and three desktop viewports.
- [x] Install the pinned real Stockfish 18 binary and run the real-engine/SQL/Chromium gates in a
  normal host environment.
- [x] Run cumulative `make acceptance` (stable alias for Stage 6) and record the final accepted
  evidence.

## Stage 6 interaction-review correction

The first user interaction review found that the standalone engine workspace did not yet satisfy
the primary course-reading workflow and exposed a real SQLite writer conflict. This correction is
part of Stage 6 completion, not a new stage.

- [x] Move interactive engine-game Stockfish work outside the database transaction, then atomically
  persist the user move and engine reply with the existing version/FEN compare-and-swap guard.
- [x] Reuse the short-transaction Syzygy/Stockfish cache path for synchronous analysis requests;
  preserve the API's `from_cache` behavior.
- [x] Add a collapsed-by-default engine strip beneath every course board. When enabled it
  automatically analyzes each selected/pending position and renders four compact scored PVs.
- [x] Slightly reduce the course board maximum width from 600 px to 560 px so the PV strip fits the
  reading layout without crowding the chapter text.
- [x] Draw the first move from up to four engine lines as Lichess-shaped blue recommendation arrows;
  default to three and expose independent arrow visibility/count controls.
- [x] Expose course-local engine time, MultiPV, arrow count, threads, hash and Ponder-off explanation
  in a settings drawer while preserving the standalone `/analysis` workspace.
- [x] Add deterministic SQLite concurrency, course-position refresh, arrow/settings, cache-hit,
  terminal-position, real-browser WCAG and 1280/1440/1920 overflow regressions.
- [x] Run the cumulative `make acceptance` gate and record the new exact evidence.

Acceptance for this correction:

- A worker/outbox write commits while an interactive engine move is still thinking, and the move
  later succeeds with both plies, one aggregate version increment and no `database is locked`.
- Enabling course analysis issues one bounded request for the current FEN; changing the selected
  course position aborts stale display work and renders the new position's result.
- Four PVs are shown by default, three first-move arrows are drawn by default, and the settings can
  change or disable those behaviors without persisting a course move.
- Backend line/branch and frontend statement/branch/function coverage floors remain unchanged.
- The real-browser Stage 6 flow includes the course engine, WCAG A/AA and three desktop viewports.

## Current machine evidence

- Final `make acceptance` exited 0 on 2026-08-10.
- Full backend: **309 passed, 4 skipped**; line coverage **91.62%**, branch coverage **75.00%**;
  strict `ResourceWarning`/unraisable-warning gates emitted no SQLite leak.
- Frontend: **8 files, 35 tests passed**; format/lint/typecheck/build pass; statement coverage
  **93.35%**, branch coverage **82.31%**, function coverage **80.16%**.
- MySQL disposable-container acceptance: **4/4 passed**, with container cleanup confirmed.
- Real Stockfish 18 and bundled Syzygy tests pass. The uvloop UCI startup regression passes.
- SQLite upgrade/head-check/downgrade/upgrade and deterministic OpenAPI contract checks pass.
- Smoke passed through both direct API and Vite proxy.
- Chromium Stage 6 E2E: **1/1 passed**, including the course-embedded four-PV engine and arrows,
  SQL job completion, play/review/draft, WCAG A/AA scan and 1280/1440/1920 viewport checks.

## Post-acceptance course-layout adjustment

The second interaction review prioritizes authored main lines over keyboard/UCI entry and moves the
course page to a four-column desktop reading layout.

- [x] Remove keyboard/UCI move entry while preserving drag and click-to-move board interaction.
- [x] Replace the path-chip row with a narrow, numbered White/Black move-score column between the
  board and prose. Historical plies are clickable without truncating the displayed continuation;
  choosing a different continuation replaces the displayed line.
- [x] Arrange desktop content as chapter directory | board/engine | move score | prose/candidates,
  with responsive fallback below 1180 px.
- [x] Update the Stage 4 browser specification so it no longer depends on deleted keyboard entry.

Focused verification for this adjustment: `CourseEditor.test.tsx` **11/11 passed**, frontend lint
and typecheck pass. Per the user's interaction-iteration instruction, cumulative acceptance and
real-browser regression are intentionally deferred until the Stage 6 UX is declared final.

## Non-negotiable acceptance

- SQL is authoritative; sockets only announce invalidation.
- Every engine child is bounded and reaped on success, timeout, cancellation, malformed output,
  crash and worker shutdown.
- Cache identity changes for the complete six-field FEN, source, reported engine version and every
  analysis parameter.
- Four PV rows are returned and rendered by default; PV moves are legal and all scores are White
  point of view.
- Missing Stockfish/Syzygy assets yield explicit capability/fallback states, never fake results.
- Stage 6E is not implemented against placeholder Exercise tables.

## Next route

The user should repeat the Stage 6 interaction review on both a course page and `/analysis`. After
that review and any final UX corrections, proceed directly to Stage 8 (8A → 8D). Stage 5/6E and
Stage 7 stay deferred as agreed.
