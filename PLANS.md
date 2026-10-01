# Current plan

2026-10-01: PDF extraction has been accepted for personal use. The current product path is v8 extraction → review → publication and v9 incremental extraction. New failures should be investigated from a real saved task. The six-book R5/P6 evaluation is deferred.

## Repository cleanup completed (2026-10-01)

1. Removed the GitHub Actions workflow and historical cumulative Stage acceptance targets. Keep small local checks and optional full verification.
2. Kept this file and docs/agent/HANDOFF.md short. Preserve older plans and investigation reports in the dated archive.
3. Retired legacy extraction creation from browser/API. Separate old candidate generation from shared PDF evidence handling. Preserve historical reads, reviews, publications and existing job recovery.
4. Archived one-off experiments and old delegation tooling; remove the unused PDFium probe.
5. Recorded focused checks, contract drift, a known stale frontend test file and diff review in docs/agent/HANDOFF.md.

## Product direction after cleanup

- Maintain the accepted PDF extraction, review and publication flow when a concrete user task fails.
- Prioritize reading and organizing chess-book explanations around key positions, pawn breaks and plans. The user may use Chessbook.com for a personal opening tree; do not build a competing tree without a clear need.
- Basic local backup is a practical near-term candidate. Training, FSRS, Lichess import, video, multi-source merging, deployment and collaboration await a fresh user decision.
- Source, Knowledge, Repertoire and Exercise remain distinct. Saved user data and human approval remain authoritative.

The previous 6,431-line task log is preserved at docs/archive/2026-10-01-before-cleanup/PLANS-historical.md. The original roadmap is at docs/archive/2026-10-01-before-cleanup/development-plan-historical.md.
