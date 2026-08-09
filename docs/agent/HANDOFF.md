# Agent handoff

## Current branch and baseline

- Branch: `main`
- Review baseline: `949e304 docs: freeze stage 2 and 3 remediation contracts`
- Current working tree: uncommitted DS-MYSQL-01 implementation plus this Codex review update; do
  not start another task or mix in unrelated edits.

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
| 3D MySQL parity | Partial overall — DS-MYSQL-01 accepted; image digest and cumulative CI gate remain |

Do not begin Stage 4 on the assumption that Stage 3 is complete.

## Baseline verification before DS-MYSQL-01

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

The Codex architecture commit `949e304` changed no production code, tests, migrations, dependency
files, or generated contracts. The current uncommitted DeepSeek diff does change migrations and
tests as recorded below.

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

**DS-MYSQL-01 is accepted.** The next bounded implementation task may pin the MySQL 8.4 image by
digest and make the Stage 3/CI gates cumulative. Overall 3D remains partial until that wiring is
implemented and independently reviewed.

The next architecture item still reserved for Codex is the full opening_explorer reference-card
and publishing invariant design. It must be frozen before assigning the Stage 2D invariant repair.

### DS-MYSQL-01 implementation and Codex review record

- **Modified files**: `backend/migrations/versions/20260806_0002_content_context.py`,
  `backend/migrations/versions/20260806_0001_position_graph.py`,
  `backend/tests/test_mysql_compat.py`, `scripts/check_mysql.py`,
  `backend/tests/test_models.py`, `backend/tests/test_check_mysql_script.py`
- **Root cause**: Both migrations' downgrade functions called `drop_index()` before `drop_table()`
  on InnoDB. MySQL requires FK-enforcing indexes to remain until the table (and its FK) is dropped.
  `drop_table()` already cleans up all indexes; the explicit `drop_index()` calls were redundant
  and triggered MySQL error 1553.
- **Accepted fix**: Removing the redundant `drop_index` calls lets real MySQL complete
  `upgrade head → downgrade base → upgrade head`. Eight explicit index drops were removed across
  migrations 0001 and 0002. Codex accepted the `test_models.py` counterfactual assertion because
  restoring any explicit MySQL `DROP INDEX` makes it fail.
- **MySQL test rewrite**: Replaced `Base.metadata.create_all/drop_all` with real
  Alembic `upgrade("head") → downgrade("base") → upgrade("head")`. Tests pass
  `CHESS_WORKBENCH_DATABASE_URL` via monkeypatch; `_current_revision` and `_present_tables`
  use `create_async_engine` (the Alembic URL is `mysql+asyncmy`).
- **Unique acceptance command**: `uv run --project backend --locked python scripts/check_mysql.py --container`
- **Exit code**: 0
- **Passed**: 3/3 (test_migration_upgrade_check_downgrade_upgrade, test_mysql_crud_round_trip, test_mysql_position_key_uniqueness)
- **Container**: Started and stopped by the script (`--rm` flag). Output confirms "Container stopped".
- **Initial blocking omission (resolved)**: the migration test contained `pass` instead of the required
  `alembic.command.check(cfg)`. Codex ran `upgrade head → command.check(cfg)` directly against a
  fresh MySQL 8.4 container; it exited 0 with `No new upgrade operations detected`. The claimed
  variant-type false positive was not reproducible.
- **Initial order dependency (resolved)**: the autouse fixture only set an environment variable. On a fresh
  MySQL schema, running CRUD and position uniqueness before the migration test produced 2 failed /
  1 passed (`courses` and `positions` did not exist). A session fixture or equivalent must establish
  head schema independently of test collection order.
- **Initial cleanup weakness (resolved)**: `_stop_container()` ignored the Docker exit code, while `main()` always
  prints `Container stopped`; the script can therefore report cleanup success when cleanup failed.
- **Codex verification**:
  - unique command as submitted: exit 0, 3 passed, 0 skipped; container stopped;
  - direct real-MySQL Alembic check: exit 0, no schema drift;
  - reversed test order on a fresh MySQL: exit 1, 2 failed / 1 passed;
  - changed-file Ruff format, Ruff lint, and mypy: passed;
  - `git diff --check`: passed;
  - full backend check was not completed because concurrent local pytest activity caused an
    environment wait; it is not acceptance evidence.

Corrective acceptance still uses the same unique command. It must execute a real
`upgrade → check → downgrade → upgrade` cycle, provide order-independent schema setup, fail if
container cleanup fails, and report 3 executed tests with no skip/xfail. Do not mark 3D accepted
until Codex reruns the corrected command and the counterfactual order check.

### Corrective-pass re-review

Resolved in the first corrective pass:

- the real `alembic.command.check(cfg)` executes;
- a session-scoped fixture establishes Alembic head independently of test order;
- the unique container command passed 3/3 and the reversed node-id order passed 3/3 on separate
  fresh MySQL 8.4 containers;
- changed-file Ruff format/lint, mypy, the two focused migration-rendering tests, and
  `git diff --check` passed;
- with MySQL environment variables absent, all three integration tests skip without executing the
  session fixture.

Corrections made in the second pass:

1. ~~Regex~~ → `assert "DROP INDEX" not in downgrade_ddl`.
   Restoring `drop_index("ix_move_edges_to_position_id", ...)` in migration 0001
   now fails this assertion.
2. `test_rc` was initialised before `try`, removing the `UnboundLocalError`; its temporary broad
   `except BaseException: pass` was rejected and then removed in the third pass.

### Second corrective pass verification

- `uv run --project backend --locked pytest …/test_check_mysql_script.py -v --no-cov -o addopts=''`:
  exit 0, **5/5 passed** (success+cleanup, failure+cleanup, readiness+cleanup, success+cleanup-fail, readiness+cleanup-fail).
- `uv run --project backend --locked python scripts/check_mysql.py --container`:
  exit 0, **3/3 passed**, container stopped.
- Reversed-order (CRUD → position → migration) on fresh MySQL:
  exit 0, **3/3 passed**.
- Counterfactual: restoring `drop_index` in migration 0001 triggers `test_migrations_render_mysql_specific_ddl`
  failure with `assert "DROP INDEX" not in downgrade_ddl`.
- Changed-file Ruff format/lint/mypy: clean.
- `make acceptance-stage-2`: exit 0.
- `git diff --check`: clean.

### Third corrective pass (DS-MYSQL-01 final)

**`except BaseException: pass` removed.** Control flow: `test_rc = 1` → `try: readiness + tests` →
`finally: cleanup` → `return test_rc`. Readiness `TimeoutError`/`KeyboardInterrupt` propagate after
cleanup.

Codex final-review evidence on 2026-08-09:

- full focused file plus DDL assertion: exit 0, **7/7 passed**;
- the readiness-plus-cleanup-failure test alone: exit 1 with
  `KeyError: 'check_mysql_script'`, proving test-order dependence;
- project-standard `make backend-static`: exit 0;
- changed-script Ruff format/lint and mypy with `backend/pyproject.toml`: exit 0;
- unique MySQL command on port 19306: exit 0, **3/3 passed**, container stopped;
- `git diff --check`: exit 0.

The production-script blocker from the second review is resolved: `TimeoutError` and
`KeyboardInterrupt` propagate after cleanup. Codex then removed the final unit-test order
dependency by patching the shared `sys.stderr` directly instead of looking up an import created by
an earlier test.

Final acceptance evidence on 2026-08-09:

- isolated readiness-plus-cleanup-failure node ID: exit 0, **1/1 passed**;
- all script tests in reverse node-ID order plus the MySQL DDL assertion: exit 0,
  **7/7 passed**;
- project-standard `make backend-static`: exit 0;
- changed-script Ruff format/lint and mypy with `backend/pyproject.toml`: exit 0;
- exact unique MySQL command without extra arguments: exit 0, **3/3 passed**, no skip/xfail,
  container stopped;
- `git diff --check`: exit 0.

DS-MYSQL-01 is accepted. Overall 3D remains partial pending the separately planned image-digest
pin and cumulative Stage 3/CI gate.

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

## Earlier architecture-document verification

These statements refer only to the committed architecture-document step at `949e304`, before
DeepSeek began DS-MYSQL-01: no application command was rerun for that docs-only commit, while
`git diff --check`, trailing-whitespace scan, and changed-file/status review passed. Current code
review evidence is listed in the DS-MYSQL-01 record above.
