# Stage 2/3 independent acceptance audit

- Audit date: 2026-08-09
- Baseline: `main` at `a85eb03`
- Scope: all `feat(dpsk)` commits through `a85eb03`, their surrounding implementation,
  tests, migrations, generated contracts, CI wiring, and the Stage 2/3 requirements in
  `docs/development-plan.md`
- Auditor: Codex

## Executive verdict

The repository's declared `make acceptance` command exits successfully, but Stage 2 and
Stage 3 do **not** meet their documented completion criteria.

- Stage 2A and the core position-graph kernel are accepted.
- Stage 2B's SQLite graph storage is accepted on the tested paths.
- Stage 2C is partial: Course/Module/Occurrence HTTP paths work, but the promised
  Source/SourceVersion/SourceFile/SourceSpan/KnowledgeNote HTTP CRUD surface is absent.
- Stage 2D is partial: the two fields exist, but the accepted dual-course semantics and
  source-note reference invariants are not implemented.
- Stage 3A is a useful basic parser, but it is not a lossless or bounded semantic parser.
- Stage 3B, 3C, and 3D are not accepted: product API, idempotency, atomic error reporting,
  resource limits, complete round-trip behavior, and real MySQL migration parity are missing
  or broken.

Stage 4 should not start on the assumption that Stage 3 is complete. The PGN variation to
course mapping must be decided first, then the missing behavior should be implemented as
bounded tasks and independently re-audited.

## Verification performed

### Repository-declared gate

`make acceptance` was run using the repository-pinned Node 22/pnpm 10.14.0 and Python
environment. It exited `0`:

- backend: 166 passed, 3 MySQL tests skipped, 2 SQLAlchemy connection-cleanup warnings;
- frontend: 5 passed; lint, formatting, type checking, and production build passed;
- SQLite Alembic upgrade/check/downgrade passed;
- OpenAPI/TypeScript contract drift check passed;
- direct Sanic and Vite-proxy smoke checks passed;
- reported backend line coverage: 86.72%;
- reported backend branch coverage: **57.34%**.

This proves the current gate is green. It does not prove the documented feature set because
the global branch floor was reduced from 75% to 45%, several focused gates were reduced below
90%, and the Stage 3 aggregate target omits required dependencies.

### Adversarial checks added during the audit

No production code was changed. Read-only or disposable checks covered:

- runtime OpenAPI path enumeration and direct requests to missing resource paths;
- importing the same PGN twice and counting persisted entities;
- semantic round-trip of all 12 committed PGN fixtures;
- deliberately changed custom headers, FEN/SAN/UCI, and multiple NAG values;
- legal long PGN parsing/export and multi-module course export;
- actual MySQL 8.4 Alembic upgrade/check/downgrade in a disposable container;
- the repository's local MySQL helper against a disposable container;
- direct database counterexamples for course mode and occurrence invariants.

The disposable MySQL containers were stopped after the checks.

## Acceptance matrix

| Unit | Command/test status | Functional verdict | Reason |
|---|---|---|---|
| 2A | Green; 37 tests; position identity 100% | Accepted | Position identity, legal move validation, FEN vectors, and driver decision behave as specified |
| 2B | Green on SQLite | Accepted with later MySQL caveat | Core Position/MoveEdge storage and SQLite migration paths work |
| 2C | Green command | Not accepted | Source/Span/Note CRUD API and OpenAPI contracts are absent |
| 2D | Green command | Not accepted | Fields exist, but dual-mode and source-note invariants do not match ADR 0005 |
| Stage 2 aggregate | Exit 0 | Not accepted | Gate omits promised APIs and passes at 57.34% branch coverage despite a 75% requirement |
| 3A | 61 tests pass | Partial | Basic fixtures parse, but full FEN, multiple NAGs, variation-leading comments, and bounded parsing are not preserved |
| 3B | 9 existing tests pass | Not accepted | No API, Source, idempotency, import transaction/error contract, or size/node/time limits |
| 3C | 10 existing tests pass | Not accepted | Full fixture round-trip fails and comparator produces false positives; export scope/safety is incomplete |
| 3D | 3 existing assertions pass on MySQL | Not accepted | Tests do not run Alembic; real MySQL downgrade fails |
| Stage 3 aggregate | Miswired | Not accepted | Aggregate explicitly depends only on 3A, misses focused 3B/3C gates and 3D, and uses sub-90% critical thresholds |

## Blocking findings

### A-01: Required Stage 2 and Stage 3 HTTP APIs are absent

`backend/src/chess_workbench/api/app.py` registers only health, graph, and content blueprints.
The content blueprint ends after Course, CourseModule, and Occurrence routes. Runtime OpenAPI
contains 13 paths and contains none for:

- Source, SourceVersion, SourceFile, or SourceSpan;
- KnowledgeNote;
- PGN text import, multipart upload, export, or download.

Direct requests to the expected Source/Note collections return 404. Service-layer methods
exist for several Stage 2 resources, but the architecture requires authoritative use through
the backend HTTP API. Contract drift passes only because generated contracts faithfully mirror
the incomplete route set.

Evidence:

- `backend/src/chess_workbench/api/app.py:58`
- `backend/src/chess_workbench/api/content.py:57`
- `backend/src/chess_workbench/api/content.py:286`
- `docs/development-plan.md:83`
- `docs/development-plan.md:132`
- `docs/development-plan.md:166`
- `docs/development-plan.md:184`

### A-02: PGN import is not idempotent and creates no Source

`PgnImporter.import_game()` unconditionally creates a new traditional Course, Module, root,
and occurrence tree. There is no input hash/import key and no Source lookup or creation.

Importing fixture `01_mainline.pgn` twice into one temporary SQLite database produced:

```text
                         after first   after second
Course                        1             2
CourseModule                  1             2
CourseOccurrence             17            34
Position                     17            17
Source                        0             0
```

Only global Position deduplication works. The existing test named
`test_same_pgn_imported_twice_shares_positions` asserts only the Position count and therefore
does not test import idempotency.

Evidence:

- `backend/src/chess_workbench/logic/pgn_import.py:38`
- `backend/src/chess_workbench/logic/pgn_import.py:48`
- `backend/tests/test_pgn_import.py:118`
- `docs/development-plan.md:179`

### A-03: Real MySQL Alembic downgrade fails

Against a disposable `mysql:8.4` instance:

```text
alembic upgrade head    PASS
alembic check           PASS
alembic downgrade base  FAIL
```

MySQL reports error 1553: it cannot drop index
`ix_source_spans_source_version_id` because the foreign key still needs it. Migration 0002
drops that index immediately before dropping the table.

The test named `test_mysql_migration_round_trip` does not run Alembic; it calls
`Base.metadata.drop_all()` and `create_all()`, so it cannot detect this failure.

Evidence:

- `backend/migrations/versions/20260806_0002_content_context.py:366`
- `backend/tests/test_mysql_compat.py:25`

### A-04: PGN variation mapping contradicts the accepted course model

ADR 0005 defines a traditional module as a linear occurrence chain and reserves branching for
opening explorer. The importer always creates `mode="traditional"` but imports arbitrary nested
PGN variations as branches in that module. The architecture overview simultaneously says this
mapping is not yet frozen.

This is a design blocker rather than a local bug. Before implementation resumes, choose and
record one semantic rule, for example:

1. permit a tree inside a traditional `MoveSequence` and amend ADR 0005;
2. split variations into separate linear sequences/modules while retaining PGN relationships;
3. import branching PGNs into a distinct representation/mode.

Evidence:

- `docs/decisions/0005-dual-course-mode.md:31`
- `docs/architecture/overview.md:80`
- `backend/src/chess_workbench/logic/pgn_import.py:48`
- `backend/src/chess_workbench/logic/pgn_import.py:79`

## High-severity findings

### A-05: Round-trip loses valid PGN semantics and the comparator masks loss

Observed behavior:

- Full import/export/compare over all 12 fixtures fails for `05_braces_comment` and
  `07_unicode_comment` because root comments are not exported.
- Every non-empty export omits the movetext termination marker (`1-0`, `0-1`, `1/2-1/2`, or
  `*`).
- A node stores only one integer NAG; `1.e4 $1 $3` silently becomes only `$1`.
- Variation-leading `starting_comment` is ignored.
- Node FEN uses python-chess's default legal-EP rendering instead of ADR 0002's full-FEN
  rendering. After `1.e4`, the stored semantic node has `-` rather than raw `e3`; a SetUp/FEN
  with a valid but currently uncapturable EP target is normalized the same way.
- Custom headers such as ECO and Annotator are lost on export.
- Import does not persist sibling `sort_order`; every variation sibling defaults to zero, so
  source order depends on created timestamps/UUID fallback rather than an explicit invariant.
- The comparator checks only nine whitelisted headers, does not compare FEN, SAN, or ply, and
  ignores a UCI difference when either side is `None`.

Counterexamples changing ECO, SAN/FEN, or one-sided UCI all returned
`equivalent=True, differences=[]`. The current tests perform semantic comparison on only six
fixtures; the all-fixture test checks only that exported text can be parsed.

Evidence:

- `backend/src/chess_workbench/logic/pgn.py:21`
- `backend/src/chess_workbench/logic/pgn.py:157`
- `backend/src/chess_workbench/logic/pgn.py:190`
- `backend/src/chess_workbench/logic/pgn.py:106`
- `backend/src/chess_workbench/logic/pgn.py:164`
- `backend/src/chess_workbench/logic/pgn_import.py:97`
- `backend/src/chess_workbench/logic/pgn_export.py:44`
- `backend/src/chess_workbench/logic/pgn_export.py:59`
- `backend/src/chess_workbench/logic/pgn_compare.py:21`
- `backend/src/chess_workbench/logic/pgn_compare.py:76`
- `backend/tests/test_pgn_export.py:118`

### A-06: Import is not bounded or self-contained as an atomic operation

The parser builds the entire recursive tree before the importer's only check,
`MAX_DEPTH=500`. There is no 5 MiB input limit, 50,000-node limit, timeout, memory budget,
preflight validation, or 413/422 API response. A generated legal repeated-knight mainline parses
at 400 ply but raises bare `RecursionError` at 500 ply; it never reaches the advertised importer
limit.

The importer owns no transaction boundary and adds no ply/path context to service errors. The
only illegal-import test calls the parser before any import and neither exercises a late failure
nor counts rows after rollback.

Evidence:

- `backend/src/chess_workbench/logic/pgn.py:128`
- `backend/src/chess_workbench/logic/pgn.py:175`
- `backend/src/chess_workbench/logic/pgn_import.py:31`
- `backend/src/chess_workbench/logic/pgn_import.py:90`
- `backend/tests/test_pgn_import.py:153`
- `docs/development-plan.md:181`
- `docs/development-plan.md:183`
- `docs/development-plan.md:543`

### A-07: Export is not a course-path export and has no traversal safety

Export requires exactly one root for the entire Course. A valid traditional course with two
rooted modules raises `ValueError: expected 1 root, found 2`; there is no module/path selector.
A legal 1050-ply service-created path raises bare `RecursionError`. There is no depth/node bound
or visited set.

For a custom FEN with Black to move on move 17, export numbers the first move as `1.` rather than
`17...`. Original PGN headers are stored as JSON in `Course.description`, which consumes a
user-facing semantic field and still does not restore custom headers.

Evidence:

- `backend/src/chess_workbench/logic/pgn_import.py:49`
- `backend/src/chess_workbench/logic/pgn_export.py:11`
- `backend/src/chess_workbench/logic/pgn_export.py:19`
- `backend/src/chess_workbench/logic/pgn_export.py:65`
- `backend/src/chess_workbench/logic/pgn_export.py:109`

### A-08: Stage 2D fields do not enforce ADR 0005 semantics

The Explorer reference-card example in ADR 0005 allows `markdown=null` and says content should
not be duplicated. Current schema requires non-empty Markdown, and the database column is NOT
NULL with a non-empty check. `source_note_id` is stored as a bare self-FK without verifying that:

- the source note exists and is active;
- the source note belongs to a traditional course;
- the target note belongs to an opening-explorer course.

The source-link test creates both courses with the default traditional mode and supplies copied
Markdown, so it does not exercise the intended relation.

`Course.mode` also has no database CHECK. Direct SQLite insertion accepts `not-a-mode`, and the
service does not enforce traditional linearity. A traditional root can have multiple children.

Evidence:

- `docs/decisions/0005-dual-course-mode.md:77`
- `backend/src/chess_workbench/schemas/domain.py:481`
- `backend/src/chess_workbench/store/models/content.py:61`
- `backend/src/chess_workbench/store/models/content.py:261`
- `backend/src/chess_workbench/services/content.py:608`
- `backend/tests/test_note_source_link.py:19`

### A-09: Lifecycle operations can break occurrence/module invariants

Public service operations can archive root A, create root B, and then restore A, leaving two
active roots in a module. A single occurrence can also be PATCHed to a different `module_id`
without moving or validating its parent/children, creating a cross-module path.

These are integrity gaps in the Stage 2 lifecycle contract and should receive negative tests
before the editor relies on them.

Evidence:

- `backend/src/chess_workbench/services/content.py:231`
- `backend/src/chess_workbench/services/content.py:354`
- `backend/src/chess_workbench/store/content_repository.py:149`

### A-10: Acceptance gates are weaker or differently wired than documented

- `scripts/check_backend_coverage.py` enforces 45% global branch coverage, not 75%; current
  measured branch coverage is 57.34%.
- Stage 2A/2B/2C use 85% focused coverage and 2D uses 89%, not the promised 90%.
- Stage 3A/3B/3C use 85%, while PGN round-trip is explicitly a critical 90% rule.
- Stage 2C selects only the first matching content test file, so it omits
  `test_content_service.py` from its focused gate.
- Stage 3B and 3C each depend directly on Stage 2D rather than their previous Stage 3 unit.
- `acceptance-stage-3` explicitly depends only on 3A; full `verify` still runs the ordinary
  3B/3C tests, but not their focused coverage gates, and the aggregate does not run 3D.
- `acceptance` still aliases Stage 2.
- `acceptance-stage-3d` exits successfully when MySQL is not configured.
- `scripts/check_mysql.py --container` runs the three tests successfully but then exits 1 because
  it does not disable the global 80% coverage addopts; observed suite coverage was about 39%.
- MySQL CI and the local helper use mutable `mysql:8.4` tags, not the required digest.

Evidence:

- `Makefile:8`
- `Makefile:99`
- `Makefile:128`
- `Makefile:137`
- `Makefile:144`
- `scripts/check_backend_coverage.py:8`
- `scripts/check_mysql.py:84`
- `.github/workflows/ci.yml:15`
- `docs/development-plan.md:37`
- `docs/development-plan.md:127`
- `docs/development-plan.md:551`

### A-11: A page/bbox SourceSpan can omit the file it locates

ADR 0004 requires file coordinates to identify the related `SourceFile`. The current schema
accepts a page locator with a bounding box while `source_file_id=None`; the service checks file
ownership only when the caller supplies an ID. This leaves a citation coordinate that cannot be
resolved to an immutable source file.

Evidence:

- `docs/decisions/0004-course-context-and-lifecycle.md:33`
- `backend/src/chess_workbench/schemas/domain.py:373`
- `backend/src/chess_workbench/services/content.py:536`

## Test-fixture credibility gaps

- `09_promotion.pgn` contains no promotion.
- `12_transposition.pgn` contains one line and shares no non-root position with
  `01_mainline.pgn`; the test eventually asserts only `pos_count > 0`.
- Variation import asserts only `occurrence_count >= 2`.
- The NAG/comment import test uses a fixture without comments and asserts only that some NAG
  exists.
- The illegal import test does not call the importer or verify rollback.
- The parser accepts an unterminated brace comment despite its public contract saying malformed
  PGN raises `ValueError`.
- The all-fixture export sweep checks parseability rather than equivalence.
- The MySQL suite checks metadata create/drop, one Course service round-trip, and two sequential
  calls to `get_or_create_position`; it does not exercise Alembic, the HTTP API, PGN, JSON,
  booleans, UTC, ordering, or a real concurrent uniqueness conflict.
- `test_import_rejects_illegal_pgn` does not close its temporary Database; the full suite reports
  two SQLAlchemy warnings when garbage collection terminates unchecked-in aiosqlite connections.

## Additional documentation drift

- `AGENTS.md` and README still describe Stage 2 as current while PLANS/HANDOFF declared Stage 3
  complete.
- `docs/architecture/overview.md` says PGN variation mapping is not frozen although the Stage 3
  plan says it is delivered.
- ADR 0006 is `Proposed`, but the architecture overview describes it as already defined; the old
  HANDOFF simultaneously said the block format was not defined.
- The project description retains older model/driver statements that conflict with accepted ADRs
  (including PyMySQL and global MoveEdge annotation fields).

Documentation should be reconciled only after the blocking semantics are decided; it must not be
used to paper over missing behavior.

## Confirmed working foundations

The audit is not a rejection of all DeepSeek work. These foundations are useful and should be
preserved:

- versioned canonical position identity and separate full state in the Stage 2 domain kernel;
- legal UCI validation through python-chess before persisted moves;
- global Position/MoveEdge sharing with occurrence-local context;
- optimistic versions and explicit archival on the tested paths;
- SQLite migrations and contract generation determinism;
- the basic PGN parser for ordinary mainlines, committed nested variations, Unicode comments,
  one NAG, SetUp/FEN, and illegal SAN;
- basic occurrence import through `ContentService` and global Position reuse;
- basic PGN rendering for the tested happy paths;
- locked `asyncmy 0.2.11` and a working real MySQL connection;
- static checks, frontend build/tests, and health smoke path.

## Required remediation order and agent split

1. **Codex/design:** resolve PGN variation mapping, import identity/Source ownership, exact API
   transaction boundary, and lossless PGN semantic scope. Record accepted decisions in ADRs.
2. **DeepSeek/bounded implementation:** repair the MySQL downgrade and replace the false migration
   test with actual Alembic upgrade/check/downgrade; fix local helper and Make/CI dependency wiring.
3. **DeepSeek/bounded implementation:** add the missing Stage 2 Source/Span/Note routes and contract
   tests against the already-present service layer, including 2D cross-mode invariants specified
   by Codex.
4. **DeepSeek after API design:** implement PGN import/export endpoints, idempotency and Source
   records, whole-operation rollback, typed ply/path errors, and preflight limits.
5. **DeepSeek/bounded tests:** replace misleading fixtures and add negative comparator tests plus
   all-12 semantic round-trip tests.
6. **Codex/review:** independently run SQLite and MySQL migrations, all focused gates, adversarial
   PGN cases, contracts, and smoke. Only then restore Stage 2/3 completion labels.

Stage 4 implementation remains paused until steps 1–4 establish a stable backend contract.
