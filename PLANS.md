# Current plan

## Goal

Bring Stage 2 and Stage 3 back into agreement with their documented contracts and establish a
trustworthy automated acceptance gate before starting Stage 4.

The independent audit is recorded in `docs/agent/stage-2-3-audit.md`.

## Scope

- Resolve PGN-to-course semantics and API/idempotency ownership.
- Complete the Stage 2 Source/Span/KnowledgeNote HTTP boundary.
- Enforce accepted dual-course/source-note invariants.
- Make PGN import/export bounded, atomic, idempotent, and semantically testable.
- Establish real SQLite/MySQL migration and behavior parity gates.
- Restore documented coverage thresholds and cumulative Stage 3 gate wiring.
- Reconcile status and architecture documents after behavior is accepted.

## Out of scope

- Stage 4 UI/editor implementation.
- New frameworks or distributed components.
- Stage 5+ training, engines, Lichess, OCR, AI, or collaboration work.

## Current audited status

| Unit | Status |
|---|---|
| 2A | Accepted |
| 2B | Accepted on tested SQLite paths |
| 2C | Partial — Source/Span/Note APIs missing |
| 2D | Partial — stored fields exist; ADR invariants missing |
| 3A | Partial — basic parser only |
| 3B | Not accepted |
| 3C | Not accepted |
| 3D | Not accepted |

## Steps

- [x] Independently audit all `feat(dpsk)` Stage 2/3 changes, declared gates, and design edits.
- [x] Record reproducible counterexamples and update the shared handoff state.
- [x] Codex: decide and record PGN variation mapping, import identity/Source ownership,
  round-trip semantic scope, and HTTP transaction/path contracts.
- [x] DeepSeek (`DS-MYSQL-01`): repair MySQL migration downgrade and replace the false metadata
  test with a real Alembic `upgrade → check → downgrade → upgrade` gate. Execute only the bounded
  task in `docs/agent/tasks/DS-MYSQL-01.md`.
- [ ] DeepSeek: pin the MySQL image digest and make Stage 3 gates/CI cumulative after
  `DS-MYSQL-01` proves the real migration entry point.
- [ ] DeepSeek: add Source/SourceVersion/SourceFile/SourceSpan/KnowledgeNote CRUD routes and
  generated contract tests.
- [ ] DeepSeek: implement the accepted Course.mode and source-note invariants with migration,
  service, HTTP, and negative tests.
- [ ] DeepSeek: implement the accepted PGN APIs, Source/idempotency model, atomic rollback,
  typed errors, limits, and module/path export.
- [ ] DeepSeek: replace misleading fixtures and add all-12 semantic round-trip, comparator
  negative, long-input, duplicate-import, rollback, and dual-database tests.
- [ ] Codex: run final adversarial review and the repaired aggregate acceptance on clean SQLite
  and disposable MySQL.
- [ ] Only after every criterion is green, mark Stage 2/3 complete and begin Stage 4.

## Frozen architecture inputs

- ADR 0006 is accepted: a MoveSequence is an ordered source move tree; Stage 3 may represent one
  PGN game as an implicit block until the Stage 4 block migration.
- ADR 0007 maps every PGN game to one ordered Module occurrence tree. Traditional means
  source-organized/default-mainline reading, not branchless storage; transpositions merge only
  Position/MoveEdge.
- ADR 0008 fixes semantic round-trip scope, Source/CAS ownership, immutable import receipts,
  transport-independent idempotency, transaction ordering, HTTP/error contracts, and resource
  limits.

## Execution guard

Do not start DeepSeek in this working tree while Codex documentation changes are uncommitted.
Either obtain permission for an atomic documentation commit and then work sequentially, or create
an independent Git worktree/branch. Agents must not share one dirty working tree.

## Completion criteria

- Every Stage 2/3 deliverable and numbered automatic criterion in
  `docs/development-plan.md` has a direct automated test or an explicitly accepted revised ADR.
- Runtime OpenAPI and generated TypeScript expose the completed Source/Note and PGN contracts.
- Repeating one logical PGN import does not increase Course/Module/Occurrence/Position/Source
  counts and returns the original logical result.
- Any failed import leaves zero new business rows and returns a stable error containing ply/path.
- All 12 corrected golden fixtures pass semantic import/export/reimport checks; comparator
  mutation tests prove each required semantic field is actually compared.
- Oversized, over-node, over-depth, and over-time imports fail deterministically with 413/422
  without recursion crashes or partial writes.
- Multi-module/path export and traversal bounds have deterministic behavior.
- SQLite and MySQL both pass real Alembic upgrade/check/downgrade and shared API/domain fixtures.
- Global line coverage is at least 80%, global branch coverage at least 75%, and critical
  position/PGN modules at least 90% without exclusions that hide business branches.
- One cumulative Stage 3 command runs all focused gates, contracts, full verification, MySQL,
  and smoke; CI invokes that same semantic entry point.
- The final handoff lists exact commands, exit codes, coverage, skipped tests, and no unverified
  completion claims.
