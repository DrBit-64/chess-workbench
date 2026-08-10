# Agent handoff

## Goal

Stage 6A–6D and the first interaction-review correction are cumulatively accepted. A second,
focused course-layout adjustment replaces keyboard entry/path chips with a four-column desktop
layout and clickable move score; it is awaiting user interaction review. Stage 5/6E and Stage 7
remain deferred by agreement.

## Working state

- Branch: `main`; accepted committed baseline: `d1a2f99 feat(codex): finish stage 4`.
- The worktree contains the uncommitted Stage 6A–6D implementation, Flash warning remediation and
  Codex final-review fixes as one working set. Do not commit, reset, rebase or split it without user
  permission.
- Migration `20260810_0009` and ADR 0009 define the SQL jobs, analysis cache and engine-game
  persistence boundary.
- Default delegated model is DeepSeek V4-Flash (`high`). Give it one bounded behavior at a time;
  architecture, concurrency, cross-module diagnosis and final review remain Codex-owned.

## Accepted Stage 6 behavior

- Durable SQL jobs provide claim leases, heartbeat, retry, cancellation, recovery, idempotency and
  SQL-backed invalidation events. WebSocket messages are hints; HTTP/SQL remains authoritative.
- Stockfish 18 analysis is bounded, cached by the complete identity, returns four White-POV PVs by
  default, and reaps engine processes on success, failure, timeout, cancellation and shutdown.
- Syzygy is probed before Stockfish and falls back explicitly when assets are absent.
- `/analysis` provides Lichess-shaped local settings, four scored lines, board interaction,
  play-from-position, review findings and save-to-traditional-course draft.
- Course boards have a collapsed-by-default live engine strip beneath a slightly smaller 560 px
  board. Enabling it automatically analyzes every selected/pending FEN, shows four compact PVs and
  draws three configurable first-move recommendation arrows.
- Course reading uses chapter directory | board/engine | narrow move score | prose/candidates on
  desktop. The numbered move score preserves its continuation while the user visits an earlier ply;
  keyboard/UCI move entry is deliberately absent.
- Explorer publication still merges source modules into one graph; ordered narrative and
  position-bound knowledge content remain distinct.
- Stage 6E was not built against placeholder Exercise tables.

## Codex final-review fixes

- Restored the required backend branch floor from 73% to **75%** and covered real worker/error
  branches instead of weakening the gate.
- Promoted `ResourceWarning` and `PytestUnraisableExceptionWarning` to errors and added per-test GC
  attribution. Non-worker API tests explicitly disable the installed Stockfish worker.
- Corrected the PGN concurrency test to issue four ASGI requests inside one application lifespan;
  it no longer races four test-client startup/shutdown sequences.
- Fixed engine-first game creation by initializing `EngineGame.moves`, avoiding async lazy-load
  `MissingGreenlet` after flush.
- Removed `setpgrp=True` from python-chess UCI startup because Python 3.13 translates it to
  `process_group`, which uvloop rejects. A real uvloop fake-engine regression and real Stockfish
  tests protect the supported path.
- Made `assert_health.py` accept the expected service name, allowing isolated Stage 6 E2E health
  validation without weakening payload checks.
- Replaced deprecated Ant Design course lists, supplied finite jsdom TextArea metrics, and retained
  focused regressions with clean stderr.
- Replaced Ant Design's low-contrast green completion tag with a project-owned WCAG-AA treatment;
  the browser Axe scan now passes.

## Interaction-review correction (2026-08-10)

- The reported `sqlite3.OperationalError: database is locked` was a real Stage 6 defect. The move
  endpoint held a read transaction while waiting for Stockfish, while the SQL worker heartbeat
  wrote on another connection. `play_game_move` now reads a snapshot, computes outside SQL and
  atomically writes both plies under the existing version/current-FEN guard.
- Synchronous analysis now reuses `process_analysis_job`'s short cache/persist transactions instead
  of holding an HTTP-owned transaction across Stockfish. Cache-hit responses still expose
  `from_cache=true`.
- `CourseEnginePanel.tsx` owns the course-local enable toggle, automatic FEN refresh, four-PV strip,
  time/MultiPV/thread/hash controls and independent recommendation-arrow controls. Stale browser
  requests are aborted and stale lines/arrows are cleared immediately.
- The course board forwards up to four MultiPV first moves through `customArrows`; default display is
  three translucent blue arrows. This is analysis-only and never creates an occurrence.
- Browser acceptance now exercises the embedded engine after saving a review course, checks WCAG
  A/AA and verifies no horizontal overflow at 1280, 1440 and 1920 px.
- The Sanic “PRODUCTION mode” line in `make dev-api` output is informational; the actual failure in
  the supplied log was the SQLite exception above. The stable single-process local mode is retained
  so the SQL worker is not duplicated by a development reloader.

Focused evidence before the cumulative gate:

- Backend Stage 6 API/engine: **24/24 passed**; Ruff and strict mypy pass.
- Frontend: **8 files / 35 tests passed**; 93.35% statements, 82.31% branches and 80.16%
  functions. Format/lint/typecheck pass.
- Chromium Stage 6 flow: **1/1 passed**, including the new course engine, WCAG A/AA and desktop
  overflow checks.
- The first full backend run measured 74.80% branch coverage after adding the concurrency path.
  Missing-resource and mate-terminal API paths were then covered without lowering the threshold;
  the cumulative result below confirms the restored floor.

## Final evidence (2026-08-10)

`make acceptance` exited 0 after the interaction correction and all final fixes:

- Backend static checks: Ruff format/lint and strict mypy pass.
- Full backend: **309 passed, 4 skipped**.
- Backend coverage: **91.62% line**, **75.00% branch** (thresholds 80%/75%).
- Resource lifecycle: strict warning gates pass with no unclosed SQLite/aiosqlite connection.
- MySQL disposable container: **4/4 passed** and container stopped.
- Real Stockfish 18, fake UCI under uvloop, Syzygy fixture and tool-manifest tests pass.
- SQLite migration round-trip and metadata drift check pass through revision `0009`.
- Frontend: **8 files, 35 tests passed**; format/lint/typecheck/build pass; coverage is 93.35%
  statements, 82.31% branches and 80.16% functions.
- OpenAPI/TypeScript contracts are deterministic and drift-free.
- Direct API/Vite-proxy smoke passes.
- Chromium Stage 6 E2E: **1/1 passed**. It covers the course-embedded live engine and arrows,
  capabilities, four PVs, background SQL work, play, review, save-to-course-draft, WCAG A/AA and
  1280/1440/1920 viewport overflow.
- `git diff --check` passes.

The cumulative evidence above predates the second course-layout adjustment. That adjustment changed
only frontend course layout/navigation and its Stage 4 E2E specification. Focused post-change
evidence: `CourseEditor.test.tsx` **11/11 passed**, frontend lint and typecheck pass. The user asked
to defer the cumulative and real-browser suites until the interactive UX is finalized.

## Interaction review checklist

Run the application with `make dev-api` and `make dev-web`, open a course, then check:

1. At desktop width, confirm the page is chapter directory | board | narrow move score |
   prose/candidates, and that no keyboard/UCI move field remains.
2. Follow several course moves. The score should group SAN by move number and White/Black; clicking
   an earlier ply changes the board while leaving the later score available to jump forward again.
3. The board is slightly smaller and an “引擎分析” strip appears directly beneath it.
4. Turning the strip on produces four scored lines for the current course position without clicking
   a separate Analyze button; following a course move refreshes those lines.
5. Three translucent recommendation arrows appear by default. Settings can hide them or change the
   count independently from the number of displayed PVs.
6. Changing time, lines, threads or hash triggers a fresh bounded calculation; turning analysis off
   removes the lines/arrows and stops further requests.

Then open `/analysis` and check:

1. The default position displays four readable PV rows with evaluation, WDL and moves.
2. Selecting a PV previews the line on the board; board selection and quick move animation feel
   natural.
3. Settings expose time, lines, threads, hash and Ponder-off explanation without offering values
   above server limits.
4. Background analysis visibly transitions through its durable job state and can be cancelled.
5. Play from both colors, including engine-first as Black, then review the game and save findings as
   a draft course.
6. A terminal FEN immediately shows a readable finished state.

Record any mismatch as a concrete interaction, expected result and screenshot. Do not begin Stage 8
until the user completes this review or explicitly waives it.

## Next route

After the interaction review, scope Stage 8A first: immutable source ingestion and extraction job
contracts that reuse Stage 6 SQL jobs/outbox, while preserving Source → Knowledge human review.
Do not start personal repertoire or Lichess import work unless the user changes the agreed order.
