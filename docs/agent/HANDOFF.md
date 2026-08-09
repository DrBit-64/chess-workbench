# Agent handoff

## Current branch and baseline

- Branch: `main`
- Reviewed baseline: `a85eb03 feat(dpsk): update design docs`
- Working tree before this audit: clean
- Current working tree: uncommitted documentation-only audit/architecture/handoff changes listed
  below; do not mix them with another agent's edits.

## Current objective

Remediate the independent Stage 2/3 acceptance audit before starting Stage 4.

Stage 2 and Stage 3 were previously marked complete, but Codex's 2026-08-09 audit found
blocking requirement gaps and false-positive acceptance checks. The durable evidence and exact
remediation order are in `docs/agent/stage-2-3-audit.md`.

## Current status

| Unit | Status after independent audit |
|---|---|
| 2A position identity/domain kernel | Accepted |
| 2B SQLite graph persistence | Accepted on tested paths |
| 2C HTTP content boundary | Partial; Source/Span/Note APIs absent |
| 2D dual course mode/source-note link | Partial; fields exist, semantics not enforced |
| 3A PGN parser | Partial; basic parser works, lossless/bounded semantics do not |
| 3B PGN import | Not accepted |
| 3C PGN export/comparator | Not accepted |
| 3D MySQL parity | Not accepted; real Alembic downgrade fails |

Do not begin Stage 4 on the assumption that Stage 3 is complete.

## Verification completed by Codex

- `make acceptance`: exit 0 using pinned Node/pnpm and Python environments.
  - backend: 166 passed, 3 MySQL skipped, 2 connection-cleanup warnings;
  - actual backend line coverage: 86.72%;
  - actual backend branch coverage: 57.34% against the documented 75% target;
  - frontend: 5 passed; lint/typecheck/build passed;
  - SQLite migration, contracts, and smoke passed.
- Existing three MySQL tests pass against disposable MySQL 8.4, but they do not run Alembic.
- Real MySQL Alembic upgrade/check pass; downgrade to base fails with MySQL error 1553 at
  migration 0002's `ix_source_spans_source_version_id` drop.
- Runtime OpenAPI has no Source/Span/Note or PGN import/export paths.
- Same-PGN repeat import doubles Course/Module/Occurrence counts while Position count remains
  stable and Source remains zero.
- All-12 semantic PGN round-trip loses two root comments; all non-empty exports omit the movetext
  result marker; comparator counterexamples produce false positives.
- Legal 500-ply parsing and 1050-ply export hit bare recursion errors.

## Files changed by Codex in this handoff

- `docs/agent/stage-2-3-audit.md`: added detailed evidence and requirement matrix.
- `docs/agent/HANDOFF.md`: replaced the inaccurate completion handoff with audited state.
- `PLANS.md`: changed the active goal from Stage 4 to Stage 2/3 remediation.
- `docs/development-plan.md`: removed false Stage 2/3 completion labels while preserving the
  intended acceptance contract, then bound Stage 3 to the accepted PGN ADRs.
- `docs/decisions/0006-chapter-content-block-format.md`: accepted the Block decision and defined
  Stage 3's implicit MoveSequence transition.
- `docs/decisions/0007-source-ordered-pgn-variation-trees.md`: froze traditional/RAV/occurrence
  mapping and export scopes.
- `docs/decisions/0008-pgn-import-export-contract.md`: froze semantic preservation, Source/CAS,
  idempotency, HTTP, transaction, error, and resource contracts.
- `docs/decisions/README.md`, `docs/architecture/overview.md`, `AGENTS.md`: synchronized stable
  architecture and command references.
- `docs/agent/tasks/DS-MYSQL-01.md`: added the first bounded DeepSeek remediation packet.

No production code, tests, migrations, dependency files, or generated contracts were changed.

## Architecture decisions completed

ADR 0006–0008 now define the previously ambiguous Stage 3 behavior:

1. Traditional is source-organized with default-mainline reading; a MoveSequence may contain the
   author's ordered variation tree. Occurrences remain single-parent and transpositions merge only
   global Position/MoveEdge.
2. Raw bytes identify a reusable Source asset; an immutable receipt and canonical fingerprint
   identify one logical import across JSON/raw/multipart transports.
3. Semantic round-trip includes every game, all unique headers, full starting FEN, result,
   variation order, root/starting/normal comments, and all NAGs. Lexical formatting is not part of
   equality.
4. Import/CAS/SQL ordering, replay/conflict behavior, module/path/receipt export scopes, stable
   errors, and fixed resource limits are explicit in ADR 0008.

## Recommended next action

Run only `docs/agent/tasks/DS-MYSQL-01.md` with DeepSeek, then have Codex review its complete diff
and rerun the unique MySQL command. Before starting, either obtain explicit permission to commit
the current Codex documentation as one atomic handoff or create an independent worktree; never run
both agents against this dirty working tree.

The next architecture item still reserved for Codex is the full opening_explorer reference-card
and publishing invariant design. It must be frozen before assigning the Stage 2D invariant repair,
but it does not block DS-MYSQL-01.

## Known risks

- Existing green commands are not sufficient acceptance evidence until Make/CI coverage and
  dependency wiring are repaired.
- Source/Knowledge HTTP features cannot currently be used by a frontend.
- Current PGN import can create duplicate user content and partial writes if a future caller does
  not provide a correct outer transaction.
- Current Course/Occurrence lifecycle operations can create multiple active roots or cross-module
  paths.
- Source CAS orphan garbage collection is deliberately deferred to Stage 8; Stage 3 still must
  guarantee that committed SQL never references a missing or hash-mismatched file.

## Verification for this documentation step

- No formatter, type checker, application test, migration, or acceptance command was rerun because
  this step changes documentation only.
- The prior audit commands and results above remain the latest behavior evidence; they do not prove
  the new ADR contracts are implemented.
- `git diff --check`, trailing-whitespace scan, and changed-file/status review passed on
  2026-08-09; application behavior was intentionally not exercised by this docs-only step.
