# Current plan

## Goal

Close the second Stage 4 product-review delta without starting a later product domain: make book
and video prose readable and source-traceable, make position explanations enter the ordered reading
flow atomically, and let Explorer reference cards reveal their original chapter context.

## Accepted baseline

- Stage 2A–2D: accepted on cumulative SQLite gates and real MySQL migrations/invariants.
- Stage 3A–3D: accepted; bounded multi-game PGN parse/import/export, Source CAS, immutable receipts,
  idempotent replay, semantic round-trip, and dual-database behavior are verified.
- `make acceptance-stage-4`: exit 0 on 2026-08-10 after both interactive-review fix sets.
- Full backend: 247 passed, 4 conditional MySQL skips; dedicated MySQL gate: 4/4 executed.
- Coverage: 92.47% line / 75.06% branch; critical PGN slices: 91.69–97.43%.
- Contracts, frontend checks/build, SQLite migration round-trip, and direct/proxy smoke: passed.
- Frontend: 26 unit/component tests and the fresh-database Chromium editor scenario passed.

## Stage 4 execution units

- [x] Close every Stage 2/3 audit blocker and pass the unique cumulative gate.
- [x] Stage 4 prerequisite: implement ADR 0006 CourseModule content blocks and deterministically
  backfill every existing/PGN Module with one MoveSequence block.
- [x] 4A: real Dashboard summary, searchable/filterable Learn catalog, Sources page, primary
  navigation, and generated contracts.
- [x] 4B: three-column editor with board interaction, authoritative move persistence, current-path
  navigation, ordered branches, transposition indication, initial/FEN creation, and reload.
- [x] 4C: Markdown editing/sanitized preview, source linking, reducer undo/redo, optimistic-conflict
  and network-failure recovery, history entry point, and atomic explorer publishing.
- [x] 4D: Chromium Playwright on a fresh temporary database covering the documented editor path,
  illegal raw HTTP move, retry/idempotency, accessibility, and desktop viewport matrix.
- [x] Run one cumulative `make acceptance-stage-4`, reconcile docs, and hand the user a direct
  interactive test command plus a short scenario checklist.

## Review boundary

- [x] Merge published Traditional Modules into existing Explorer graph components instead of
  creating one visible chapter per source Module.
- [x] Present Explorer graph entry positions rather than source chapter names in the left panel.
- [x] Highlight the selected square and all legal destinations with Lichess-style dot/ring markers.
- [x] Use the Lichess “fast” 100 ms movement animation and show destinations during drag start.
- [x] Add backend, component, and browser regressions; rerun the cumulative Stage 4 gate.
- [x] Add SourceSpan citations to narrative content blocks and include them in immutable history.
- [x] Add one transaction/API operation that creates a local KnowledgeNote and its ordered block.
- [x] Move traditional content into a wide, default reading surface with an explicit edit mode.
- [x] Add source-context drawers for Explorer reference cards without copying source prose.
- [x] Run the cumulative Stage 4 gate and reconcile the final evidence below.
- Next action after these checks: user resumes interactive product review or starts the revised
  Stage 6A → Stage 8 path.

## Non-negotiable acceptance

- SQL remains authoritative; `chess.js` may preflight interactions but `python-chess` validates
  every persisted move.
- All data assertions use APIs/database fixtures; screenshots are diagnostic only.
- Browser tests create their own temporary database and do not touch `data/` user content.
- No serious/critical axe violations; keyboard access and 1280×720, 1440×900, 1920×1080
  layouts are automated.
- The Stage 4 gate remains cumulative over the accepted Stage 3 gate.

## Deferred

- Stage 4E global graph visualization.
- Stage 5 repertoire/training and Stage 7 Lichess are deliberately postponed for the AI-book-first
  roadmap. Stage 6A job infrastructure (and optionally 6B analysis) precedes Stage 8; Stage 6
  integrations that require Stage 5 remain deferred rather than faking that dependency.
- Stage 8 PDF/OCR/AI is next after the required Stage 6 substrate; Stage 9 video can then reuse its
  review boundary.
- Collaboration.
