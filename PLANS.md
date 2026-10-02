# Current plan

2026-10-01: PDF extraction has been accepted for personal use. The current product path is v8 extraction → review → publication and v9 incremental extraction. New failures should be investigated from a real saved task. The six-book R5/P6 evaluation is deferred.

## Bounded asynchronous PDF extraction completed (2026-10-03)

[ADR 0027](docs/decisions/0027-bounded-async-pdf-extraction.md), the [C1–C4 plan](docs/agent/pdf-concurrency-plan-2026-10-03.md) and [implementation/acceptance record](docs/agent/pdf-concurrency-implementation-2026-10-03.md) are current. Two independent PDF jobs can await DeepSeek concurrently, a third stays queued, model calls share a two-slot limit, and local/native stages serialize. Paid responses have run-bound checkpoints; v8/v9 source relation semantics and review approval remain unchanged.

Normal website Endgame runs p66–68, p174–176 and p234–235 now have reviewable candidates. Raw source comparison covered 89/91 printed mainline plies and all six selected score branches; one human review command restored the remaining two plies. The first B/C runs exposed a diagram-orientation failure and a model output-budget failure; their original records remain. Generic fixes and successful new runs are documented, with the real output-split fallback still only fixture-tested. Catalan, Makogonov and reviewed v9 saved-response replay passed without new paid calls. Future PDF work remains driven by a concrete observed failure, not automatic resumption of broad R5/P6.

## Repository cleanup completed (2026-10-01)

1. Removed the GitHub Actions workflow and historical cumulative Stage acceptance targets. Keep small local checks and optional full verification.
2. Kept this file and docs/agent/HANDOFF.md short. Preserve older plans and investigation reports in the dated archive.
3. Retired legacy extraction creation from browser/API. Separate old candidate generation from shared PDF evidence handling. Preserve historical reads, reviews, publications and existing job recovery.
4. Archived one-off experiments and old delegation tooling; remove the unused PDFium probe.
5. Recorded focused checks, contract drift, a known stale frontend test file and diff review in docs/agent/HANDOFF.md.

## Lichess study export (2026-10-02)

The operator requested publishing a saved subsection or parent chapter from the course page to a new Lichess study. Official API/source feasibility is confirmed; implementation follows ADR 0024. It is a one-way PGN export with flattened chapter names and one-time study:write token-file setup. Lichess game import and bidirectional sync remain outside this slice.

## Long numbered opening theory (2026-10-02)

ADR 0025 implements the shared v8/v9 numbered-theory path and review outline. Earlier standalone and within-theory trials passed their limited checks; the user's actual multi-game 274–287 → 288–318 append **failed**: all 491 new moves went into example game 12, A3 lost 34 emitted moves through incomplete dependency repair, and the append omitted two previously approved manual moves. The saved result remains unchanged.

[ADR 0026](docs/decisions/0026-source-unit-scoped-incremental-review.md) contains the read-only investigation, source-derived expected structure, offline replay evidence and proposed sequence: S1 source ownership + reviewed baseline; S2 scoped relations + dependency repair; S3 notation normalization + missing-move summaries; S4 section-focused review + grouped repair; S5 real API acceptance against the actual multi-game predecessor. S1–S4 are implemented in the current working tree: reviewed append snapshot, source-scoped anchors, dependency/notation repair, and section-focused review with one-step group transfer. S5 passed saved-response replay and real-artifact offline checks. A no-provider website predecessor at p274–287 let the operator run the real p288–318 append once in the browser; the operator now reports that its chess-score quality is sufficient. The original failed document remains intact. The new review issue is bulk handling of non-score blockers: selected excludable items can be checked or drag-selected and removed in one undoable review revision. No model retry is needed for that workflow. Do not automatically resume broad R5/P6 evaluation.

## Product direction after cleanup

- Maintain the accepted PDF extraction, review and publication flow when a concrete user task fails.
- Prioritize reading and organizing chess-book explanations around key positions, pawn breaks and plans. The user may use Chessbook.com for a personal opening tree; do not build a competing tree without a clear need.
- Basic local backup is a practical near-term candidate. Training, FSRS, Lichess import, video, multi-source merging, deployment and collaboration await a fresh user decision.
- Source, Knowledge, Repertoire and Exercise remain distinct. Saved user data and human approval remain authoritative.

The previous 6,431-line task log is preserved at docs/archive/2026-10-01-before-cleanup/PLANS-historical.md. The original roadmap is at docs/archive/2026-10-01-before-cleanup/development-plan-historical.md.
