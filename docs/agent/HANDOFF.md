# Agent handoff

## Goal

Stage 8A is accepted. Stage 8B is active under ADR 0013: evidence ports, PDFium rendering,
PaddleOCR JSON adaptation and the immutable artifact/`pdf_extraction` handler are accepted. The
next Codex task is the 8B-5 committed-evidence API/UI summary and focused Stage 8B acceptance.

## Working state

- Branch: `main`; accepted committed baseline:
  `2398bcb feat(codex): stage 8p-2 & implement interface between codex and dpsk`.
- Worktree was clean before the current documentation design changes.
- Stage 6 and Stage 8A are accepted. Stage 5/6E and Stage 7 remain deferred.
- ADR 0010 defines the accepted CCEF v1 architecture; `docs/architecture/ccef-v1.md` freezes its
  exact field-level contract. It clarifies ADR 0006: the portable extraction package is mapped to
  internal Blocks only by a downstream ChessWorkbench ConsumerAdapter.
- 8P-1 CCEF v1 portable contract is accepted after Codex final review: 43 focused tests and all
  configured static gates pass; runtime UTC handling and the checked-in Schema pattern agree.
- 8P-2 provider port is accepted after Codex final review: 70 focused tests plus configured static
  gates pass; runtime errors/outcomes/call snapshots and caller-owned Schema presence are enforced.
- 8P-3 official V4 Flash adapter is accepted after Codex security review: 108 focused tests and
  configured static gates pass; no live/paid request was made.
- 8P-4A decoder (`DS-STAGE8-CCEF-DECODER-01`) is accepted after Codex review (2026-08-11):
  truncation precedence, invalid-json/invalid-package/untrusted-validation boundaries and
  exception-chaining hygiene verified; 131 focused tests passed.
- 8P-4B chess normalizer (`DS-STAGE8-CHESS-NORMALIZER-01`) is accepted after Codex review
  (2026-08-11): branch reconstruction, ambiguous/invalid retention, input immutability and
  idempotency verified; 143 focused tests passed across 8P-1/4A/4B.
- 8P-5 consumer proof is accepted after Codex review: the standalone `python -I` reader, synthetic
  package/golden projection and design-only ChessWorkbench mapping plan are complete. Codex added
  an offline-safety gate rejecting external JSON Schema references before validator construction;
  173 focused tests pass across 8P-1/4A/4B/5.
- Final 8P feature-boundary review is accepted after cross-layer corrections to lazy import
  isolation, Schema extension/discriminator parity, normalized provider finish reasons, recursive
  JSON rejection and standalone consumer defaults/non-standard-number handling. The complete 8P
  focused suite passes 294 tests; configured Ruff and MyPy gates are clean.
- ADR 0012 is accepted. It fixes PDF bytes identity, 1-based inclusive physical page ranges,
  256 MiB default limit, raw/derived CAS separation, immutable extraction receipts, Job as the
  single running status and handler-scoped worker claiming.
- 8A-1 is accepted after Codex corrected exception-context leakage, descriptor cleanup and
  large-file verification memory use. Its focused CAS/PGN suite passes 39 tests.
- 8A-2A is accepted: BSD-3-Clause pypdf 6.15.0, bounded in-memory inspection, seven fixed failure
  reasons and 63 focused tests. PyMuPDF was deliberately not added because its AGPL/commercial
  license would constrain the user's planned reuse on other websites.
- 8A-2B is accepted after Codex review: three immutable ORM records, additive revision
  `20260811_0010`, SQLite/MySQL-portable constraints and real-MySQL acceptance wiring. The focused
  model/migration suite passes 18 tests with 4 MySQL-only skips; Ruff and MyPy are clean.
- 8A-2C1 is accepted after Codex review: inspection precedes metadata validation and CAS, mapped
  failures leak no parser/path context, repeat bytes reuse one 0600 blob, and 121 focused tests pass.
- 8A-2C2 is accepted after Codex review: exact PDF Source-chain replay, physical page validation,
  finite profile fingerprints, explicit/no-key idempotency, deterministic run IDs and atomic
  run/Job/invalidation rollback are covered by 50 service/integration tests. Together with the
  seven model tests the final focused gate is 57 passed; configured strict MyPy and Ruff are clean.
- 8A-3A schemas are accepted after Codex review: 46 delegated/independently rerun tests pass;
  generic JobRead keeps identity-equal engine compatibility without narrowing the module export
  surface. Codex added `PdfAssetList` because reload-safe Sources UI cannot rediscover an uploaded
  asset that has no run through the originally frozen single-item endpoint alone.
- Codex implemented the 8A-3B route/query/worker core. `claim` and expired-lease recovery now both
  require registered kinds; the 14-test Stage 6 job gate proves an engine worker cannot touch a
  PDF job. API/config/service static checks are clean. API black-box verification remains active.

## Frozen architecture

```text
Source/OCR fragments
    -> StructuredGenerationProvider (DeepSeek first; replaceable)
    -> CCEF decoder/assembler (portable JSON)
    -> deterministic structure/reference/chess validation
    -> ConsumerAdapter (ChessWorkbench or another website)
```

- CCEF v1 identifier: `chess-content-extraction/1.0`.
- CCEF contains portable content, evidence and diagnostics; it contains no Course, Module,
  Occurrence, KnowledgeNote, SQL ID, approval state or provider-private response fields.
- The extraction core never imports Sanic, SQLAlchemy, store or ChessWorkbench domain schemas.
- Provider accepts a caller-supplied JSON Schema. It does not hardcode a downstream website.
- ChessWorkbench mapping is one-way and leaves the original CCEF package immutable.
- AI confidence cannot mark a move valid. Later python-chess validation is authoritative.
- Unknown content is retained as `unresolved`; it is never silently dropped.

## Current agent instruction

The active V4-Flash packet is `DS-STAGE8A-SOURCES-PDF-UI-01` in `PLANS.md`. Modify only the existing
Sources page and its existing focused page test, then append evidence here. Backend, generated
contracts, API client/type helpers and all other frontend files are read-only.

## Required completion report for the next packet

Report:

1. exact files changed;
2. behavior and validators implemented;
3. exact focused test count and every acceptance command result;
4. confirmation that the packet's named invariants remain intact;
5. assumptions and any interface ambiguity;
6. `git diff --stat` and `git diff --check` result;
7. status `pending Codex review` and confirmation that no later packet was started.

Do not commit, rebase, reset, install dependencies, weaken checks or expand the permitted boundary.

## Next route

After Codex accepts the Sources UI packet, add the cumulative `acceptance-stage-8a` target and run
the focused 8A closeout once. Do not start OCR/rendering or a live provider call before 8A closes.

## DS-STAGE8-PORTABLE-CONTRACT-01 completion

### 1. Files changed

- `backend/src/chess_workbench/extraction/__init__.py` (new, 60 lines) — public package exports.
- `backend/src/chess_workbench/extraction/contracts.py` (new, 458 lines) — strict CCEF v1 models,
  package-level validators and deterministic JSON Schema generation.
- `backend/tests/test_extraction_contract.py` (new, 482 lines) — 30 focused contract tests.
- `contracts/chess-content-extraction-v1.schema.json` (new, 13,500 bytes) — Draft 2020-12 artifact.
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched.

### 2. Behavior and validators

- `_StrictModel` base: `extra="forbid"` + `strict=True` at every object boundary (17 objects in
  schema carry `additionalProperties: false`).
- `ExtractionPackage`: literal version `chess-content-extraction/1.0`, UUID package id, opaque
  `source_ref`, ordered discriminated `items`, diagnostics, provenance, namespaced extensions.
- `EvidenceRef`: one-based page, normalized positive-area bbox, paired half-open offsets,
  lowercase SHA-256 (regex-constrained).
- Items: `heading`, `prose` (no/move-node/position anchor), `move_sequence`, `figure`,
  `unresolved` (requires raw_text or details). Common: unique local ID, non-empty evidence,
  optional confidence, warnings, extensions.
- `MoveNode`: flat, topological parent-before-child enforced, contiguous unique zero-based
  `sibling_order` per parent (including null root), NAG uniqueness, `valid` requires all four
  normalization fields / `unvalidated` forbids them. No chess-legality logic.
- Package validator rejects: duplicate item/node IDs, dangling prose anchors, dangling/forward
  parents, duplicate/gap sibling orders, evidence outside declared `page_range`, dangling
  diagnostic item/node refs.
- `ccef_schema_document()` / `ccef_schema_canonical_json()` produce the canonical bytes per
  ccef-v1.md (`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"`).

### 3. Focused test count and acceptance commands

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py        → 30 passed
make backend-format backend-lint backend-typecheck → all clean (89 source files)
git diff --check                                   → clean
git diff --stat                                    → only the pre-existing documentation edits
                                                    (packet files are new/untracked: 1000 lines +
                                                    13,500-byte schema artifact)
```

### 4. JSON Schema drift gated

`test_json_schema_artifact_is_byte_for_byte_deterministic` compares
`ccef_schema_canonical_json()` with the checked-in artifact byte-for-byte and asserts regeneration
stability.

### 5. Assumptions and ADR ambiguity

- `strict=True` applies globally; `package_id` (UUID) and `created_at` (datetime) use per-field
  `strict=False` because JSON represents them as strings. bbox/confidence use `strict=False`
  so integer-valued JSON numbers (`1`, `[0,0,1,1]`) match the `type: number` schema artifact.
- `figure.position_fen_candidate` is length-limited only (no six-field check), per ccef-v1.md;
  only `PositionAnchor.fen` and `FenPosition.fen` require six fields.
- No chess legality, python-chess, HTTP, SQL or provider code in this packet.

### 6. `git diff --stat` / `git diff --check`

Clean. New packet files are untracked; existing working-tree documentation edits are untouched.

### 7. Status

**Codex review: changes requested.** Do not proceed to 8P-2. The active next instruction is the
bounded V4-Flash correction packet `DS-STAGE8-PORTABLE-CONTRACT-01-R1` in `PLANS.md`.

## Codex review of DS-STAGE8-PORTABLE-CONTRACT-01 (2026-08-11)

Independent gates:

- focused contract suite: `30 passed`;
- configured repository Ruff lint: passed;
- repository MyPy gate: passed (`89 source files`);
- Schema dialect/ID, confidence number shape, provenance date-time shape and reverse-domain
  extension-key pattern: present as designed.

Adversarial cases missing from the submitted tests expose four blockers: a minimal self-parent
move node is accepted; confidence coerces JSON strings/booleans; provenance coerces numeric
timestamps/numeric strings; and nested non-finite extension numbers are accepted and serialize
lossily. The bbox container also accepts tuples despite the declared strict boundary. Exact fixes,
test oracles, edit limits and commands are recorded in `PLANS.md` under
`DS-STAGE8-PORTABLE-CONTRACT-01-R1`.

## DS-STAGE8-PORTABLE-CONTRACT-01-R1 completion

### Corrections applied (per PLANS.md R1)

1. **Self-parent rejected**: `_check_move_tree` now checks a non-null `parent_id` against the
   seen set BEFORE adding the current node id. New `test_rejects_self_parent` (single-node
   self-parent sequence) plus the retained dangling/forward-parent tests.
2. **Strict scalars**: removed `strict=False` from `Confidence` and the bbox container. Strict
   floats still accept integer-valued JSON numbers; `"0.5"`/`true` rejected for confidence; tuple
   container, numeric strings and booleans rejected for bbox. Tests:
   `test_confidence_accepts_numbers_and_rejects_strings_and_booleans`,
   `test_bbox_accepts_integer_numbers_and_rejects_tuple_strings_booleans`.
3. **Round-trip-safe UUID/date-time**: `package_id` and `created_at` keep strict types plus
   `mode="before"` validators that whitelist only UUID instance/string and datetime
   instance/ISO-RFC3339 string (converting the string to an instance so `model_dump(mode="json")`
   round trips). Ints, numeric strings, date-only strings, booleans and bytes rejected.
4. **Finite extensions**: `FiniteJsonValue = Annotated[JsonValue, AfterValidator(...)]` recursively
   rejects `NaN`/`Infinity`/`-Infinity` in package/item/node `extensions`; ordinary nested JSON
   scalars/arrays/objects still work.
5. **Schema artifact**: the corrected models produce identical canonical JSON; the
   byte-for-byte drift test still passes and the artifact was not regenerated.

### New focused test count and gates

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py        → 37 passed (30 original + 7 new R1)
make backend-format backend-lint backend-typecheck → all clean (89 source files)
git diff --check                                   → clean
git diff --stat                                    → only the pre-existing documentation edits
                                                    (packet files are new/untracked)
```

New tests: `test_rejects_self_parent`, `test_confidence_accepts_numbers_and_rejects_strings_and_booleans`,
`test_bbox_accepts_integer_numbers_and_rejects_tuple_strings_booleans`,
`test_created_at_accepts_datetime_and_iso_string_only`,
`test_package_id_accepts_uuid_instance_and_string_only`,
`test_extensions_reject_nested_non_finite_numbers`,
`test_extensions_accept_ordinary_nested_json_values`.

### Assumptions

- Strict datetime (base `strict=True`) rejects date-only/int/bool inputs; the numeric string
  `"0"` leak is closed by the RFC3339-pattern before-validator that also converts to a
  `datetime` instance (strict dict validation rejects str otherwise).
- `json.loads("NaN")` still parses non-finite floats, so the `FiniteJsonValue` AfterValidator is
  the enforcement point for nested extension values.
- No chess legality, provider/HTTP/SQL code, dependency, or public field changes.

### Status

**Pending Codex re-review.** 8P-1 is NOT complete; do not proceed to 8P-2.

## Codex R1 re-review (2026-08-11)

The R1 implementation closes all four original blockers under independent adversarial replay:
self-parent, lax confidence/bbox conversion, lax UUID/date-time input types, and nested non-finite
extension numbers are all rejected. The focused suite passes `37/37`; configured backend format,
Ruff lint and MyPy gates also pass.

One narrow date-time portability issue remains before freezing CCEF v1. The runtime parser accepts
surrounding whitespace and RFC3339 `-00:00`, rejects valid lowercase `t`/`z`, and the generated
Schema does not express the normative UTC-only restriction. `PLANS.md` now contains the bounded
`DS-STAGE8-PORTABLE-CONTRACT-01-R2` correction packet with exact accepted/rejected forms, Schema
oracle, edit boundary and commands. Do not proceed to 8P-2 yet.

## DS-STAGE8-PORTABLE-CONTRACT-01-R2 completion

### Corrections applied (per PLANS.md R2 — `Provenance.created_at` only)

1. **Regex**: `_DATETIME_STRING` is now the single maintained pattern source:
   `^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:[0-9]+)?(?:Z|z|+00:00)$`
   (optional fractional seconds; explicit UTC designator `Z`/`z`/`+00:00`; `T` or `t`
   separator).
2. **Runtime**: the before-validator no longer calls `.strip()` — the anchored pattern rejects
   surrounding whitespace directly. `z`/`Z` are normalized to `+00:00` before
   `datetime.fromisoformat`. `-00:00` and every non-zero offset fail the pattern; missing
   timezone and date-only/numeric strings remain rejected.
3. **Schema**: `ccef_schema_document()` injects the same `_DATETIME_STRING.pattern` into
   `$defs.Provenance.properties.created_at` while keeping `format: date-time`, so
   schema-only consumers now see the UTC restriction. The checked-in
   `contracts/chess-content-extraction-v1.schema.json` was regenerated and the byte-for-byte
   drift test still passes.
4. **No other fields, validators, dependencies or public shapes changed.**

### New focused tests (6 added → 43 total)

- `test_created_at_accepts_all_utc_designator_spellings` (Z/z/+00:00 × T/t × fractional seconds)
- `test_created_at_rejects_surrounding_whitespace`
- `test_created_at_rejects_unknown_local_offset` (`-00:00`)
- `test_created_at_rejects_non_zero_offsets` (`+02:00`, `-05:30`)
- `test_created_at_rejects_missing_timezone`
- `test_schema_created_at_carries_utc_pattern_and_format` (asserts the generated Schema carries
  both the UTC pattern and `format: date-time`, and that the pattern rejects `-00:00`/`+02:00`/
  whitespace)

### Acceptance commands

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py        → 43 passed (37 prior + 6 new R2)
make backend-format backend-lint backend-typecheck → all clean (89 source files)
git diff --check                                   → clean
git diff --stat                                    → only the pre-existing documentation edits
                                                    (packet files are new/untracked)
```

### Status

**Pending Codex final re-review.** 8P-1 is NOT marked complete; do not proceed to 8P-2.

## Codex final review of 8P-1 (2026-08-11)

**Accepted.** Independent verification passed:

- `backend/tests/test_extraction_contract.py`: `43 passed`;
- configured backend formatter check, Ruff lint and MyPy: all clean;
- accepted UTC spellings (`Z`, `z`, `+00:00`, `T`/`t`, fractional seconds) match in runtime and
  the generated Schema pattern;
- whitespace, `-00:00`, non-zero offsets, missing timezone and numeric text are rejected by both;
- the checked-in Schema is byte-for-byte equal to canonical regeneration;
- original R1 adversarial cases remain closed.

8P-1 is complete. The active next task is the bounded provider-port packet
`DS-STAGE8-PROVIDER-PORT-01` in `PLANS.md`; it defines strict provider-neutral request/response/error
types, an async Protocol and a deterministic scripted fake. It explicitly excludes HTTP, model
configuration, credentials, CCEF decoding, SQL and jobs.

## DS-STAGE8-PROVIDER-PORT-01 completion

### Files changed

- `backend/src/chess_workbench/extraction/provider.py` (new) — provider-neutral value objects,
  error, runtime-checkable async Protocol and deterministic scripted fake.
- `backend/src/chess_workbench/extraction/__init__.py` — exports the new public port types.
- `backend/tests/test_extraction_provider.py` (new, 21 tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched (contracts.py, Schema artifact, dependencies, config, jobs, SQL, routes,
services and existing tests untouched).

### Behavior implemented

- `StructuredMessage`: role literal + content non-empty/whitespace-only-rejected, max 2,000,000
  chars, preserved verbatim (no trimming).
- `StructuredGenerationRequest`: non-empty ordered messages with ≥1 user, schema name regex
  `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, `response_schema: dict[str, FiniteJsonValue]` (empty `{}`
  valid, never inspected), required `max_output_tokens >= 1`.
- `TokenUsage`: optional non-negative strict ints; no total==sum assumption.
- `StructuredGenerationResponse`: verbatim non-empty `content`, trimmed `provider`/`model`,
  optional trimmed `finish_reason`, `usage` defaulting to empty object.
- `ProviderErrorCode` literal union; `StructuredGenerationProviderError(RuntimeError)` with
  public `code`/`message`/`retryable`, `str(error) == message`, non-empty message, no raw body
  attribute, and `__deepcopy__` so the scripted fake can snapshot outcomes.
- `StructuredGenerationProvider` runtime-checkable async Protocol with exactly
  `generate(request) -> StructuredGenerationResponse`.
- `ScriptedStructuredGenerationProvider`: ordered finite outcomes; every awaited call records a
  deep request snapshot, consumes exactly one outcome, returns a deep response copy or raises the
  scripted error; `calls` immutable tuple; non-negative `remaining`; exhaustion raises
  `AssertionError`. No sleeps/I/O/parsing/schema behavior.

### Acceptance commands

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_provider.py
    → 64 passed (43 contract + 21 provider)
make backend-format backend-lint backend-typecheck → all clean (91 source files)
git diff --check                                   → clean
git diff --stat                                    → only pre-existing documentation edits
                                                    (packet files are new/untracked)
```

### Assumptions

- provider.py defines its own strict base/finite-JSON helpers rather than importing from
  `contracts.py`, to honor the import-purity requirement (the provider port must not depend on
  CCEF models).
- The import-purity test loads provider.py standalone via `importlib` so the extraction package
  `__init__` (which re-exports contracts) does not pollute `sys.modules`.
- The exhausted call is still recorded in `calls` ("each awaited call records a deep snapshot").
- No HTTP, API key, model config, CCEF decoding, SQL or job code added.

### Status

**Pending Codex review.** 8P-2 is NOT marked complete; do not proceed to the DeepSeek HTTP
adapter (8P-3) and do not commit.

## Codex review of DS-STAGE8-PROVIDER-PORT-01 (2026-08-11)

The focused suite independently passes `64/64`, and configured backend format, Ruff and MyPy gates
are clean. Architecture/import boundaries are intact. 8P-2 nevertheless needs one bounded runtime
enforcement correction: invalid provider-error literals/types are accepted, invalid scripted
outcomes can be returned as successful responses, and callers can mutate the fake's internal call
snapshots through the tuple property. The exact fixes, regression oracles, unchanged interface and
edit boundary are in `PLANS.md` as `DS-STAGE8-PROVIDER-PORT-01-R1`. Do not enter 8P-3 yet.

## DS-STAGE8-PROVIDER-PORT-01-R1 completion

### Corrections applied (per PLANS.md R1 — provider.py + focused tests only)

1. **Error constructor runtime validation** (`StructuredGenerationProviderError`):
   - `code` must be a string and one of the seven `ProviderErrorCode` literals — enforced via
     `_PROVIDER_ERROR_CODES = frozenset(get_args(ProviderErrorCode))` (single maintained source,
     drift-proof). Invalid → `ValueError` naming the accepted codes.
   - `message` must be a string, non-empty after the whitespace-only check → `ValueError`.
   - `retryable` must be an actual `bool` (rejects `0`/`1`/strings/None) → `TypeError`.
   - Public constructor order, fields, `str(error) == message` and `__deepcopy__` preserved.

2. **Scripted outcome validation at construction**: every outcome must be a
   `StructuredGenerationResponse` or `StructuredGenerationProviderError`; otherwise a `TypeError`
   identifies the offending index. Invalid outcomes never reach `generate()`.

3. **`calls` isolation**: the `calls` property now returns fresh deep copies of the internal
   request snapshots on every access, so mutating a previously returned request/message/schema
   cannot change subsequent observations. Original-request isolation and exhaustion-call
   accounting preserved.

### New focused tests (5 added → 26 provider / 69 total)

- `test_error_rejects_invalid_code` (unknown string + non-string)
- `test_error_rejects_non_string_message`
- `test_error_rejects_non_bool_retryable` (`"yes"`, `0`, `1`, `None`)
- `test_scripted_fake_rejects_invalid_outcomes_at_every_position` (index 0 / index 1)
- `test_calls_tuple_mutation_cannot_change_observations`

All original provider tests (Protocol conformance, FIFO, response isolation, error-then-success,
exhaustion accounting, import purity) retained and passing.

### Acceptance commands

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_provider.py
    → 69 passed (43 contract + 26 provider)
make backend-format backend-lint backend-typecheck → all clean (91 source files)
git diff --check                                   → clean
git diff --stat                                    → only pre-existing documentation edits
                                                    (packet files are new/untracked)
```

### Assumptions

- Invalid constructor inputs are rejected with `ValueError` for `code`/`message` and `TypeError`
  for `retryable`, matching the PLANS wording ("clear TypeError or ValueError").
- `calls` deep-copies on every property access (stronger than snapshotting once), which is an
  equivalently strong read-only representation.
- No public fields changed; no dependency added; no HTTP/8P-3 work.

### Status

**Pending Codex re-review.** 8P-2 is NOT marked complete; do not proceed to the DeepSeek HTTP
adapter and do not commit.

## Codex-led DeepCode delegation transition (2026-08-11)

Manual copy/paste between Codex and DeepCode has been replaced by the project-local
`$delegate-deepcode` skill. ADR 0011 records the control model: the user talks only to Codex;
Codex may launch one already-specified `PLANS.md` packet through a PTY-backed DeepCode worker,
wait for its scoped notify result, then independently review the real diff. DeepCode remains a
bounded implementation worker and never approves or commits its own changes.

Implemented infrastructure:

- `.agents/skills/delegate-deepcode/` — workflow skill, PTY launcher and atomic notify receiver;
- `.deepcode/settings.json` — V4 Flash/high plus project-only non-destructive worker permissions
  and the completion notify command;
- `.agent-sync/` — gitignored per-run prompt, Git baseline, terminal transcript and result JSON;
- `docs/decisions/0011-codex-led-deepcode-delegation.md` and `AGENTS.md` — durable architecture and
  escalation rules.

Deterministic fake-worker verification covered completed notification, explicit worker failure,
process exit before notification, exclusive-lock rejection and a 30-second timeout. Both scripts
pass Ruff format/lint, Python compilation and the skill package passes `quick_validate.py`.
No real model call was needed for the transport tests. No commit was created.

## Final Codex review of DS-STAGE8-PROVIDER-PORT-01-R1 (2026-08-11)

**Accepted; 8P-2 complete.** Independent source review and adversarial construction confirm that
R1 rejects unknown/non-string error codes, non-string/empty messages, non-bool retryability and
invalid scripted outcomes, while `calls` returns isolated deep snapshots. Codex additionally made
`StructuredGenerationRequest.response_schema` required instead of silently defaulting a missing
field to `{}`; an explicitly supplied empty Schema remains valid. This enforces the caller-owned
Schema invariant before a real adapter is added.

Focused evidence:

```text
test_extraction_contract.py + test_extraction_provider.py → 70 passed
backend format / Ruff / MyPy                              → clean
git diff --check                                          → clean
```

8P-3 has not started. Its DeepSeek HTTP adapter behavior, sanitized error mapping, mocked transport
and cost/output bounds must be designed by Codex as a new packet before automatic delegation.

## DS-STAGE8-DEEPSEEK-ADAPTER-01 completion

### 1. Files changed

- `backend/src/chess_workbench/extraction/deepseek.py` (new) — DeepSeek V4 Flash transport adapter.
- `backend/src/chess_workbench/extraction/__init__.py` — export only: `from .deepseek import
  DeepSeekV4FlashProvider` plus one `__all__` entry (2 lines added).
- `backend/tests/test_extraction_deepseek.py` (new, 78 focused tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched. The pre-existing worktree edits (delegate skill, `PLANS.md`,
`backend/pyproject.toml` + `backend/uv.lock` httpx dependency, HANDOFF) are preserved untouched.

### 2. Behavior and validators implemented

- `DeepSeekV4FlashProvider` with the exact public constructor
  `(*, api_key, timeout_seconds=600.0, max_output_tokens_limit=128_000, transport=None)`, a static
  `__repr__` that never surfaces the key, and a fresh non-streaming `httpx.AsyncClient` per accepted
  request (single POST, no retry; `transport` is the `httpx.MockTransport` test seam).
- Constructor validation: `api_key` actual non-whitespace string, trimmed before use; `timeout_seconds`
  actual finite int/float (not bool) in `[1, 1800]`; `max_output_tokens_limit` actual int (not bool) in
  `[1, 384_000]`.
- Request mapping: exact payload `{"model": "deepseek-v4-flash", "messages": [adapter system message,
  *caller messages], "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
  "max_tokens": request.max_output_tokens, "stream": false}`; headers
  `Authorization: Bearer <trimmed key>` and `Accept: application/json` (JSON content type via `json=`).
  Exactly one deterministic system message is prepended: the fixed instruction line, `Schema name:`,
  and the canonical Schema JSON (`json.dumps(..., ensure_ascii=False, sort_keys=True,
  separators=(",", ":"))`). Caller messages are appended unchanged, in original order; the request is
  never mutated.
- Output-limit guard before any network I/O: `max_output_tokens > max_output_tokens_limit` raises
  provider error `invalid_request`, non-retryable, fixed sanitized message.
- Success mapping (2xx): requires object body with non-empty `choices` whose first item is an object
  with a `message` object carrying non-whitespace string `content` and `finish_reason` either `null` or
  a non-whitespace string; top-level non-whitespace string `model`; `usage` object with actual
  non-negative int (not bool) `prompt_tokens`/`completion_tokens`/`total_tokens`. Returns
  `StructuredGenerationResponse` with raw content verbatim, `provider="deepseek"`, the returned model,
  finish reason (including `"length"` preserved), and usage mapping `prompt→input`,
  `completion→output`, `total→total`. Provider-private fields are ignored. `{}` content is valid;
  empty/whitespace content, invalid JSON and every malformed/missing/type-invalid required field map to
  `invalid_response`, non-retryable, fixed message `DeepSeek returned an invalid response`. Content is
  never parsed as JSON or schema-validated (8P-4 owns both).
- Error mapping (fixed messages, numeric HTTP status only; no `raise_for_status`, no body/credential
  leakage): `httpx.TimeoutException` and HTTP 408/504 → `timeout`/retryable; other `httpx.TransportError`
  → `unavailable`/retryable; HTTP 401/402/403 → `authentication`/non-retryable; HTTP 429 →
  `rate_limited`/retryable; HTTP 400/404/409/422 and other 4xx → `invalid_request`/non-retryable;
  HTTP 500–599 except 504 → `unavailable`/retryable; other non-2xx → `unknown`/non-retryable.
  `asyncio.CancelledError`, `KeyboardInterrupt` and other `BaseException` values propagate unchanged.

### 3. Focused test count and acceptance commands

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_provider.py backend/tests/test_extraction_deepseek.py
    → 105 passed (27 provider + 78 deepseek)
make backend-format backend-lint backend-typecheck → all clean (94 files formatted,
    Ruff clean, MyPy 93 source files)
git diff --check                                   → clean
git diff --stat                                    → only pre-existing documentation edits
    (delegate.py, PLANS.md, pyproject.toml, uv.lock, HANDOFF) + the 2-line __init__.py export;
    deepseek.py and test_extraction_deepseek.py are new/untracked
```

The 78 deepseek tests cover: exact request mapping with non-ASCII Schema / deterministic injected
instruction / caller message order / explicit non-thinking + JSON mode / output bound / no request
mutation; successful response mapping with all token fields and ignored private fields; `{}` accepted
while empty/whitespace content is `invalid_response`; invalid top-level JSON and 24 malformed
field cases; timeout, generic transport failure and cancellation propagation; all 17 HTTP mapping rows
with secret/provider-body markers proving no leakage; constructor validation, trimmed key use, safe
repr and output-limit rejection before transport; runtime Protocol conformance; import purity
(standalone subprocess load proves no CCEF/SQLAlchemy/Sanic/store/services/jobs/settings imports).

### 4. Outgoing request carries the deterministic arbitrary Schema instruction without CCEF

The request test asserts the exact system message text (`Return exactly one JSON object ... Schema
name: <name> / JSON Schema: <canonical>`) and the exact payload key set; `deepseek.py` never imports
or names CCEF contracts (proved by the standalone import-purity subprocess test and the source-token
test).

### 5. Assumptions and interface ambiguity

- `finish_reason` presence is required (strict reading of "first choice `finish_reason` either `null`
  or a non-whitespace string"); `null` and non-whitespace strings are accepted, anything missing or
  malformed is `invalid_response`.
- The port's own model constraints (e.g. 255-char `model`/`finish_reason` caps) are enforced by
  wrapping response construction in a `ValidationError` catch that maps to `invalid_response`, so no
  raw pydantic error or provider value can leak.
- Error type choices for the constructor: `TypeError` for wrong Python types (non-string key, bool,
  non-numeric timeout, non-int limit), `ValueError` for empty key, non-finite and out-of-range values.
- Fixed error messages include only the numeric HTTP status where applicable, per the packet.
- No live DeepSeek request, no API key, no paid call, no dependency changes, no quality-gate
  reduction; `httpx>=0.28,<1` was already added to `backend/pyproject.toml`/`uv.lock` by Codex and was
  not touched.

### 6. `git diff --stat` / `git diff --check`

Clean (`git diff --check` reports no whitespace errors). The diff contains only the pre-existing
worktree edits plus the 2-line `__init__.py` export; the two new packet files are untracked and were
not added to the index.

### 7. Status

**Pending Codex review.** 8P-3 is NOT marked complete. 8P-4 (package/reference validation and
python-chess normalization) was NOT started, and no commit was created.

## Final Codex review of DS-STAGE8-DEEPSEEK-ADAPTER-01 (2026-08-11)

**Accepted; 8P-3 complete.** DeepCode stayed within the permitted boundary and its functional
mapping was correct, but independent adversarial review found that `raise mapped_error from exc`
left sensitive vendor exceptions attached to the public error. A transport timeout retained the
request's `Authorization: Bearer <key>` header, while `JSONDecodeError.doc` retained the raw
provider body. Pydantic validation errors could similarly retain rejected provider values.

Codex changed the mapping so sanitized provider errors are raised only after the sensitive except
scope has ended. New parameterized regressions cover transport, malformed JSON and invalid
Pydantic response values, asserting both `__cause__` and `__context__` are `None`. An additional
runtime adversarial script independently proved the key/body markers are unreachable.

Final focused evidence:

```text
test_extraction_provider.py + test_extraction_deepseek.py → 108 passed
backend format / Ruff / MyPy                             → clean
sensitive exception-context adversarial check            → passed
git diff --check                                         → clean
```

No live DeepSeek call, API key or paid request was used. 8P-4 has not started. No commit was
created.

## DS-STAGE8-CCEF-DECODER-01 completion (8P-4A)

### 1. Files changed

- `backend/src/chess_workbench/extraction/decoder.py` (new, 182 lines) — provider-neutral
  `CcefDecodeError` / `CcefDecodeErrorCode` / `decode_extraction_response`.
- `backend/src/chess_workbench/extraction/__init__.py` — export only: one import line
  (`CcefDecodeError`, `CcefDecodeErrorCode`, `decode_extraction_response`) and three `__all__`
  entries. The pre-existing 8P-3 deepseek export is untouched.
- `backend/tests/test_extraction_decoder.py` (new, 61 focused tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched. `contracts.py`, `provider.py`, `deepseek.py`, the checked-in JSON Schema,
dependencies, configuration, SQL, jobs, services, routes, migrations and existing tests are
unchanged; the pre-existing worktree edits are preserved.

### 2. Behavior and validators implemented

- `CcefDecodeErrorCode` literal union of exactly `truncated | invalid_json | invalid_package |
  untrusted_validation`; `CcefDecodeError(ValueError)` enforces the code against the literal
  union and a non-empty actual string message, exposes public `code`/`message`, and
  `str(error) == message`.
- `decode_extraction_response` policy:
  1. `finish_reason == "length"` → `truncated`, `Structured generation was truncated`, before
     content is read.
  2. Standard-library `json.loads` with an `object_pairs_hook` that rejects duplicate member
     names at any nesting depth and a `parse_constant` that rejects `NaN`/`Infinity`/`-Infinity`;
     malformed JSON, fences, trailing commentary, scalar/list top levels and non-object top
     level → `invalid_json`, `Structured generation content is not valid JSON`.
  3. Before Pydantic: every `kind == "move_sequence"` item's nodes may omit `validation_status`
     or set exactly `"unvalidated"` and may only omit/null `san_candidate`, `uci_candidate`,
     `fen_before`, `fen_after`; any other status or non-null authoritative field →
     `untrusted_validation`, `Provider output may contain only unvalidated move nodes`. Malformed
     `items`/`nodes` shapes are skipped by the scanner and left to CCEF validation.
  4. `ExtractionPackage.model_validate` failures (unknown fields, unsupported version, strict
     scalar types, dangling/self/forward-parent and sibling-order violations, malformed shapes)
     → `invalid_package`, `Structured generation content is not a valid CCEF package`.
  5. The validated package is returned without mutating `response`; defaults are CCEF v1's.
- Exception hygiene (same pattern Codex required for 8P-3): the public error is raised only
  after leaving the `json.loads`/Pydantic exception handlers, so `__cause__`/`__context__` stay
  `None` and raw provider content or rejected values never reach `str`/`repr`/`args`/attributes.

### 3. Focused test count and acceptance commands

```text
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_provider.py \
  backend/tests/test_extraction_decoder.py
    → 131 passed (43 contract + 27 provider + 61 decoder)
make backend-format backend-lint backend-typecheck → all clean (96 files formatted,
    Ruff clean, MyPy 95 source files)
git diff --check                                   → clean
git diff --stat                                    → only pre-existing worktree edits +
    the 4-line __init__.py export additions; decoder.py and test_extraction_decoder.py are
    new/untracked
```

The 61 decoder tests cover: valid decode with CCEF defaults and response snapshot unchanged;
`length` wins over valid JSON and over garbage; 20 `invalid_json` cases (malformed JSON, single
quotes, scalar/list top levels, Markdown fences, trailing commentary, `NaN`/`Infinity`/
`-Infinity`, duplicate keys at root/nested/deep levels); 7 `invalid_package` mutations plus 4
malformed `items`/`nodes` shapes left to CCEF; omitted/explicit `unvalidated` with null
authoritative fields accepted; `valid`/`invalid`/`ambiguous`/unknown status and each non-null
authoritative field `untrusted_validation` (including a complete CCEF-satisfying `valid` node);
the trust boundary applied to a second move_sequence item; all four codes raised by the decoder;
constructor code/message validation; marker-free `str`/`repr`/`args`/attributes/`__cause__`/
`__context__` for all four error paths; standalone import purity (no httpx, deepseek, store,
services, api, schemas, config, domain, sqlalchemy, sanic, pydantic_settings); source-token
purity; package exports.

### 4. Invariants preserved

- The provider port and DeepSeek adapter remain CCEF-free and unchanged.
- `contracts.py` and the checked-in Schema remain the only structural/reference contract source.
- Provider output can create only `unvalidated` nodes; no `valid`/`invalid`/`ambiguous` or
  authoritative SAN/UCI/FEN fields are creatable through this decoder.
- No chess parsing, PDF/OCR, HTTP, retry, SQL, filesystem ingestion, ConsumerAdapter, job or
  route work; no dependency change, quality-gate reduction, live/paid call or commit.

### 5. Assumptions

- `validation_status: null` and non-dict items/nodes are treated by the scanner as
  "no validation claim" and therefore fall through to ordinary CCEF validation
  (`invalid_package`), matching the "malformed shapes are left to CCEF" rule.
- `json.loads` is the "standard library" parser; its `object_pairs_hook`/`parse_constant`
  hooks raise `ValueError`, all of which map to `invalid_json` without leaking values.
- `CcefDecodeError` uses `super().__init__(message)` so `args` carries only the fixed public
  message (never raw content), mirroring `StructuredGenerationProviderError`.
- The flagged-raise pattern (raise after leaving the handler) satisfies the packet's stricter
  `__context__ is None` requirement; `raise ... from None` alone would not.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` reports no whitespace errors. The diff contains only the pre-existing worktree
edits (delegate skill, PLANS.md, pyproject.toml, uv.lock, HANDOFF, ADR 0011, the 8P-3 deepseek
files) plus the 4-line `__init__.py` export; `decoder.py` and `test_extraction_decoder.py` are
new/untracked and were not added to the index.

### 7. Status

**Pending Codex review.** 8P-4A is NOT marked complete; 8P-4B (python-chess move-tree
normalization) was NOT started, and no commit was created.

## DS-STAGE8-CHESS-NORMALIZER-01 completion (8P-4B)

### 1. Files changed

- `backend/src/chess_workbench/extraction/validation.py` (new, 190 lines) — deterministic
  python-chess normalizer: `normalize_chess_moves(package) -> ExtractionPackage`.
- `backend/src/chess_workbench/extraction/__init__.py` — export only: one import line
  (`from .validation import normalize_chess_moves`) and one `__all__` entry. The pre-existing
  8P-3/8P-4A exports are untouched.
- `backend/tests/test_extraction_validation.py` (new, 39 collected focused tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched. `contracts.py`, `decoder.py`, `provider.py`, `deepseek.py`, the checked-in
JSON Schema, dependencies, configuration, SQL, jobs, services, routes, migrations and existing
tests are unchanged; the pre-existing worktree edits are preserved.

### 2. Behavior and validators implemented

- `normalize_chess_moves` deep-copies the input, deterministically recomputes every move node of
  every `move_sequence` item from `move_text`, revalidates the result through
  `ExtractionPackage.model_validate(model_dump(mode="json"))` and never mutates the input.
- Initial positions: `StartPosition` → `chess.Board()`; `FenPosition` → `chess.Board(fen,
  chess960=False)` with explicit rejection of `~` placement notation and castling fields outside
  the canonical ordered `K?Q?k?q?`/`-` form, plus `board.is_valid()`. Full six-field canonical
  FEN output via `board.fen(en_passant="fen")`; clocks are preserved, never reset.
- Branch reconstruction: root nodes copy the initial board (root siblings are independent
  alternatives); a child copies its parent's successfully normalized after-board; a node without
  a unique parent board stays `invalid` with the unresolved-parent warning. No guessing through
  gaps.
- Token policy: at most one leading `N.`/`N...` prefix (spaces after), repeatedly removable
  trailing `!`/`?`/`!!`/`??`/`!?`/`?!` and NAG `$0`..`$255` tokens (whitespace between suffixes
  allowed), whitespace-only cleanup rejected, parsed with `board.parse_san` (accepting
  python-chess's standard SAN and legal coordinate-notation extension, then rewritten to canonical
  SAN/UCI). Null moves (`--`, `0000`, `Z0`, `@@@@` parse to `Move.null()`) are rejected.
  `chess.AmbiguousMoveError` is caught separately from other invalid/illegal `ValueError`s.
- Five exact outcomes with stable warning codes/messages (see PLANS.md table): invalid initial
  position, unresolved parent, ambiguous move, invalid move, context mismatch; valid nodes carry
  canonical `san_candidate`, lowercase `uci_candidate`, `fen_before`, `fen_after` computed with
  SAN before push. Optional `side_to_move`/`move_number` must agree with `board.turn` and
  `board.fullmove_number`; omitted context never blocks validity; any invalid/ambiguous node has
  no after-board so all descendants are unresolved.
- Idempotency: prior warnings carrying one of the five validator codes are removed before each
  recompute and at most one current validator warning is appended using a deep copy of the node
  evidence; node IDs, parent/order, raw `move_text`, NAGs, confidence, evidence, extensions and
  unrelated warnings are preserved value-equal.
- Import boundary: `validation.py` imports only the standard library, `chess` (python-chess) and
  `.contracts`; no provider/decoder/deepseek/httpx, Sanic, SQLAlchemy, store, services, jobs,
  settings or domain-schema imports (proved by standalone subprocess load and source-token test).

### 3. Focused test count and acceptance commands

```text
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_validation.py
    → 143 passed (43 contract + 61 decoder + 39 validation)
make backend-format backend-lint backend-typecheck → all clean (98 files formatted,
    Ruff clean, MyPy 97 source files)
git diff --check                                   → clean
git diff --stat                                    → only pre-existing worktree edits +
    the 6 accumulated __init__.py export lines (decoder/deepseek/validation);
    validation.py and test_extraction_validation.py are new/untracked
```

The 39 collected validation tests cover: exact SAN/UCI/before-after FEN values for a startpos mainline
plus root variation with input immutability; legal custom FEN with castling (both sides, incl.
child branch), promotion (SAN and coordinate form), en-passant and coordinate notation; token
normalization (`1.e4`, `1...e5`, `Nf3!!`, `d4$0`, `c4 $255`, `1. Nf3 ! ?`) with failures
(comments, arbitrary prose, two-move tokens, `$256`, empty-after-cleanup, null moves); illegal
moves retained invalid with descendants unresolved; a genuinely ambiguous position (`Ne5` with
two knights) retained `ambiguous`; five invalid six-field FENs (no kings, two white kings, `~`,
Shredder `HAha`, unordered `QKqk`) producing exact root/descendant warnings; side/fullmove
context match and mismatch (including black to move, mismatch blocking the whole descendant
path, and clock preservation on a fullmove-2 FEN); forged `valid` node recomputed with nags/
extensions/unrelated warnings preserved; value-idempotent repeat with no duplicate validator
warnings; warning evidence as an independent deep copy; packages without move sequences returned
as equal but distinct copies; import purity and source-token purity; export presence; exact
message literals for all five codes; mixed valid/invalid sibling branches; and input immutability
for mixed outcomes.

### 4. Invariants preserved

- python-chess is the sole chess-rules authority; AI confidence and prior candidate fields never
  make a node valid (forged `valid` nodes are recomputed from `move_text`).
- Illegal, ambiguous, context-conflicting and disconnected source content is retained for human
  review; nothing is silently deleted or promoted.
- Output stays CCEF v1 with no Course/Knowledge/SQL/approval/provider-private data.
- No PDF/OCR, HTTP, retry, ConsumerAdapter, job, route, persistence or UI work; no live call,
  dependency, Schema/quality-gate change or commit.

### 5. Assumptions

- `parse_san` failure modes are all `ValueError` subclasses (`InvalidMoveError`,
  `IllegalMoveError`, `AmbiguousMoveError`), verified by fuzzing pathological tokens; the
  normalizer additionally fuzz-checked 25 pathological `move_text` values end-to-end, all of
  which stay `invalid` without raising.
- The CCEF contract's `move_text` field (`strip_whitespace=True`) pre-strips surrounding
  whitespace, so a trailing-space token cannot reach the normalizer; the token policy's
  whitespace rule is implemented for whitespace exposed between suffixes, and a trailing-space
  test case was dropped because it is untestable through the contract.
- The fullmove clock of a declared `FenPosition` is preserved in `fen_before`/`fen_after` (e.g.
  fullmove-2 input stays fullmove-2 after the first move), matching "do not reset clocks".
- `board.san(move)` may include a check suffix (`a8=Q+`); that is python-chess's canonical SAN
  and is stored as-is.
- `fen_before`/`fen_after` use `board.fen(en_passant="fen")` explicitly because this python-chess
  version's default `en_passant` mode is `"legal"`, not `"fen"`.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` reports no whitespace errors. The diff contains only the pre-existing worktree
edits (delegate skill, PLANS.md, pyproject.toml, uv.lock, HANDOFF, ADR 0011, the 8P-3 deepseek
files, the 8P-4A decoder files) plus the accumulated `__init__.py` export lines;
`validation.py` and `test_extraction_validation.py` are new/untracked and were not added to the
index.

### 7. Status

**Pending Codex review.** 8P-4B is NOT marked complete; 8P-5 (consumer proof) was NOT started,
and no commit was created.

## Final Codex review of DS-STAGE8-CHESS-NORMALIZER-01 (2026-08-11)

**Accepted; 8P-4 complete.** The worker stayed inside the permitted implementation boundary.
Codex independently reviewed the move-tree board propagation, standard-FEN restrictions,
context-mismatch blocking, ambiguous/illegal handling, authoritative-field reset, warning
idempotency and deep-copy behavior. A separately constructed two-knight ambiguous position proved
that the ambiguous node never becomes `valid`, its descendant is retained with
`ccef_chess_unresolved_parent`, the source package is unchanged, and a second normalization is
value-identical.

Independent verification:

```text
pytest contract + decoder + validation → 143 passed
  (43 contract + 61 decoder + 39 validation)
independent adversarial script          → independent-adversarial-ok
backend format/lint/typecheck           → clean (98 formatted, Ruff clean, MyPy 97 files)
git diff --check                        → clean
```

No cumulative Stage 8/whole-repository acceptance was run during this iterative packet, matching
the user's requested fast feedback policy. No live/paid model request and no commit were made.
`PLANS.md` has no active worker packet; 8P-5 has not started.

## DS-STAGE8-CONSUMER-PROOF-01 completion (8P-5)

### 1. Files changed

- `examples/ccef_consumer/consumer.py` (new, 282 lines) — standalone example reader.
- `contracts/examples/chess-content-extraction-v1.sample.json` (new) — public synthetic sample.
- `contracts/examples/chess-content-extraction-v1.reader.json` (new) — exact golden stdout
  projection of the sample (11,905 bytes).
- `backend/tests/test_ccef_consumer_proof.py` (new, 26 focused tests).
- `docs/architecture/ccef-chess-workbench-mapping.md` (new) — Codex-frozen one-way mapping plan.
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched. The pre-existing worktree edits (delegate skill, PLANS.md,
backend/pyproject.toml + uv.lock jsonschema dependency, ADR 0011, the 8P-3/8P-4 extraction files
and their tests) are preserved untouched; `backend/src/chess_workbench/extraction/__init__.py`
was not modified by this packet.

### 2. Behavior and validators implemented

- `consumer.py` imports only the standard library and exactly
  `Draft202012Validator, FormatChecker, SchemaError, ValidationError` from `jsonschema`
  (untyped; targeted `# type: ignore[import-untyped]`, no config change). Exposes
  `load_validated_package(schema_path, package_path) -> dict`, `project_reader_document(package)
  -> dict` and `main(argv=None) -> int` with the exact CLI. Loads both files UTF-8 via `json.load`,
  requires object top levels, checks Schema `$schema`/`$id`, calls
  `Draft202012Validator.check_schema` then validates with `FormatChecker()`, defensively requires
  `schema_version == "chess-content-extraction/1.0"`, and never fetches remote references.
  Success writes the deterministic projection with `json.dumps(..., ensure_ascii=False,
  sort_keys=True, indent=2) + "\n"` to stdout, nothing to stderr, return 0. Rejection writes
  exactly `CCEF consumer rejected the input\n` to stderr, nothing to stdout, return 2;
  `KeyboardInterrupt`/`SystemExit`/`MemoryError` and other `BaseException` values propagate.
- Reader projection: `consumer_format example-ccef-reader/1`, deep-copied source/provenance/
  diagnostics, entries in package order with `type`/`source_id`/`evidence`/`confidence`/
  `warnings`/`extensions` (defaults `null`/`[]`/`{}`), kind-specific fields exactly per PLANS.md
  (including node `status` default `unvalidated`, prose `text_format` default `plain`), and an
  unknown-kind `ValueError` for direct callers. The input package is never mutated.
- Review queue: item-warning entries, one entry per flagged move node (`move_<status>` first when
  not `valid`, then warning codes, dedup preserving first occurrence), unresolved `reason_code`
  merged into that item's entry, then warning/error diagnostics as `diagnostic_<code>` entries
  (info excluded, never merged), all in deterministic encounter order.
- Sample: fixed UUID/timestamps, `source_ref="sample://opening-book/chapter-8"`, page range
  319..399, all five kinds in reading order, both prose anchor kinds plus one narrative prose,
  one startpos `move_sequence` with a root variation and a child variation containing a retained
  illegal node (`ccef_chess_invalid_move`), a chessboard figure with an item warning, an
  unresolved item with `ocr_unclear` plus a warning, info + warning diagnostics, evidence with
  page/bbox/offset/hash variants, confidence, NAG `[40]` and `com.example.reader` extensions.
  All valid nodes carry exact canonical SAN/UCI/six-field FEN (python-chess verified) and the
  package is value-identical under `normalize_chess_moves`.
- Mapping doc: the Codex-frozen nine decisions (preconditions/ownership, evidence + Stage 8A/8D
  blocker, ordered items, moves, NAG mismatch, anchored prose, figures/unresolved,
  atomicity/idempotency, stage boundary/checklist with the four blockers), explicitly
  design-only with no adapter/API/SQL write.

### 3. Focused test count and acceptance commands

```text
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_validation.py backend/tests/test_ccef_consumer_proof.py
    → 169 passed (43 contract + 61 decoder + 39 validation + 26 consumer proof)
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff format --config backend/pyproject.toml --check \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
    → 2 files already formatted
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff check --config backend/pyproject.toml \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
    → All checks passed
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
    → Success: no issues found in 2 source files
git diff --check → clean
git diff --stat  → only the pre-existing tracked worktree edits (packet files are new/untracked)
```

The 26 consumer-proof tests cover: Schema check + sample Schema/Pydantic validation +
normalization idempotency; `python -I` CLI stdout byte-identical to the golden with empty
stderr; projection fidelity (ids/kinds/order, both anchors, tree parent/order, canonical move
fields, defaults, evidence, extensions, deep copies, input immutability) and the golden's exact
review queue; queue ordering/merge/dedup plus warning/error diagnostics with info excluded;
13 rejected-input rows (invalid JSON, scalar/list top levels for schema and package, wrong
dialect/ID, invalid Schema, unknown package field, unsupported version, bad UUID, bad
date-time) each returning 2 with only the fixed stderr; missing-file containment; direct
unknown-kind `ValueError`; injected `KeyboardInterrupt`/`MemoryError` propagation; AST import
boundary; an isolated `python -I` driver run proving `chess_workbench`/pydantic/chess/httpx/
sanic/sqlalchemy/store/services/jobs/config are absent from `sys.modules`; mapping-document
content coverage.

### 4. Invariants preserved

- The example consumes only the published Schema/package boundary and owns its separate reader
  projection; it never imports or exposes ChessWorkbench domain concepts (`python -I` from the
  repository root proves the repository and backend source are not import paths).
- Schema validation proves portable shape; ADR 0010/ccef-v1 and the producer remain
  authoritative for cross-reference/tree/chess invariants not encoded in JSON Schema.
- Unknown/unresolved/invalid content remains visible in the review queue; no silent loss or
  automatic formal publication.
- No production extraction change, provider/network call, PDF/OCR, SQL, API, job, UI, actual
  ConsumerAdapter, quality-gate reduction, `__init__.py`/config/dependency edit or commit.
- Repeated runs are byte-for-byte stable (re-verified independently after all edits).

### 5. Assumptions

- Unresolved-item queue merge order is `[reason_code, *item warning codes]` (dedup, first
  occurrence wins), parallel to the move-node rule where the status reason comes first.
- Item-warning entries keep warning codes in original order without dedup (the packet only
  specifies dedup for node reasons); duplicate codes would be impossible through the model only
  if warning codes were unique, which they are not constrained to be.
- The mapping document test normalizes whitespace before phrase matching so prose line-wrapping
  cannot break the required-phrase assertions.
- `jsonschema` ships no type stubs; the import is annotated with `# type: ignore[import-untyped]`
  (no mypy config change, which is outside the edit boundary).
- `python -I` still loads the venv site-packages (only user site and PYTHONPATH are disabled), so
  the isolated runs can import `jsonschema` while the repository/backend source stay off
  `sys.path`.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` reports no whitespace errors. `git diff --stat` contains only the pre-existing
tracked worktree edits (delegate skill, PLANS.md, pyproject.toml, uv.lock, HANDOFF, ADR 0011,
`__init__.py` exports); all five packet files are new/untracked and were not added to the index.

### 7. Status

**Pending Codex review.** 8P-5 is NOT marked complete; the final 8P boundary review and Stage 8A
were NOT started, and no commit was created.

## Final Codex review of DS-STAGE8-CONSUMER-PROOF-01 (2026-08-11)

**Accepted; 8P-5 complete.** Codex independently reviewed the consumer isolation, Schema/package
validation, projection fidelity, review-queue ordering, synthetic fixture, golden output and the
one-way mapping plan. The initial worker implementation had one blocking discrepancy: it stated
that validation never fetched remote references but did not enforce that property. Codex added a
pre-validation recursive gate for non-fragment `$ref`, `$dynamicRef` and `$recursiveRef`, plus
sentinel tests proving validator construction is never reached for those inputs. The CLI also
returns its fixed rejection response for an external `$ref` Schema.

Independent verification:

```text
pytest contract + decoder + validation + consumer proof → 173 passed
  (43 contract + 61 decoder + 39 validation + 30 consumer proof)
python -I consumer output vs golden                    → byte-identical
configured Ruff format/check and MyPy                  → clean
git diff --check                                       → clean
```

Files owned by 8P-5 are `examples/ccef_consumer/consumer.py`, the two
`contracts/examples/chess-content-extraction-v1.*.json` fixtures,
`backend/tests/test_ccef_consumer_proof.py`, and
`docs/architecture/ccef-chess-workbench-mapping.md`; Codex also added the already-planned
development-only `jsonschema` dependency and lock entries. No production extraction logic,
published CCEF Schema, SQL/API/job/UI code or actual ConsumerAdapter was changed. No live/paid
provider call, full-repository acceptance run or commit was made. The final 8P feature-boundary
review and Stage 8A remain unstarted.

## Final 8P feature-boundary review (2026-08-11)

**Accepted; all 8P deliverables now compose across their real package boundary.** Codex reviewed
the complete dependency path rather than relying on each packet's isolated import harness and
made these final corrections:

1. `chess_workbench.extraction` now lazily exports the DeepSeek adapter and chess normalizer;
   importing the portable contract no longer eagerly imports `httpx` or `chess`.
2. The canonical Schema now sets `additionalProperties: false` on all seven namespaced extension
   maps and requires all four union discriminators. Schema-only consumers therefore reject bad
   extension keys and no longer accept discriminator-less values rejected by Pydantic.
3. `StructuredGenerationResponse.finish_reason` is provider-neutral `stop | length | null`.
   DeepSeek requires a real non-streaming finish reason, preserves `stop`/`length`, maps
   `insufficient_system_resource` to retryable `unavailable`, and rejects all other conditions as
   sanitized `invalid_response`.
4. Deeply nested model JSON that exceeds the Python parser recursion bound becomes sanitized
   `invalid_json`, with no chained raw-content exception.
5. The standalone consumer rejects NaN/Infinity extensions accepted by Python's permissive JSON
   parser, handles Schema-valid omission of the default `items` list, and keeps its remote-reference
   rejection gate.

Current official DeepSeek endpoint/model/thinking/JSON-output and finish-reason facts were checked
against `https://api-docs.deepseek.com/api/create-chat-completion` and
`https://api-docs.deepseek.com/quick_start/pricing`; no live request or API key was used.

Final focused verification:

```text
pytest contract/provider/deepseek/decoder/validation/consumer → 294 passed
configured Ruff format/check                                → clean
configured MyPy over all 8P modules and focused tests       → clean
python -I standalone consumer vs golden                     → byte-identical
git diff --check                                            → clean
```

No full backend/frontend/repository acceptance, SQL/API/job/UI work, actual ConsumerAdapter,
PDF/OCR processing or commit was performed. 8P is complete; 8A remains unstarted and must begin
with a Codex-owned architecture plan.

## DS-STAGE8A-CAS-01 completion (8A-1)

### 1. Files changed

- `backend/src/chess_workbench/services/source_storage.py` (new) — reusable atomic bytes CAS
  primitive: `StoredSourceBlob` frozen result and `store_content_addressed_bytes(...)`.
- `backend/src/chess_workbench/services/pgn.py` — `prepare_pgn_import` now calls the new
  primitive (namespace `sources/pgn`, suffix `.pgn`); the private `_store_cas` duplicate and the
  now-unused `os`/`tempfile` imports were removed. Nothing else in the module changed.
- `backend/tests/test_source_storage.py` (new, 27 collected tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file touched. Schemas, SQL models/migrations, routes, configuration, dependencies,
lockfiles, Makefile, ADRs, frontend and all pre-existing worktree edits are untouched; the new
files are untracked and were not added to the index.

### 2. Behavior and validators implemented

- `StoredSourceBlob` is a `@dataclass(frozen=True, slots=True)` value carrying `relative_path`,
  lowercase `sha256`, `size_bytes` and `reused`.
- `store_content_addressed_bytes(storage_root, *, namespace, suffix, raw_bytes)` validates
  `namespace` (one or more lowercase ASCII segments matching `[a-z0-9][a-z0-9_-]*` separated only
  by `/`) and `suffix` (`.` plus 1..16 lowercase ASCII alphanumerics) with anchored regexes
  **before any filesystem access**; absolute paths, empty/dot/dot-dot segments, backslashes,
  whitespace and non-ASCII raise `ValueError`. The digest is always computed from the bytes; no
  caller-supplied path or expected digest exists.
- Returned path is exactly `<namespace>/<sha256[:2]>/<sha256><suffix>`.
- Write guarantees preserved from the proven PGN CAS: mkdir parents; existing destination is
  size+hash verified and reused (`reused=True`); otherwise a same-directory temp file is
  written/flushed/fsynced, chmod 0600, size+hash verified, atomically replaced, with the temp
  path always cleaned, returning `reused=False`.
- Any filesystem `OSError` (including an existing corrupt blob) becomes
  `ServiceError(code="source_storage_unavailable", status=503)` with generic message
  `"source storage is unavailable"`, raised `from None` so no absolute path or OS text is
  reachable through `__cause__`/`__context__` either.
- `prepare_pgn_import` re-raises that sanitized error with the exact original PGN message
  (`"PGN source storage is unavailable"`) so the PGN error contract, API responses, hashes,
  `relative_path` and the `sources/pgn/<prefix>/<hash>.pgn` layout stay byte-for-byte unchanged.

### 3. Focused test count and acceptance commands

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_source_storage.py backend/tests/test_pgn_api.py
    → 39 passed (27 source storage + 12 PGN API)
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
    → 3 files already formatted
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
    → All checks passed
uv run --project backend --locked mypy \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
    → Success: no issues found in 3 source files
git diff --check → clean
```

Bonus sanity run (not in the packet's exact command list): the existing PGN integration suite
`backend/tests/test_pgn_import.py` passes 18/18, confirming the CAS refactor preserved PGN
behavior including `source_storage_unavailable` on corrupt blobs and unavailable roots.

The 27 source-storage tests cover: exact bytes/path/hash/size and mode 0600 with `reused=False`;
replay returns the same result with `reused=True` and unchanged contents with no temp remnants;
frozen result immutability and digest computed from the bytes; a multi-segment namespace plus
alphanumeric suffix; 12 invalid namespace families and 8 invalid suffix families each raising
`ValueError` before creating any storage-root content; a pre-existing corrupt destination raising
the sanitized `ServiceError` (code/status/message, no path/OS text, `__cause__ is None`) without
being overwritten; and injected write (`os.fdopen`) / replace (`os.replace`) failures leaving no
`*.tmp` file and exposing no absolute path/OS text.

### 4. Invariants preserved

- No raw bytes, absolute path or `OSError` text crosses the public service error; `from None`
  keeps `__cause__`/`__context__` free of OS text.
- Existing corrupt blobs are treated as storage failure and are never overwritten.
- Existing PGN tests were not weakened or rewritten; PGN API responses, hashes, relative path and
  the `sources/pgn/<prefix>/<hash>.pgn` layout are unchanged.
- No class hierarchy, async I/O, streaming, new dependency or PDF-specific code introduced.
- The packet's permitted edit boundary was respected exactly.

### 5. Assumptions

- Item 6 "keep PGN ... errors ... unchanged" was read literally: `prepare_pgn_import` re-raises
  the new module's sanitized `ServiceError` with the original PGN-specific message, because the
  message text flows into the PGN HTTP error body via the `ServiceError` handler. The new module
  itself uses the packet-mandated generic message `"source storage is unavailable"` (verified in
  its own tests). If Codex intended the generic message to propagate through the PGN path too,
  this is the single place to change.
- The re-raise uses `from None`, so the PGN path no longer retains the underlying `OSError` in
  `__cause__` (previously it did); no test asserts the chain, and dropping it is strictly safer
  w.r.t. the packet's no-path-exposure invariant.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` shows only the pre-existing tracked worktree edits
plus the `pgn.py` refactor; `source_storage.py` and `test_source_storage.py` are new/untracked.

### 7. Status

**Pending Codex review.** 8A-1 is NOT marked complete; 8A-2 (PDF domain) was NOT started, and no
commit was created.

## Codex final review of DS-STAGE8A-CAS-01 (2026-08-11)

**Accepted; 8A-1 is complete.** The actual implementation and packet boundaries were reviewed.
The delegated result initially sanitized displayed exception chaining with `raise ... from None`,
but the underlying `OSError` remained programmatically reachable through `__context__`. Codex
changed the control flow so the public `ServiceError` is constructed after leaving the handler and
added direct assertions that both `__cause__` and `__context__` are `None` for corrupt-file and
injected-I/O failures.

Codex also closes the raw descriptor if `os.fdopen` raises and replaces whole-file `read_bytes()`
verification with 1 MiB streaming hashes, preventing a future 256 MiB PDF replay from allocating a
second whole-file buffer. Exact PGN paths, response message, hashes and behavior remain unchanged.

Independent focused verification:

```text
pytest source_storage + PGN API → 39 passed
configured Ruff format/check   → clean
configured MyPy                → clean
git diff --check               → clean
```

No full repository acceptance, PDF parsing, SQL/API/job/frontend change, live provider call or
commit was made. ADR 0012 is the accepted 8A design; 8A-2 is the next independent unit.

## DS-STAGE8A-PDF-INSPECTION-01 completion (8A-2A)

### 1. Files changed

- `backend/pyproject.toml` — one production dependency line added: `pypdf>=6.14.2,<7`.
- `backend/uv.lock` — resolver output for pypdf only (`pypdf==6.15.0` wheel/sdist entries plus the
  two project dependency lines); all accumulated 8P entries are preserved.
- `backend/src/chess_workbench/logic/pdf.py` (new) — the bounded inspection boundary.
- `backend/tests/test_pdf_inspection.py` (new, 63 collected tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file was edited. CAS/PGN, configuration, schemas, models, migrations, services, routes,
frontend, Makefile, ADRs, existing tests and `data/books` are untouched; pre-existing worktree
edits (delegate skill, PLANS.md, 8P extraction files, httpx/jsonschema lock entries, ADR 0011/0012)
are preserved.

### 2. Behavior and validators implemented

- Public surface exactly as frozen: `MAX_PDF_BYTES = 256 * 1024 * 1024`, `MAX_PDF_PAGES = 20_000`,
  frozen+slots `PdfInspection(filename, size_bytes, page_count, media_type="application/pdf")`,
  `PdfInspectionError(ValueError)` with the seven `reason` literals, and
  `inspect_pdf(raw_bytes, *, filename, declared_media_type, max_bytes=..., max_pages=...)`.
- Fixed validation order: programmer type/limit misuse raises `TypeError`/`ValueError` (not
  `PdfInspectionError`), then `empty_pdf`, `payload_too_large` (`len > max_bytes`), `invalid_filename`
  (1..200 code points, no C0/C1 control/NUL/`/`/`\`, non-empty/non-dot/non-whitespace basename
  before a case-insensitive `.pdf` suffix, no leading/trailing whitespace), `unsupported_media_type`
  (ASCII-whitespace-trim + lowercase; only `None`/empty/`application/pdf` accepted), then a
  `%PDF-<major>.<minor>` header (major 1|2, exactly one decimal minor digit) searched within the
  first 1024 bytes before the parser is ever constructed.
- Parser step: `pypdf.PdfReader(BytesIO(raw_bytes), strict=False, root_object_recovery_limit=10_000)`;
  `is_encrypted` is checked before any page access (`encrypted_pdf`); `len(reader.pages)` of 0 is
  `invalid_pdf`, above `max_pages` is `page_limit_exceeded`. Every parser/data failure maps to
  `invalid_pdf`; the public error is constructed only after leaving the handler so both `__cause__`
  and `__context__` are `None` and no raw bytes/parser text/absolute path is reachable.
  `MemoryError`, `KeyboardInterrupt`, `SystemExit` and other `BaseException` values propagate.
- Success returns the exact input filename, byte length, physical page count and canonical MIME;
  no text/metadata/attachment/JavaScript/label extraction and no file writes.

### 3. Focused test count and every acceptance command result

```text
uv lock --project backend                                    → Resolved 62 packages, added pypdf v6.15.0
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_inspection.py                        → 63 passed
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py → 2 files already formatted
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py → All checks passed
uv run --project backend --locked mypy \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py → Success: no issues in 2 source files
git diff --check                                             → clean
```

The 63 tests cover: 1-page/3-page exact immutable metadata; uppercase `.PDF` and empty/None/
case-variant MIME; input bytes unchanged; `empty_pdf` precedence; `payload_too_large` with exact
boundary; 23 filename families (empty, 201 code points, leading/trailing whitespace, traversal,
`/`/`\`, NUL, C0/C1 controls, dot basename, wrong suffix); 9 wrong/parameterized MIME families;
12 missing/bad-signature rows (fake `%PDF`, major 0/3, two-digit minor `1.70`, lowercase, header
after byte 1024); zero-page writer; encrypted fixture rejected before page access; `page_limit_exceeded`
with exact boundary; short-binary-comment header accepted and header at byte 1024 rejected with the
parser proven unconstructed; 14 monkeypatched parser/data failures sanitized with no
cause/context/attacker text; parser never constructed for preflight failures; injected
`KeyboardInterrupt`/`MemoryError` propagation; programmer type/limit misuse → `TypeError`/`ValueError`;
reason-literal enforcement; frozen constants.

### 4. Invariants preserved

- No PDF output enters CCEF or ChessWorkbench models; inspection only.
- No warning/test/coverage/type floor weakened; pypdf's own warnings are not silenced.
- No user book was read and no live/network test was added; all fixtures are generated in memory
  with `pypdf.PdfWriter`.
- Public errors contain no raw bytes, parser text or absolute path and have no chained exception.

### 5. Assumptions and API facts

- **pypdf 6.15.0 exports `PdfReadError` from `pypdf.errors`, not the `pypdf` top level.** The frozen
  contract says to contain `PdfReadError`; the implementation catches `PyPdfError` (its base from
  `pypdf.errors`), which covers `PdfReadError` plus every sibling parser failure (`ParseError`,
  `PdfStreamError`, `FileNotDecryptedError`, `EmptyFileError`, ...). Listing both would trip Ruff
  B014 (duplicate exception types in one handler).
- `PdfReader.__init__` accepts exactly the frozen call
  (`strict=False`, `root_object_recovery_limit=10_000`) — verified against the installed package.
- Filename length is measured in Python code points (`len(str)`); "non-dot basename" is read as
  "basename is not exactly `.`", so `book.v1.pdf` remains valid.
- Leading/trailing whitespace uses `str.strip()` (Unicode-aware); the MIME trim is ASCII-only as
  frozen.
- The 1..200 code-point limit applies to the whole filename including the suffix (e.g. 196 + `.pdf`
  + `x` fails); this was the natural reading of "1..200 Unicode code points".
- pypdf emits `PdfReadWarning` text to stderr for the junk-prefixed header fixture; it is a warning,
  not an error, and is not silenced.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` shows only the pre-existing tracked worktree edits
plus the one-line `pyproject.toml` dependency addition; `pdf.py` and `test_pdf_inspection.py` are
new/untracked and were not added to the index.

### 7. Status

**Pending Codex review.** 8A-2A is NOT marked complete; 8A-2B (PdfAsset/ExtractionRun/Artifact
persistence + migration) was NOT started, and no commit was created.

## Codex final review of DS-STAGE8A-PDF-INSPECTION-01 (2026-08-11)

**Accepted; 8A-2A is complete.** Codex independently reviewed the pure inspection implementation,
all 63 tests and the dependency/lock delta. Filename and MIME gates precede signature/parser work;
the parser is called with `strict=False` and bounded root recovery; encryption is checked before
page access; parser/data failures become fixed errors only after leaving the exception handler, so
both `__cause__` and `__context__` remain empty. `MemoryError`, `KeyboardInterrupt` and other
BaseException values are not contained.

Latest resolution selected `pypdf==6.15.0`, within `>=6.14.2,<7`. It remains BSD-3-Clause; no
AGPL PyMuPDF, renderer, OCR dependency or tool manifest was added. The initial delegated run paused
because the wheel was absent from cache; Codex performed `uv sync --project backend --locked` and
resumed that same private session without involving the user.

Independent focused verification:

```text
pytest PDF inspection → 63 passed
configured Ruff       → clean
configured MyPy       → clean
git diff --check      → clean
```

No user book was read, and no file storage, SQL/API/job/frontend, full acceptance, live provider
call or commit was performed. The active next packet is `DS-STAGE8A-PDF-MODELS-01`.

## DS-STAGE8A-PDF-MODELS-01 completion (8A-2B)

### 1. Files changed

- `backend/src/chess_workbench/store/models/extraction.py` (new, 142 lines) — the three immutable
  Stage 8A ORM records `PdfAsset` / `ExtractionRun` / `ExtractionArtifact` plus local
  `_ascii_string` / `_case_sensitive_string` helpers (own copies, no private helper imported).
- `backend/src/chess_workbench/store/models/__init__.py` — imports/exports only: one import block
  and three `__all__` entries (`PdfAsset`, `ExtractionRun`, `ExtractionArtifact`).
- `backend/migrations/env.py` — model registration only: the three names added to the import list
  and to `_REGISTERED_MODELS`; the registration import block was re-sorted alphabetically because
  the packet's exact `ruff check` gate runs on this file (the Makefile lint previously excluded
  `backend/migrations`, so the pre-existing block was not sorted).
- `backend/migrations/versions/20260811_0010_stage8_pdf_extraction.py` (new, 194 lines) — one
  additive revision `20260811_0010`, down `20260810_0009`; upgrade asset → run → artifact with
  `op.create_index` for the three indexes; downgrade is exact reverse with `op.drop_table` only.
- `backend/tests/test_stage8_models.py` (new, 8 collected tests) — focused model-shape suite.
- `backend/tests/test_models.py` — exact revision count updated `9` → `10` plus one small
  import/registration assertion for the new tables; ruff also re-sorted the existing import block
  (sqlalchemy group before chess_workbench) to satisfy the packet's `--project backend` lint gate.
- `docs/agent/HANDOFF.md` — this evidence.

No other file was touched. All pre-existing worktree edits (delegate skill, PLANS.md, 8P
extraction files, pypdf/httpx/jsonschema lock entries, ADR 0010/0011/0012, 8A-1/8A-2A files) are
preserved untouched.

### 2. Behavior and validators implemented

- `PdfAsset` (`pdf_assets`): `content_sha256` ascii-binary String(64), `byte_size` and
  `page_count` Integer; RESTRICT FKs to `sources` / `source_versions` / `source_files`; checks for
  hash length 64, byte size > 0 and page count 1..20,000; four separate unique constraints
  (content hash, source_id, source_version_id, source_file_id).
- `ExtractionRun` (`extraction_runs`): RESTRICT FKs to `pdf_assets` and `jobs`; `first_page` /
  `last_page` Integer; `pipeline_version` String(32); `logical_fingerprint` and
  `effective_key_hash` ascii-binary String(64); checks first page >= 1, last >= first, non-empty
  pipeline version, both hashes length 64; unique `effective_key_hash` and unique `job_id`;
  `logical_fingerprint` is intentionally **not** unique — indexed via
  `ix_extraction_runs_fingerprint` plus `ix_extraction_runs_asset_created (pdf_asset_id,
  created_at)`.
- `ExtractionArtifact` (`extraction_artifacts`): RESTRICT FK to `extraction_runs`; `kind`
  String(32) restricted to the seven frozen literals; nullable `page_number` with check
  `page_number IS NULL OR page_number >= 1`; case-sensitive (utf8mb4_bin) `relative_path`
  String(512); `media_type` String(255); `byte_size`; ascii-binary `content_sha256`; unique
  `relative_path`, unique `(run_id, kind, content_sha256)` and
  `ix_extraction_artifacts_run_kind_page (run_id, kind, page_number)`.
- All three use `UUIDPrimaryKeyMixin + UTCCreatedAtMixin + Base` (InnoDB), RESTRICT FKs only,
  and relationships only inside the asset → run → artifact chain (no Source/Job ORM coupling, no
  cascade/delete-orphan, no lifecycle/version/archive fields).
- Migration renders MySQL InnoDB, ascii/utf8mb4 binary collations and `DATETIME(6)` via the
  established `_utc_datetime` / `_ascii_string` / `_case_sensitive_string` helpers and `op.f()`
  constraint names matching the model naming-convention output; every constraint name stays ≤ 64.

### 3. Focused test count and every acceptance command result

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8_models.py backend/tests/test_models.py
    → 18 passed (7 stage8 models + 11 test_models)
uv run --project backend --locked ruff format --check \
  <the six packet files>                              → 6 files already formatted
uv run --project backend --locked ruff check \
  <the six packet files>                              → All checks passed
uv run --project backend --locked mypy \
  <the six packet files>                              → Success: no issues in 6 source files
git diff --check                                      → clean
```

The 8 stage8 tests cover: exact table/column sets with no
status/version/updated_at/archived_at; UUID + aware-UTC creation round trip through a linked
Source/Version/File/Job/asset/run/artifact chain; every check/unique constraint rejecting a
minimal invalid row on SQLite (4 asset checks + 4 asset uniques, 5 run checks + 2 run uniques,
6 artifact checks + 2 artifact uniques); two runs sharing one `logical_fingerprint` with distinct
effective keys/jobs; RESTRICT FKs + MySQL DDL containing InnoDB/ascii_bin/utf8mb4_bin/DATETIME(6)
with all constraint names ≤ 64; offline SQLite migrations to head with `compare_metadata == []`
and downgrade to zero tables; offline MySQL downgrade with `DROP TABLE` only and no `DROP INDEX`.

### 4. Invariants preserved

- Job is the only operational status; no status/progress/result JSON column on `ExtractionRun`.
- The three records are immutable receipts/indexes — no update/archive/version mixins, no delete
  cascade; the only lifecycle column is `created_at`.
- Source/Version/File ownership and CCEF IDs are unchanged; no package/provider data stored.
- No service transaction, HTTP schema/route, worker behavior, file I/O or PDF parsing was added.
- No dependency, config, frontend, Makefile, ADR, existing migration or quality-gate change.

### 5. Assumptions

- "Relationships may be added only between these records and their direct Source/Job parents" was
  read as permissive; relationships were added only inside the asset → run → artifact chain, and
  no Source/Job ORM relationship was added to keep the new module decoupled from `content.py` /
  `engine.py` (nothing in the frozen tests requires it).
- `page_count >= 1 AND page_count <= 20000` and `last_page >= first_page` render identically on
  SQLite and MySQL 8.0.16+; the `page_number IS NULL OR page_number >= 1` form is the portable
  nullable-check idiom already used in this codebase.
- `backend/migrations/env.py` needed a mechanical import re-sort because the packet's exact `ruff
  check` command lints that file while the Makefile `backend-lint` never did; the edit touches
  only the registration import block. The same `--project backend` classification also re-sorted
  the pre-existing `test_models.py` import block (sqlalchemy before chess_workbench).
- The `effective_key_hash` and `job_id` unique names were authored to equal the naming-convention
  output (`uq_extraction_runs_*`), matching the existing `pgn_assets` pattern.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. The tracked diff contains only the pre-existing worktree edits plus
the four boundary files (`env.py` registration, `store/models/__init__.py` exports,
`test_models.py` revision/import assertions, this HANDOFF); the three new packet files are
untracked and were not added to the index.

### 7. Status

**Pending Codex review.** 8A-2B is NOT marked complete; 8A-2C (persistence/idempotency service)
was NOT started, and no commit was created.

## DS-STAGE8A-PDF-PREPARE-01 completion (8A-2C1)

### 1. Files changed

- `backend/src/chess_workbench/services/pdf.py` (new, 141 lines) — pure pre-transaction PDF
  upload preparation: `PreparedPdfAsset` and `prepare_pdf_asset(...)`.
- `backend/tests/test_pdf_prepare.py` (new, 31 collected focused tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file was touched. All pre-existing worktree edits (delegate skill, PLANS.md, 8P
extraction files, pypdf/httpx/jsonschema lock entries, ADR 0010/0011/0012, 8A-1/8A-2A/8A-2B
files) are preserved untouched; `git status --short` confirms only the two new packet files were
added by this worker.

### 2. Behavior and validators implemented

- `PreparedPdfAsset` is a `@dataclass(frozen=True, slots=True)` with the exact nine public fields
  (`filename`, `content_sha256`, `size_bytes`, `page_count`, `relative_path`, `title`, `author`,
  `edition`, `storage_reused`); no raw bytes, parser object, absolute path or mutable mapping is
  retained.
- `prepare_pdf_asset(raw_bytes, *, filename, declared_media_type, title, author, edition,
  storage_root, max_bytes=MAX_PDF_BYTES, max_pages=MAX_PDF_PAGES)` implements the frozen order:
  1. `inspect_pdf` is called first (before any filesystem operation) with exactly the five
     inspection inputs; `PdfInspectionError` is captured and the public `ServiceError` is raised
     only after leaving the `except` block, so both `__cause__` and `__context__` are `None` and
     no parser message/bytes/path leaks. Mapping: `payload_too_large` → code/status 413/message
     `PDF payload exceeds the configured limit`/details `{"limit_bytes": max_bytes}`;
     `unsupported_media_type` → status 415/code same/message `PDF media type is not supported`/
     details `{"reason": ...}`; every other reason → status 422/code `validation_error`/message
     `PDF upload is invalid`/details `{"reason": ...}`.
  2. Display metadata is validated only after successful inspection and before CAS: every
     non-None value must be an actual `str` (else `TypeError`), equal its `.strip()` value, and be
     1..200 Unicode code points; whitespace/length failures raise the stable
     `ServiceError("validation_error", 422, "PDF metadata is invalid", {"field": <name>})` with no
     raw value. A missing `title` defaults exactly to the validated filename without its final
     `.pdf` suffix, preserving spelling/case; `author`/`edition` remain optional.
  3. The original bytes are stored through the accepted generic CAS with exact namespace
     `sources/pdf`, suffix `.pdf`; hashing and file writes are not reimplemented, and the generic
     sanitized `source_storage_unavailable` ServiceError passes through unchanged.
  4. The result carries inspection filename/size/page count, CAS hash/path/reused flag and the
     normalized metadata.
- `KeyboardInterrupt`, `SystemExit` and other non-`Exception` BaseException values from
  inspection, metadata access and CAS propagate unchanged (only `PdfInspectionError` is caught;
  `TypeError`/`ValueError` programmer misuse propagates as-is).

### 3. Focused test count and every acceptance command result

```text
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_prepare.py backend/tests/test_pdf_inspection.py \
  backend/tests/test_source_storage.py
    → 121 passed (31 prepare + 63 inspection + 27 source storage)
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
    → 2 files already formatted
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff check \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
    → All checks passed
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked mypy \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
    → Success: no issues found in 2 source files
git diff --check → clean
```

The 31 prepare tests cover: exact one-page blob bytes/path/hash/size and mode 0600 under
`sources/pdf/<prefix>/<hash>.pdf` with `storage_reused=False` and exactly one stored file;
identical-bytes replay reusing the same path/hash with `storage_reused=True` and no second blob;
three-page physical page count; frozen result with the exact nine public fields; title fallback
from an uppercase-suffix filename preserving spelling/case; valid explicit metadata;
`TypeError` for non-str title/author/edition; 10 trim/empty/over-200 metadata families producing
the frozen 422 `validation_error`/`PDF metadata is invalid`/`{"field": ...}` with no raw value,
`__cause__ is None` and `__context__ is None`, and no storage root created; the 200-code-point
boundary accepted; all seven inspection reasons mapped to the exact frozen
code/status/message/details with no storage root created and no chained exception; a corrupt
existing blob raising the unchanged sanitized `source_storage_unavailable` (503) without being
overwritten; a recording spy proving `inspect_pdf` receives exactly the five inputs; a CAS spy
proving metadata validation precedes CAS and that success calls CAS with namespace
`sources/pdf`, suffix `.pdf` and the original bytes; `KeyboardInterrupt` from inspection,
`SystemExit` from a hostile `.strip()` during metadata access, and `SystemExit` from CAS all
propagate unchanged.

### 4. Invariants preserved

- Transaction-external preparation only: no authoritative SQL row, Job, HTTP request, worker,
  route or public API contract was added.
- Filename and metadata never influence a disk path; only the CAS digest does (namespace/suffix
  are fixed constants).
- No `BaseException` is caught; no parser/OS detail is exposed; no new error code was added; the
  existing inspection and CAS behavior is unchanged (their focused suites still pass untouched).
- No file outside the permitted edit boundary was modified.

### 5. Assumptions

- "Passing all five inspection inputs exactly" was implemented as
  `inspect_pdf(raw_bytes, filename=..., declared_media_type=..., max_bytes=..., max_pages=...)`.
- "Missing title" means `title is None`; an empty string is invalid metadata (1..200 rule), so it
  raises instead of defaulting.
- The derived default title is always valid because a validated PDF filename is 1..200 code
  points, has no surrounding whitespace and has a non-empty basename before `.pdf`; the suffix
  removal preserves the original spelling/case.
- `MemoryError` is an `Exception` and therefore propagates naturally (nothing catches it); the
  packet's mandatory BaseException propagation is proven with `KeyboardInterrupt`/`SystemExit`.
- The packet's `payload_too_large` details carry only `{"limit_bytes": max_bytes}` (the packet
  restricts `{"reason": ...}` to the "latter two" cases).

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` contains only the pre-existing tracked worktree
edits; `services/pdf.py` and `test_pdf_prepare.py` are new/untracked and were not added to the
index.

### 7. Status

**Pending Codex review.** 8A-2C1 is NOT marked complete; the 8A-2C2 SQL persistence/idempotency
core was NOT started, and no commit was created.

## DS-STAGE8A-PDF-PERSISTENCE-TESTS-01 completion (8A-2C2 tests)

### 1. Files changed

- `backend/tests/test_pdf_persistence.py` (new, 49 collected focused tests) — black-box tests
  for the Codex-owned frozen `PdfPersistenceService` in `services/pdf_persistence.py`.
- `docs/agent/HANDOFF.md` — this evidence.

No other file was touched. `services/pdf_persistence.py`, models, migrations, jobs, content,
schemas, routes, config, frontend, Makefile, dependencies, ADRs and all existing tests are
unchanged; all pre-existing worktree edits are preserved untouched. `git status --short`
confirms the only new worker file is `backend/tests/test_pdf_persistence.py` (untracked, not
added to the index).

### 2. Frozen behaviors proven (black-box, no private helpers asserted)

- `register_asset`: creates exactly one linked `Source(kind="book") → SourceVersion → SourceFile
  → PdfAsset`, copies prepared title/author/edition/filename/relative_path/media_type/size/hash/
  page metadata and returns `replayed=False`; the same content hash replays the original asset
  with `replayed=True`, creates no rows and keeps the first display metadata.
- Caller-owned transaction: faults at `source`/`source_version`/`source_file`/`pdf_asset` plus a
  normal caller `session.rollback()` leave zero rows in all four tables.
- `enqueue_extraction`: requires an existing asset and `1 <= first_page <= last_page <=
  page_count`; 404/422 rejection creates no run, Job or invalidation event.
- Canonical logical fingerprint covers content hash, pages, fixed pipeline version and the
  finite-JSON profile; object key order is irrelevant (replay); different pages or profiles
  create distinct runs/jobs; the Job payload owns a deep profile snapshot (caller mutation cannot
  change it). Non-dict profiles raise `TypeError`; non-finite/type-invalid profiles raise the
  frozen 422 `ServiceError` with no SQL writes.
- Without an Idempotency-Key the logical fingerprint is the effective key: exact replay returns
  the same run/job; the queued Job has kind `pdf_extraction`, status `queued` and the exact
  payload (schema version 1, deterministic `uuid5` run id, asset id, page range,
  `pdf-extraction:v1`, canonical profile), with one `job/queued` invalidation event.
- Explicit keys: 1..128 visible ASCII only, stored only as SHA-256; same key/same request
  replays; same key/different request returns the frozen `409 idempotency_conflict` with zero new
  rows; different keys for the same logical request create distinct runs/jobs sharing the
  logical fingerprint.
- Atomicity: faults at `job` or `extraction_run` roll back the run, Job and its invalidation
  event while the previously committed asset (and its source chain) is retained.
- Programmer type misuse for prepared/UUID/page ints/idempotency/profile raises the frozen
  `TypeError` messages; `ServiceError` code/status/message/details match the frozen strings.

### 3. Focused test count and every acceptance command result

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_persistence.py backend/tests/test_stage8_models.py
    → 56 passed (49 pdf persistence + 7 stage8 models)
uv run --project backend --locked ruff format --check backend/tests/test_pdf_persistence.py
    → 1 file already formatted
uv run --project backend --locked ruff check backend/tests/test_pdf_persistence.py
    → All checks passed
uv run --project backend --locked mypy backend/tests/test_pdf_persistence.py
    → BLOCKED environmentally (see escalation below)
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_pdf_persistence.py
    → Success: no issues found in 1 source file
git diff --check
    → clean
```

### 4. Escalation evidence: the frozen bare `mypy` command cannot pass in this environment

Reproduction: from the repository root, `uv run --project backend --locked mypy
backend/tests/test_pdf_persistence.py` exits 1 with six `[import-untyped]` errors
("Skipping analyzing 'chess_workbench.services.content' … module is installed, but missing
library stubs or py.typed marker").

Inspected files/hypothesis: `mypy -v` shows `Config File: Default` — there is no
`pyproject.toml` at the repository root and mypy only discovers `backend/pyproject.toml`
explicitly, so `mypy_path = "backend/src"` (which the project config sets) is never applied.
`chess_workbench` therefore resolves to the installed package inside `backend/.venv`
(runtime `import chess_workbench` resolves to `backend/src` via the editable install, which
mypy does not honor), and the missing `py.typed` marker triggers `import-untyped`.

Not caused by this packet: the identical bare command on the previously accepted
`backend/tests/test_pdf_prepare.py` fails with the same `import-untyped` errors, and the
repo-wide `make backend-typecheck` gate reports 6 errors in 3 pre-existing files outside this
packet's boundary (`test_pdf_inspection.py` unused `type: ignore`, Codex-owned
`services/pdf_persistence.py:234` `no-any-return`, `test_pdf_prepare.py` reexport `attr-defined`)
— none in `test_pdf_persistence.py`. With the project's configured invocation
(`--config-file backend/pyproject.toml`, the form used by `make backend-typecheck` and by
earlier accepted packets) the new test file is clean. No production/config file was edited and no
check was weakened. Blocking decision: the frozen command line appears to need
`--config-file backend/pyproject.toml` (or an equivalent `MYPYPATH`) to resolve the source tree;
Codex should confirm or amend the packet command.

### 5. Invariants preserved

- No production behavior was changed: the service, models, migrations, jobs, content/schemas and
  existing tests are byte-identical to the Codex-owned worktree state.
- Tests are deterministic, offline, use only a temporary SQLite `Database` +
  `Base.metadata.create_all` and directly constructed immutable `PreparedPdfAsset` values; no
  `data/books`, CAS, sleep/randomness or HTTP/network access.
- The packet's permitted edit boundary was respected exactly.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` shows only the pre-existing tracked worktree
edits; `backend/tests/test_pdf_persistence.py` is new/untracked and was not added to the index.

### 7. Status

**Pending Codex review** (one environmental mypy-invocation blocker escalated above; all 56
focused tests pass and Ruff/git gates are clean). 8A-3 was NOT started, and no commit was
created.

## Codex final review — Stage 8A-2 accepted (2026-08-11)

- Accepted `DS-STAGE8A-PDF-PREPARE-01` after actual-diff review and an independent 121-test run.
- Codex implemented `services/pdf_persistence.py`; V4-Flash supplied 49 black-box cases. Codex
  corrected the packet's mypy invocation, replaced random test UUIDs, fixed the strict-MyPy
  `Any` return and added one real bytes → inspection → CAS → SQL replay case.
- Final persistence/model gate: 57 passed (50 persistence/integration + 7 model). Focused Ruff,
  configured strict MyPy and `git diff --check` pass.
- No full repository acceptance, live provider call, user-book read or commit was performed.

## DS-STAGE8A-PDF-API-SCHEMAS-01 completion (8A-3A)

### 1. Files changed

- `backend/src/chess_workbench/schemas/jobs.py` (new, 30 lines) — canonical generic job read
  contract: `JobStatusValue` literal and `JobRead`, byte-for-byte unchanged from the engine
  module they were extracted from.
- `backend/src/chess_workbench/schemas/engine.py` — removed the `JobStatusValue` literal and the
  `JobRead` class; added `from chess_workbench.schemas.jobs import JobRead, JobStatusValue` plus
  `__all__ = ["JobRead", "JobStatusValue"]` so the old import path keeps working as a re-export.
  Nothing else in the module changed.
- `backend/src/chess_workbench/schemas/pdf.py` (new, 113 lines) — the eight frozen Stage 8A PDF
  contracts (see below).
- `backend/tests/test_pdf_schemas.py` (new, 29 focused tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file was touched. Services, models/migrations, routes/app, worker/jobs implementation,
contracts generator/output, config, dependencies, Makefile, frontend, ADRs and existing tests are
untouched; all pre-existing worktree edits are preserved.

### 2. Behavior and validators implemented

- `schemas/jobs.py` owns `JobStatusValue` and `JobRead` with the exact original fields
  (`id`, `kind`, `status`, `payload`, `result`, `attempt_count`, `max_attempts`,
  `cancel_requested_at`, `last_error_code`, `last_error_message`, `created_at`, `updated_at`).
  `engine.py` re-exports both names, so `engine.JobRead is jobs.JobRead` holds and the canonical
  `JobRead.model_json_schema()` is byte-identical to the pre-move shape (locked by a literal
  oracle captured before the move).
- `PdfAssetUploadMetadata(StrictContract)`: optional `title`/`author`/`edition`, each `Title`
  (strip + 1..200 code points), all defaulting to `None`.
- `PdfExtractionCreate(StrictContract)`: `pdf_asset_id: EntityId`, `first_page`/`last_page`
  integers `>= 1`, `profile: dict[str, JsonValue]` default `{}`; rejects `last_page < first_page`;
  profile values are recursively deep-copied into a caller-independent snapshot and any non-finite
  float (`NaN`/`Infinity`/`-Infinity`) at any nesting depth is rejected. No client hash/path/job
  status/idempotency fields exist.
- `PdfAssetRead(StrictContract)`: `id`, `content_sha256: Sha256`, positive `byte_size`,
  `page_count` 1..20,000, `source_id`/`source_version_id`/`source_file_id`, `filename: Title`,
  `title: Title`, optional `author`/`edition`, `created_at: UtcDateTime`. No relative/absolute
  path field is exposed (extra `path`-like keys are rejected by `extra="forbid"`).
- `PdfAssetEnvelope(StrictContract)`: `replayed: bool`, `asset: PdfAssetRead`.
- `PdfExtractionRead(StrictContract)`: `id`, `pdf_asset_id`, `first_page`/`last_page` with the
  same `>= 1` + page-order validation as create, non-empty `pipeline_version`, `profile` with the
  same finite/deep-copy validation, nested generic `job: JobRead`, `has_conflicts: bool = False`,
  `created_at: UtcDateTime`.
- `PdfExtractionEnvelope(StrictContract)`: `replayed: bool`, `extraction: PdfExtractionRead`.
- `PdfExtractionList(StrictContract)`: `items: list[PdfExtractionRead]`.
- All models inherit `extra="forbid"` and frozen behavior from `StrictContract`; UUID JSON strings
  and RFC3339 UTC strings (`Z`) round-trip through `model_validate_json` / `model_dump(mode="json")`.

### 3. Focused test count and every acceptance command result

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_schemas.py backend/tests/test_stage6_engine.py
    → 46 passed (29 new pdf schema tests + 17 existing stage 6 engine tests)
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
    → 4 files already formatted
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
    → All checks passed
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
    → Success: no issues found in 4 source files
git diff --check → clean
```

The 29 tests prove: exact field sets/defaults for every model; unknown-field rejection at every
nested boundary (top-level, nested `job`, nested `asset`/`extraction` in envelopes, list items,
and the absent client-supplied idempotency/hash/path keys); `Title` constraints on
title/author/edition/filename (empty, whitespace-only, 201 chars rejected; 200 accepted; strip);
`byte_size > 0` and `page_count` 1..20,000; reverse page range rejected on both create and read
with equal ranges allowed; recursive NaN/Infinity/-Infinity rejection (Python and JSON modes) and
acceptance of ordinary nested null/bool/int/finite-float/string/list/object values; deep
caller-independent profile snapshots; asset path absence (`relative_path`/`absolute_path`/
`storage_path`/`path` rejected as unknown); UTC/UUID JSON round trips including naive and
non-UTC timestamp rejection and non-UUID id rejection; nested Job status literal validation plus
nested-job unknown-field rejection; `has_conflicts` default and bool-field typing; immutable
frozen models; OpenAPI 3.0 conversion via `openapi_schema` with no dangling `$defs`/`#/$defs`/
`const` and the inlined nested job status enum; `engine.JobRead is jobs.JobRead` identity plus the
captured pre-move `JobRead` JSON Schema literal; and an AST import-boundary proof that `pdf.py` /
`jobs.py` import only `schemas.domain` / `schemas.jobs` (no SQLAlchemy, Sanic, services, api,
store or engine imports).

### 4. Invariants preserved

- Existing engine consumers see the same `JobRead` class/schema: `schemas.engine` re-exports the
  canonical `schemas.jobs` object (identity-proven in tests); `services/engine.py` and
  `api/engine.py` import paths are unchanged and were smoke-checked at runtime.
- No SQLAlchemy/Sanic/service/provider imports were introduced into any schema module.
- No route, SQL query, transaction, worker or frontend behavior was added; the contracts
  generator output was not regenerated or touched (8A-4 owns generated contracts).
- `StrictContract` conventions preserved: `extra="forbid"` + frozen; lax bool coercion for
  `replayed`/`has_conflicts` matches existing contract conventions (non-bool-coercible values
  still rejected).

### 5. Assumptions

- `id`/`source_id`/`source_version_id`/`source_file_id`/`pdf_asset_id` use the existing
  `EntityId` (`UUID`) alias; `content_sha256` uses the existing `Sha256` annotated type.
- "Owns, unchanged from `schemas.engine`" was implemented by moving the exact class/literal into
  `jobs.py` and re-exporting from `engine.py` (`__all__`), matching the packet's edit boundary
  wording and the focused identity oracle.
- The JSON Schema shape oracle is a literal captured from the pre-move `JobRead` in this
  worktree; it locks the "unchanged in shape" requirement against Pydantic 2.11 output.
- No client-provided idempotency key, hash or path field exists on the create contract; the
  explicit-key idempotency contract belongs to the 8A-3 route/service layer, not these schemas.
- `pipeline_version` uses `NonEmptyText` (strip + min 1) as the "non-empty" constraint.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` shows only the pre-existing tracked worktree edits
(Codex-owned: delegate skill, PLANS.md, 8P extraction files, 8A-1/8A-2 files, and the 8A-2C2
handler-scoped `allowed_kinds` claiming changes in `services/jobs.py`, `services/worker.py` and
`test_stage6_jobs.py` — the last three are content-verified as Codex work whose mtimes predate
this session; they were not modified by this worker) plus the `schemas/engine.py` re-export;
`schemas/jobs.py`, `schemas/pdf.py` and `test_pdf_schemas.py` are new/untracked and were not
added to the index.

### 7. Status

**Pending Codex review.** 8A-3A is NOT marked complete; 8A-3B (routes + idempotent enqueue) and
8A-4 (Sources UI / acceptance) were NOT started, and no commit was created.

## DS-STAGE8A-PDF-API-TESTS-01 completion (8A-3C)

### 1. Files changed

- `backend/tests/test_pdf_api.py` (new, 834 lines, 11 collected tests) — deterministic
  black-box HTTP tests for the frozen Stage 8A PDF routes.
- `docs/agent/HANDOFF.md` — this evidence.

No other file was edited. Production code was read-only: routes (`api/pdf.py`), services
(`pdf.py` / `pdf_persistence.py` / `jobs.py` / `worker.py`), schemas, models, migrations,
config, existing tests and all pre-existing worktree edits are untouched. Concurrent Codex
work regenerated `backend/openapi.json`, `frontend/src/logic/api/client.ts`,
`frontend/src/logic/api/types.ts` and `frontend/src/types/api.generated.ts` at 15:43–15:44
(during this session; none of my commands write those files); those edits are preserved
untouched and were not caused by this packet.

### 2. Frozen behaviors proven (black-box, no private helper asserted)

- Isolated app per test: temporary SQLite + storage root, `engine_worker_enabled=False`, a
  small explicit `pdf_max_bytes`, `Base.metadata.create_all`; only tiny deterministic in-memory
  `pypdf` PDFs; no `data/books`, network, provider, sleep, randomness, subprocess or
  private-helper assertion. Every `Database` is closed.
- `POST /api/pdf-assets`: exactly one multipart `file` + optional strict JSON `metadata`;
  valid PDF → 201, `Idempotency-Replayed: false`, canonical `Location`, envelope with exact
  read-model key set (page count, source/version/file IDs, first metadata, no relative or
  absolute path anywhere in the body), CAS blob at exactly
  `sources/pdf/<sha256[:2]>/<sha256>.pdf` (bytes equal, mode 0600, exactly one file). Same
  bytes with a different filename/metadata → 200 replay `true`, same ids, first display
  metadata and filename retained; exactly one PdfAsset/Source/Version/File/blob.
- `GET /api/pdf-assets/{id}` returns the byte-equal read model from the upload envelope;
  `GET /api/pdf-assets` discovers persisted assets in the persistence order
  (`created_at desc, id` — asserted against the DB, so ties are deterministic) and exposes no
  path; missing UUID → stable 404 `not_found`.
- `POST /api/pdf-extractions`: new valid physical range → 202, replay → 200, exact
  `Location`/`Idempotency-Replayed`; the run id is asserted to equal the frozen deterministic
  `uuid5` (computed in-test from asset hash + pages + `pdf-extraction:v1` + finite profile);
  nested `Job` is exact (`pdf_extraction`, `queued`, attempt 0, max_attempts 3, null
  cancel/error/result, exact payload `schema_version 1`, run/asset ids, pages, pipeline,
  profile). Explicit same key + different profile and same key + different pages → 409
  `idempotency_conflict` with zero new run/job/event rows; same key + same request replays.
  Missing asset → 404; reverse range / out-of-range / zero page → 422 with the frozen
  `PDF page range is invalid` details and zero new run/job/event rows.
- GET-one and list expose identical run/job state. `status=queued` and `has_conflicts=false`
  include the queued runs; `has_conflicts=true` and every other valid status
  (`running/succeeded/failed/cancelled`) exclude them; unknown/duplicate/non-lowercase status
  and duplicate/non-lowercase/invalid conflict booleans → 422 `validation_error`. No progress
  is invented. Missing run → stable 404.
- An engine `SqlWorker` (default registered handler) `run_once()` returns `False` when only
  the queued `pdf_extraction` job exists; the job stays `queued` with `attempt_count == 0` and
  no error.
- Transport/validation rejection, each with stable code/status and zero authoritative rows and
  zero CAS files: non-multipart media → 415; missing file / duplicate file → 422
  (hand-crafted multipart bodies used for the missing-file and duplicate-metadata cases,
  because the ASGI httpx client cannot express them natively); unknown part → 422; duplicate /
  invalid / unknown metadata → 422; fake PDF → 422 `PDF upload is invalid` `reason
  invalid_pdf`; declared non-PDF MIME → 415; payload over `pdf_max_bytes` → 413
  `payload_too_large` with `{"limit_bytes": 512}`. No error body contains the storage root
  absolute path, raw payload bytes or parser text.
- Request-cap rule: with `pdf_max_bytes=512` the app keeps Sanic's pristine default cap
  (asserted against a bare `Sanic` oracle) and is always `>= pdf_max_bytes + 1 MiB`; with a
  200 MiB `pdf_max_bytes` the cap is exactly `pdf_max_bytes + 1 MiB`.
- No Course or KnowledgeNote row is created by upload or enqueue.

### 3. Focused test count and every acceptance command result

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_api.py backend/tests/test_stage6_jobs.py
    → 25 passed (11 pdf_api + 14 stage6 jobs)
uv run --project backend --locked ruff format --check backend/tests/test_pdf_api.py
    → 1 file already formatted
uv run --project backend --locked ruff check backend/tests/test_pdf_api.py
    → All checks passed
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_pdf_api.py
    → Success: no issues found in 1 source file
git diff --check → clean
```

(The packet's mypy command already carries `--config-file backend/pyproject.toml`, the form
Codex standardized in 8A-2C2.)

### 4. Invariants preserved

- Production code was not modified; all frozen route/service/schema/worker behavior matched
  the packet exactly on first probe (no mismatch to report).
- Tests are deterministic, offline and self-contained; fixed UUIDs only where the
  implementation is deterministic (run id via the public fingerprint/uuid5 construction);
  no sleeps, randomness or private helpers.
- Every `Database` is closed; `git diff --check` is clean.

### 5. Assumptions

- "Missing file" and "duplicate metadata" multipart cases are constructed by hand as raw
  multipart bodies because the ASGI httpx client cannot express them natively (empty
  `files={}` encodes as urlencoded → hits the 415 media-type boundary first).
- "Newest-first" asset/run ordering is asserted against the actual persistence order
  (`created_at desc, id`), so timestamp ties are handled deterministically without sleeps.
- The pristine Sanic request cap is obtained from a bare `Sanic("…", configure_logging=False)`
  instance rather than a hardcoded constant, keeping the oracle robust to Sanic upgrades.
- The unknown-status 422 case uses `status=bogus`; `status=queued` is a valid filter and is
  asserted as including the queued runs.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. The tracked diff contains only the pre-existing worktree edits
plus the concurrent Codex contract regeneration (`backend/openapi.json` and the three
frontend generated files); `backend/tests/test_pdf_api.py` is new/untracked and was not added
to the index.

### 7. Status

**Pending Codex review.** 8A-3C is NOT marked complete; 8A-4 (Sources UI / cumulative Stage 8A
gate) was NOT started, and no commit was created.

## DS-STAGE8A-ACCEPTANCE-WIRING-01 completion (8A-4B)

### 1. Files changed

- `Makefile` — added `acceptance-stage-8p` and `acceptance-stage-8a` to `.PHONY` and added the
  two cumulative targets after `acceptance-stage-6`. `acceptance: acceptance-stage-6` is
  untouched.
- `backend/tests/test_acceptance_wiring.py` — extended (117 lines added): two module-level suite
  constants, a `_pytest_lines` helper and six new deterministic text-level tests. No existing
  assertion was loosened.
- `docs/agent/HANDOFF.md` — this evidence (append only).

No other file was touched. All pre-existing worktree edits (8P extraction files, 8A-1/2/3 files,
Sources UI, generated contracts, delegate skill, ADR 0010/0011/0012, etc.) are preserved
untouched.

### 2. Exact target design implemented

- `.PHONY` now lists both names.
- `acceptance-stage-8p: acceptance-stage-6a` — one no-coverage pytest invocation
  (`-o addopts=''`, no `--cov`) over exactly these suites, in this order:
  `test_extraction_contract.py`, `test_extraction_provider.py`, `test_extraction_deepseek.py`,
  `test_extraction_decoder.py`, `test_extraction_validation.py`, `test_ccef_consumer_proof.py`;
  then `@test -s` non-empty assertions for `docs/decisions/0010-portable-ai-extraction-contract.md`,
  `docs/architecture/ccef-v1.md` and `contracts/chess-content-extraction-v1.schema.json`.
- `acceptance-stage-8a: acceptance-stage-8p bootstrap-frontend` — recipe order exactly as frozen:
  `$(MAKE) backend-static`, one no-coverage pytest invocation over exactly
  `test_source_storage.py`, `test_pdf_prepare.py`, `test_pdf_inspection.py`,
  `test_stage8_models.py`, `test_pdf_persistence.py`, `test_pdf_schemas.py`, `test_pdf_api.py`,
  `test_stage6_jobs.py` (in this order), `$(MAKE) backend-migration-check`, `@test -s`
  `docs/decisions/0012-stage-8a-pdf-assets-and-extraction-runs.md`, `$(MAKE) check-contracts`,
  `$(MAKE) frontend-format frontend-lint frontend-typecheck`, and
  `$(PNPM) --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx --coverage=false`.
- `acceptance: acceptance-stage-6` is unchanged (8A remains an AI-import milestone, not the
  stable CI stage).

### 3. Wiring tests added (text-level only, no Make recursion)

1. `test_stage_8_make_targets_are_cumulative` — exact prerequisites (`8p → 6a`; `8a → 8p +
   bootstrap-frontend`).
2. `test_stage_8_targets_are_declared_phony` — both names inside the `.PHONY` block.
3. `test_stage_8p_recipe_runs_exactly_the_portable_boundary_suites` — exactly one no-coverage
   pytest line carrying exactly the six 8P suites in order, plus the three `@test -s` doc/Schema
   assertions.
4. `test_stage_8a_recipe_runs_exactly_the_8a_suites_and_commands` — exactly one no-coverage
   pytest line carrying exactly the eight 8A suites in order, plus every required command
   (`backend-static`, `backend-migration-check`, ADR 0012 `@test -s`, `check-contracts`,
   `frontend-format frontend-lint frontend-typecheck`, WorkbenchPages vitest `--coverage=false`)
   in the frozen order.
5. `test_stage_8a_recipe_inherits_the_portable_boundary_gate` — none of the six portable suite
   paths appear in the 8A recipe (inherited via `acceptance-stage-8p`).
6. `test_acceptance_stable_entry_remains_stage_6_and_excludes_stage_8` — the `acceptance` target
   still points exactly at `acceptance-stage-6` (whose verify/smoke/stage6_e2e recipe is intact)
   and references no 8P/8A target.

### 4. Focused oracle results (run exactly as the packet commands them)

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_acceptance_wiring.py                    → 13 passed
uv run --project backend --locked ruff format --check backend/tests/test_acceptance_wiring.py
                                                             → 1 file already formatted
uv run --project backend --locked ruff check backend/tests/test_acceptance_wiring.py
                                                             → All checks passed
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_acceptance_wiring.py                    → Success: no issues found in 1 source file
git diff --check                                             → clean
```

Bonus sanity (not part of the oracle): `make -n acceptance-stage-8p` and
`make -n acceptance-stage-8a` dry-runs exit 0 and print the expected recipe chain, proving the
Makefile parses and both targets resolve. No recipe was executed. The packet forbids running Make
recursively from pytest; the tests only read the Makefile text.

### 5. Invariants preserved

- Production behavior, dependencies/locks, generated contracts, migrations, frontend, ADRs and
  PLANS.md are untouched; only the two boundary files plus this HANDOFF changed.
- `acceptance: acceptance-stage-6` and the whole Stage 2–6 cumulative chain are unchanged.
- All pre-existing worktree edits (Codex-owned and prior packets) are preserved exactly.
- No commit was created; 8B and the focused 8A closeout run were not started.

### 6. Assumptions

- `acceptance-stage-8a` uses `$(PNPM)` (the Makefile's resolver variable) rather than the literal
  `pnpm`, matching the established `acceptance-stage-4a`/`6b` pattern; the packet names the vitest
  invocation by file and `--coverage=false` flag, which are present verbatim.
- The `acceptance:` target has no recipe (it is a prerequisites-only line at EOF), so the
  stable-entry test asserts its exact prerequisite, its own line content, and the intact
  `acceptance-stage-6` recipe instead of `_target_recipe` on a recipe-less target.
- `--cov` absence plus `-o addopts=''` is asserted as the "no-coverage" evidence for both pytest
  invocations.

### 7. Status

**Pending Codex review.** 8A-4B is NOT marked complete; the focused 8A closeout run and Stage 8B
were NOT started, and no commit was created.

## DS-STAGE8B-EVIDENCE-PORTS-01 completion (8B-1)

### 1. Files changed

- `backend/src/chess_workbench/extraction/evidence.py` (new, 403 lines) — strict, side-effect-free
  evidence values and renderer/OCR ports frozen by ADR 0013: boxes, fragments, render profile,
  rendered page, OCR request/result, source-evidence hashing, Protocols, the stable error model and
  the deterministic scripted OCR fake.
- `backend/src/chess_workbench/extraction/__init__.py` — exports from the new module only: one
  `from .evidence import (...)` block and the matching `__all__` entries. Nothing else in the file
  was touched (all pre-existing decoder/provider/lazy-export lines are prior-packet work).
- `backend/tests/test_extraction_evidence.py` (new, 877 lines, 61 collected tests).
- `docs/agent/HANDOFF.md` — this evidence (append only).

No other file was touched. Contracts/decoder/provider/validation, SQL/models/migrations,
services/worker/config, dependencies/lock, routes/OpenAPI, frontend, ADRs, Makefile, existing tests
and this plan are untouched; the pre-existing worktree edits are preserved byte-for-byte.

### 2. Behavior and validators implemented

- `_StrictModel` base: `extra="forbid"`, `strict=True`, `frozen=True` at every object boundary.
- `EvidenceOrigin = Literal["embedded_text", "ocr"]`.
- `NormalizedBox`: finite strict floats `x0..y1` in `0..1` (explicit finite AfterValidator plus
  bounds), `x0 < x1` and `y0 < y1` enforced by a model validator; integer JSON numbers accepted.
- `PixelBox`: strict nonnegative ints (bool rejected), `x0 < x1` / `y0 < y1`.
- `TextFragment`: `order` 0..19,999 (bool rejected), whitespace-preserving `text` (empty and
  whitespace-only rejected, 1..100,000 code points), `box: PixelBox`, optional confidence as finite
  strict float 0..1. Embedded vs OCR confidence rules are enforced by the containing models.
- `RenderProfile`: exact defaults (`dpi=150`, `max_side_px=10000`, `max_pixels=40000000`,
  `max_png_bytes=67108864`, `embedded_text_min_chars=32`); strict positive ints, dpi 72..600, bools
  rejected.
- `RenderedPage`: physical page >=1, positive width/height, dpi 72..600, nonempty `png_bytes` up to
  64 MiB preserved exactly, ordered `embedded_fragments`, trimmed nonempty renderer name/version
  (max 100). Validators enforce contiguous unique fragment orders from zero, boxes inside
  width/height, total fragments <=20,000, `width*height <= 40,000,000` and null confidence for all
  embedded fragments.
- `OcrRequest`: same physical page/width/height/png constraints, trimmed `language` max 64
  (default `""`), and `profile: dict[str, JsonValue]` (default `{}`) that recursively rejects
  non-finite values and deep-copies the caller's dict at construction (caller mutation cannot reach
  the model).
- `OcrPageResult`: matching physical page and positive dimensions, ordered OCR-only fragments with
  the same order/count/box-bounds rules plus a required confidence per fragment, trimmed nonempty
  engine name/version (max 100).
- `SourceEvidenceFragment`: physical page, normalized box, preserved text, origin, origin/confidence
  rule (OCR requires confidence, embedded requires null), trimmed engine name/version and lowercase
  64-hex `fragment_sha256`. A model validator recomputes SHA-256 over the compact sorted-key UTF-8
  JSON array `[physical_page,[x0,y0,x1,y1],text,origin,engine_name,engine_version]` (the model's
  JSON numeric values) and rejects any mismatch. The pure `source_fragment_sha256(...)` helper uses
  the identical canonicalization (`ensure_ascii=False, sort_keys=True, separators=(",", ":")`).
- Runtime-checkable `PdfPageRenderer` Protocol (sync `render_page(pdf_bytes, physical_page,
  profile) -> RenderedPage`) and `OcrAdapter` Protocol (async `recognize(request) -> OcrPageResult`).
- `PdfEvidenceError(RuntimeError)`: public `code`/`message`/`retryable`, `str(error) == message`,
  `__deepcopy__`-safe, holds no raw content/path/provider-body attribute; constructor validates a
  non-empty string code/message and an actual bool retryable.
- `ScriptedOcrAdapter`: accepts a nonempty finite iterable of `OcrPageResult | PdfEvidenceError`
  (invalid outcomes raise `TypeError` naming the index, empty raises `ValueError`), deep-copies
  outcomes at construction, consumes FIFO, deep-snapshots every request, returns/raises deep copies,
  exposes a deep-copied immutable `calls` tuple and nonnegative `remaining`, and raises
  `AssertionError` on exhaustion. No sleep/I/O.
- Import purity: the module imports only the standard library and Pydantic (proved by a standalone
  subprocess load and a source-token check).

### 3. Focused test count and every acceptance command result

```text
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_evidence.py
    → 61 passed
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
    → 3 files already formatted
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
    → All checks passed
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
    → Success: no issues found in 3 source files
git diff --check → clean
```

The 61 tests cover: positive/negative constraints for every model; nested unknown-field rejection;
strict bool/string/coercion rejection (including tuple-list and tuple-dict boundaries); integer JSON
numbers accepted by strict floats; NaN/Infinity recursion in `profile`; order/bounds/count limits
(0..19,999 orders, 20,000-count rule, 64 MiB png, 40,000,000 pixel area, 100,000 code points);
exact bytes/text preservation; contiguous-unique-from-zero ordering; pixel boxes inside
width/height; embedded-null vs OCR-required confidence rules; frozen-model immutability; exact
render profile defaults; JSON round trips where bytes are not involved; canonical hash
stability/content-bound/mismatch/non-ASCII-verbatim and 64-hex format; error fields/string form/
constructor validation/deepcopy safety/no raw attribute; Protocol positive/negative runtime checks
plus static conformance assignments; scripted FIFO success/error-then-success/exhaustion/empty-and-
invalid-outcome rejection/generator iterable/request snapshot isolation/result copy isolation/
construction-time deep copy/calls-tuple mutation isolation; standalone import purity; package export
identity. No snapshots, filesystem, network, clock or randomness.

Bonus sanity (not part of the packet oracle): the pre-existing contract/provider suites still pass
after the shared `__init__.py` change — 73 passed (`test_extraction_contract.py` +
`test_extraction_provider.py`).

### 4. Invariants preserved

- The module's own frozen strict base is used; CCEF contracts are never imported (identity-proven by
  the import-purity subprocess and the `ExtractionPackage`-token check).
- No chess, HTTP, SQL, Sanic, filesystem, subprocess or provider/consumer import exists in
  `evidence.py`; no behavior outside the packet boundary was added (no rendering, OCR invocation,
  file/CAS I/O or Job handler).
- Only the four permitted boundary files were touched; all pre-existing worktree edits are
  preserved exactly; no commit was created.
- Unknown fields and Python coercions are rejected at every boundary; accepted bytes and text are
  preserved verbatim.

### 5. Assumptions and interface ambiguity

- "OCR fragments require confidence; embedded fragments require null" is enforced at the containing
  model level (`OcrPageResult`/`RenderedPage`), because `TextFragment` itself has no `origin` field;
  the origin-specific rule also lives on `SourceEvidenceFragment`.
- "matching physical page" for `OcrPageResult` is interpreted as the result carrying its own
  physical page >=1 consistent with its own fragments/dimensions; cross-request match validation is
  impossible inside a standalone model and was not invented.
- The `width*height <= 40,000,000` and fragment-order rules are applied to `RenderedPage` (explicit
  in the packet); `OcrRequest`/`OcrPageResult` enforce only the "same physical page/width/height/png
  constraints" and "same order/count/box bounds" wording, which names no pixel-area cap.
- `OcrRequest.language` is optional and defaults to `""` ("trimmed language max 64" does not demand
  non-empty).
- Strict Pydantic floats accept integer JSON numbers (e.g. confidence `0` becomes `0.0`), matching
  the 8P-1 R1 precedent; `png_bytes`/strict bytes do not round-trip through JSON mode (base64 would
  be rejected), so JSON round-trip tests cover only bytes-free models.
- Frozen models raise `ValidationError` on attribute assignment in Pydantic 2.13 (not `TypeError`);
  runtime-checkable Protocols cannot detect signature mismatches via `isinstance`, so negative
  protocol tests use classes that lack the method and exact signatures are enforced by mypy via
  static conformance assignments.
- The scripted fake records the exhausting call in `calls` before raising `AssertionError`, matching
  the accepted provider-fake accounting.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. The tracked diff contains only the pre-existing worktree edits plus the
evidence `__init__.py` exports; `evidence.py` and `test_extraction_evidence.py` are new/untracked
and were not added to the index.

### 7. Status

**Pending Codex review.** 8B-1 is NOT marked complete; 8B-2 (PDFium renderer) was NOT started, and
no commit was created.
## Codex Stage 8A closeout and Stage 8B-1/8B-2 acceptance (2026-08-11)

- Stage 8A is accepted. The cumulative run proved real MySQL compatibility, migration
  upgrade/head-check/downgrade, 294/294 portable extraction tests, 232/232 PDF/backend tests,
  generated-contract drift, frontend format/lint/typecheck and 12/12 Sources page tests. Two
  deterministic closeout-only issues were fixed: Ruff import order and test mock typing.
- Added `acceptance-stage-8p` and `acceptance-stage-8a`; their wiring tests pass 13/13. Stable CI
  deliberately remains `acceptance-stage-6` until the complete AI-import stage is accepted.
- ADR 0013 now owns Stage 8B rendering/OCR/source-evidence boundaries. It selects permissively
  licensed PDFium via `pypdfium2`, keeps PaddleOCR behind a replaceable local adapter and forbids
  8B from creating formal SourceSpan/Course/Knowledge rows.
- Accepted `extraction/evidence.py` after Codex added the missing shared 40,000,000-pixel guard to
  OCR requests/results. Focused evidence gate: 61/61, Ruff and MyPy clean.
- Added and locked `pypdfium2==5.12.1` and Pillow 12.3.0. Codex implemented
  `PdfiumPageRenderer`: in-memory physical-page rendering, deterministic RGB PNG, embedded-text
  rectangles, strict side/pixel/PNG limits, sanitized errors and explicit resource cleanup.
  Renderer+evidence gate: 77/77; focused Ruff/MyPy and `uv lock --check` pass.
- The V4-Flash renderer packet was terminated because it created `.tmp_pdfium_probe.py` outside
  its permitted boundary. No worker implementation file existed at termination; Codex wrote the
  accepted renderer from scratch. The harmless untracked probe remains only because agents lack
  deletion permission; it is not imported by production/tests.
- No commit was created. Next work is Codex design of the exact PaddleOCR recorded-JSON and local
  runner protocol, followed by a bounded V4-Flash 8B-3 packet.

## Codex Stage 8B-3 PaddleOCR adapter acceptance (2026-08-11)

- Added `extraction/paddleocr.py` with the versioned local-runner protocol
  `chess-workbench/paddleocr-runner/1`. Its pure normalizer accepts only the strict PaddleOCR 3.x
  `rec_texts`/`rec_scores`/`rec_polys` subset, binds page and pixel dimensions to the request,
  preserves text/order/confidence, converts four-point polygons to bounded axis-aligned boxes and
  maps every malformed result to sanitized non-retryable `ocr_invalid_output`.
- Added final `PaddleOcrJsonAdapter`. It snapshots bounded argv, never invokes a shell, sends one
  canonical JSON/base64-PNG request through stdin, uses a controlled temporary working directory,
  streams stdout/stderr through independent byte limits, enforces one whole-operation timeout and
  kills/reaps on timeout, overflow and cancellation. Stable public mappings cover unconfigured or
  failed spawn, timeout, nonzero/pipe failure, oversized output and invalid JSON without exposing
  stderr, paths, OCR text or parser details.
- Added package exports and `test_paddleocr_adapter.py`. The focused runner tests use only the
  current Python executable as a deterministic local fixture; no PaddlePaddle, model, network,
  book PDF, SQL, worker or API is invoked.
- V4-Flash delegation was stopped after about one minute: it had consumed roughly 110,000 tokens
  repeatedly inspecting existing tests and had made no implementation change. Codex completed the
  item directly; no out-of-bound product file was created by this run.
- Verification: `test_paddleocr_adapter.py` 39/39 passed; adapter plus accepted evidence suite
  100/100 passed; focused Ruff format/check and MyPy passed; `git diff --check` clean.
- No commit was created. Stage 8B-3 is accepted. Next work is Codex design of 8B-4 immutable
  evidence artifacts and the existing `pdf_extraction` Job handler; it has not started.

## Codex Stage 8B-4 immutable evidence handler acceptance (2026-08-11)

- Added a bounded verified CAS reader: canonical contained server path only, regular non-symlink
  file, exact stat size, bounded chunk read, concurrent-mutation signal and exact SHA-256. Every
  filesystem/integrity failure maps to sanitized `source_storage_unavailable` with no path or OS
  exception context.
- Added `services/pdf_extraction.py`. It strictly binds the Job payload to the persisted
  run/asset/source file, rereads and verifies the PDF outside transactions, renders only the
  requested physical pages, chooses embedded text at the configured threshold or calls OCR once,
  normalizes top-left bboxes and writes deterministic UTF-8/sorted/compact/newline JSON plus PNGs
  to `derived/extraction` CAS.
- Per page it writes one `rendered_page` and one `ocr_fragment` index (the historical kind name
  contains either `embedded_text` or `ocr` origin), then run-level `render_manifest` and
  `ocr_manifest`. Empty pages record `empty_page`; the run cap is 200,000 fragments. No Course,
  KnowledgeNote or formal SourceSpan is written.
- Artifact registration happens only after all blobs exist, in one short transaction locking the
  run row. Identical slots replay without new rows; any path/hash/size/media difference raises
  `artifact_conflict` without overwrite or partial rows. Retry reuses CAS; user cancellation rolls
  back registration and may leave only permitted unreferenced blobs.
- Added migration `20260811_0011`: drops global `relative_path` and `(run, kind, hash)` uniqueness.
  Those constraints incorrectly rejected legitimate content-address reuse when pages/runs produce
  identical bytes. Logical `(kind,page)` uniqueness is serialized by the sole registration
  service. ADRs 0012/0013 record the correction.
- The API lifecycle now registers `pdf_extraction` whenever the existing worker switch is enabled;
  Stockfish availability only controls the engine handler. Optional server-owned
  `paddle_ocr_runner_path` configures real scanned-page OCR; Job profile cannot provide argv.
- Added focused handler tests for embedded/OCR/empty pages, canonical manifests, same-PNG CAS
  reuse, replay, corruption, conflict, retry-to-success, compact Job result and running
  cancellation. Updated the pre-existing model/migration expectations for CAS sharing.
- DeepCode did not report insufficient balance. It was terminated after about one minute for the
  prior repeated-reading pattern (nearly 100,000 tokens and no implementation edit), so the user's
  balance-exhaustion stop rule was not triggered. Codex handled the architecture-sensitive work.
- Focused verification is green: Ruff, MyPy, CAS/handler/Job/model/migration/config/lifecycle tests
  and `git diff --check`. No live OCR, network, user book PDF or cumulative Stage gate was run.
- No commit was created. Stage 8B-4 is accepted; 8B-5 has not started.

## DS-STAGE8B-SOURCES-EVIDENCE-01 completion (8B-5 Sources evidence display)

### 1. Files changed

- `frontend/src/app/SourcesPage.tsx` — added the evidence summary block inside each extraction
  run row (presentational only; no imports, hooks, backend, types or other files touched).
- `frontend/src/app/WorkbenchPages.test.tsx` — added three focused tests (append only; all
  pre-existing tests untouched).
- `docs/agent/HANDOFF.md` — this evidence (append only).

No other file was edited. Generated API types, backend/OpenAPI, `PLANS.md`, Makefile,
dependencies, other frontend components/tests and all Stage 8C code are read-only and untouched;
all pre-existing worktree edits (8A/8B Codex work, delegate skill, contracts, etc.) are preserved.

### 2. Behavior implemented (frozen backend contract is read-only)

- The generated `PdfExtraction` type exposes the frozen `evidence` field
  (`PdfEvidenceSummary | null` with `status/page_count/fragment_count/warning_count/
  render_manifest_sha256/ocr_manifest_sha256`), so no type/client change was needed.
- When `run.evidence` is non-null, one summary renders under that run with the exact text
  `已提交证据：{page_count} 页 · {fragment_count} 个文本片段 · {warning_count} 个警告`, followed on
  the next line by `Manifest 已提交` plus the two safely shortened identifiers
  `渲染 {first 12 chars}…` and `OCR {first 12 chars}…` (via `slice(0, 12)`). No path, full opaque
  payload, raw Job result or requested-page-range derivation is shown.
- When Job status is `succeeded` but `evidence` is null, the run renders the warning
  `证据索引尚未完整提交`; no evidence/manifest completion is claimed.
- Queued/running/failed/cancelled runs with null evidence add no evidence-completion text.

### 3. Focused test count and every acceptance command result

```text
pnpm --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx --coverage=false
    → 15 passed (12 pre-existing + 3 new; new tests use API-shaped fixtures,
      no console or timer mocks)
pnpm --dir frontend exec prettier --check src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
    → All matched files use Prettier code style!
pnpm --dir frontend exec eslint src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
    → clean (no output, exit 0)
pnpm --dir frontend exec tsc --noEmit
    → clean (no output, exit 0)
git diff --check
    → clean
```

New tests: committed summary with exact counts (5 页 / 12 个文本片段 / 1 个警告) and shortened
hashes (`渲染 aaaaaaaaaaaa…`, `OCR bbbbbbbbbbbb…`), proof the summary uses evidence counts rather
than the requested 319..399 range (`queryByText(/已提交证据：81 页/)` is null); incomplete-success
warning (`证据索引尚未完整提交`) with no `已提交证据：`/`Manifest 已提交`; and absence of any
false completion claim on queued/failed rows while the existing status labels and error message
(`排队中`, `已失败`, `OCR 服务不可用`) still render.

### 4. Invariants preserved

- Upload, extraction creation, filters, SWR polling (2 s while queued/running), source cards,
  status/error/conflict display and every existing Chinese label are unchanged.
- No client-side progress or count is inferred; only `run.evidence` values are displayed.
- Backend contract, artifact rules and lifecycle are read-only; no API/lifecycle/backend/Stage 8C
  change was necessary (the generated type already exposes the frozen fields).

### 5. Assumptions

- The manifest line renders `Manifest 已提交` as its own text node followed by `渲染 {12}…` and
  `OCR {12}…` nodes in a wrapping flex row, so each required visible string is individually
  assertable and no invented separator text is required by the packet.
- The incomplete-success warning is shown for any `succeeded` run whose `evidence` is null,
  including a `succeeded` run that has no evidence at all.

### 6. `git diff --stat` / `git diff --check`

`git diff --check` is clean. `git diff --stat` for the two boundary files shows the accumulated
uncommitted 8A-4A Sources UI work plus this packet's additions (`git diff` is against the pre-8A
baseline); the new evidence lines are the only additions beyond the pre-existing worktree state.

### 7. Status

**Pending Codex review.** This packet is complete and stays within its permitted edit boundary;
8B-5 acceptance wiring and the cumulative `acceptance-stage-8b` composition were NOT started, and
no commit was created.

## Codex Stage 8B-5 and Stage 8B closeout (2026-08-11)

- Accepted the delegated Sources evidence display after inspecting its actual diff and
  independently rerunning all five packet commands. DeepCode completed normally and did not report
  exhausted balance, credit or quota.
- Added the typed `PdfEvidenceSummary` API field. It is non-null only for a succeeded Job whose
  compact result binds to the same run and whose complete per-page render/evidence indexes plus
  both manifest indexes are committed with matching manifest hashes. Incomplete or inconsistent
  artifact sets return `evidence: null`; storage paths remain private.
- Extraction reads now snapshot the run's immutable artifact indexes. The Sources page renders
  exact committed page/fragment/warning totals and shortened manifest hashes; a succeeded Job with
  no verified summary displays `证据索引尚未完整提交` rather than a false completion claim.
- Regenerated `backend/openapi.json` and `frontend/src/types/api.generated.ts`. Contract drift
  check performs two fresh generations and is clean.
- Added `acceptance-stage-8b` as a deliberately focused, non-cumulative gate. It does not inherit
  8A/8P/Stage 6, `verify` or `smoke`, and does not call a real book, OCR model, provider or network.
- Final focused acceptance: 220/220 backend tests, Ruff format/check and MyPy on the eight owning
  modules, generated-contract drift, Prettier/ESLint/TypeScript, and 15/15 Sources page tests all
  pass. Acceptance wiring itself passes 14/14; `git diff --check` is clean.
- No commit was created and `.tmp_pdfium_probe.py` remains untouched. Stage 8B is complete. Stop
  before Stage 8C until the user explicitly continues.

## Codex Stage 8C architecture and 8C-1 prompt builder (2026-08-11)

- Added ADR 0014. New AI runs will use `pdf-extraction:v2`, keeping one Job as the only lifecycle
  truth across 8B evidence and 8C candidates; existing successful v1 runs remain immutable.
- Official DeepSeek documentation was checked: V4 Flash is text-only, with 1M context, up to 384K
  output and JSON Output. Stage 8C therefore uses one whole-range text request by default and does
  not silently split chapters or pretend the model saw page PNGs. Unsupported diagrams remain
  unresolved/review evidence for a future vision adapter.
- Added pure `extraction/prompting.py`: strict frozen page/fragment/context models, exact page-range
  coverage, UTC and strict-type validation, deterministic compact Unicode JSON, fixed CCEF schema
  request, prompt-injection isolation, and pre-provider fragment/text/prompt limits. An 81-page
  319..399 input creates exactly one system plus one user message and one provider request.
- Limits are 200,000 fragments, 1,500,000 source-text code points and a caller cap up to 2,000,000
  combined prompt code points. Inputs over a limit return sanitized `input_too_large`; mutated or
  inconsistent evidence returns sanitized `invalid_evidence`.
- The V4-Flash delegation was terminated after about two minutes at roughly 126,000 tokens because
  it stayed in the same reading/reasoning cycle and created no implementation file. It did not
  report exhausted balance, credit or quota. Codex completed the already-designed pure module;
  no out-of-bound product file was created.
- Focused verification: prompting 22/22 plus existing provider 28/28 = 50/50 passed; focused Ruff,
  MyPy and `git diff --check` are clean. No PDF, network, provider call, model quota or SQL was used.
- No commit was created; `.tmp_pdfium_probe.py` remains untouched. 8C-1 is accepted. Next is 8C-2
  trusted metadata binding, canonical raw/normalized CCEF codec and deterministic conflict summary.

## DS-STAGE8C-TRUSTED-CANDIDATES-01 completion

### Files changed

- `backend/src/chess_workbench/extraction/candidates.py` (new) — pure 8C-2 trusted candidate
  assembler.
- `backend/src/chess_workbench/extraction/__init__.py` — lazy exports for the six candidate
  names (keeps python-chess out of the eager contract import, matching the existing
  `normalize_chess_moves` lazy pattern).
- `backend/tests/test_extraction_candidates.py` (new, 29 tests).
- `docs/agent/HANDOFF.md` — this evidence.

No other file changed; no commit, no 8C-3 work, no provider call, no I/O.

### Behavior implemented

- `CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA = "chess-workbench/provider-response/1.0"`;
  sanitized `CcefCandidateError` with sole code `binding_mismatch` and exact message
  `CCEF package metadata does not match the trusted request` (no retained values / cause).
- Strict frozen `CcefCandidateSummary` (9 exact fields) and `CcefCandidateArtifacts`
  (nonempty bytes + 64-lowercase-hex hashes + summary).
- `assemble_ccef_candidate_artifacts(context, request, response)`:
  1. exact input types (TypeError before decoding);
  2. rebuild via `build_ccef_generation_request(context)` and require exact Pydantic equality
     with `request` (mismatch → `binding_mismatch`);
  3. `decode_extraction_response(response)` with its `CcefDecodeError` propagated unchanged;
  4. exact trusted-metadata match: package_id, source ref/media/language/page_range,
     provenance created_at, adapter `chess-workbench-ccef-prompt`/`1.0`, null
     provider/model/request/response hashes, empty extensions;
  5. request_sha256 over compact sorted-key ensure_ascii=False allow_nan=False JSON of
     `request.model_dump(mode="json")` (no newline); response_sha256 over exact
     `response.content.encode("utf-8")`;
  6. deep-copied raw package with provenance provider/model/hashes locally bound, revalidated
     through `ExtractionPackage` (nodes stay `unvalidated`);
  7. `normalize_chess_moves(raw_package)` once → normalized package;
  8. canonical raw/normalized CCEF bytes (compact sorted-key JSON + one final `\n`); provider
     response artifact bytes with exact 8 fields and one final `\n`; all four SHA-256 digests;
  9. summary computed only from the normalized package (item/move-node/figure/unresolved/
     warning/error/invalid/ambiguous counts and `has_conflicts`).
- No context/request/response/decoded mutation; repeated assembly is byte-for-byte stable.

### Focused commands (packet-verbatim)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_candidates.py \
  backend/tests/test_extraction_prompting.py \
  backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_validation.py
    → 152 passed (candidates 29 + prompting 22 + decoder 48 + validation 53)
uv run --project backend --locked ruff format --check candidates.py __init__.py test_extraction_candidates.py
    → 3 files already formatted
uv run --project backend --locked ruff check candidates.py __init__.py test_extraction_candidates.py
    → All checks passed!
uv run --project backend --locked mypy ... (same 3 files) → Success: no issues found in 3 source files
git diff --check → clean
```

### Assumptions

- "Disconnected" normalization is exercised with a present-but-illegal parent whose board cannot
  resolve (the CCEF contract itself rejects dangling/forward parent ids before normalization).
- `__init__.py` candidate exports are lazy (python-chess optional dependency stays out of the
  eager contract import, per the existing module docstring invariant).
- Frozen-model mutation in this pydantic version raises `ValidationError`.
- `git diff --stat` shows only the allowed files (`__init__.py` modified; candidates.py and the
  test file untracked/new); the pre-existing `PLANS.md` edit is untouched.

### Unresolved issues

None. 8C-3 (job/worker wiring) not started; no commit created.

### Status

**Pending Codex review.**

## Codex review of DS-STAGE8C-TRUSTED-CANDIDATES-01 (2026-08-12)

- Accepted 8C-2 without a correction round after inspecting the complete implementation and tests.
- Confirmed the edit boundary: only `extraction/candidates.py`, candidate lazy exports, its focused
  test and this handoff entry were added by the packet; pre-existing `PLANS.md` work was preserved.
- Independently reran candidate + prompting + decoder + validation tests: 152/152 passed.
- Independently reran focused Ruff format/check and MyPy on the three owning files; all passed.
  `git diff --check` is clean.
- Reviewed trusted source/provenance binding, exact request and response hash inputs, canonical
  provider/raw/normalized bytes, raw-vs-normalized separation, normalization count/status summary,
  sanitized error payloads and lazy import behavior against ADR 0014; no material gap found.
- No repository-wide gate, provider/network call or commit was performed. 8C-3 has not started.
- Next action is the bounded `DS-STAGE8C-RUNTIME-CONFIG-01` packet in `PLANS.md`; after its review,
  Codex owns the cross-module v2 handler, artifact transaction and retry-state implementation.

## DS-STAGE8C-RUNTIME-CONFIG-01 completion

### Files changed

- `backend/src/chess_workbench/config.py` — added four server-owned Stage 8C runtime settings to
  `Settings` and `strict=True` to `SettingsConfigDict` (enables pydantic-settings env-string
  coercion so the strict fields still load from `CHESS_WORKBENCH_*`).
- `backend/tests/test_config.py` — extended with the Stage 8C oracle tests.
- `docs/agent/HANDOFF.md` — this evidence.

All prior dirty/untracked work preserved; no commit/add/stage/unstage/reset; no v2 handler,
provider call, Job/worker or 8C-4 work; no probe files.

### Behavior implemented

- `deepseek_api_key: SecretStr | None = Field(default=None, repr=False)` loaded from
  `CHESS_WORKBENCH_DEEPSEEK_API_KEY`, absent by default, rejects empty/whitespace-only values
  (field validator) and stays a masked `SecretStr` (no trimming/conversion).
- `ccef_provider_timeout_seconds: float = Field(default=600.0, ge=1.0, le=1800.0,
  allow_inf_nan=False, strict=True)`.
- `ccef_max_output_tokens: int = Field(default=128_000, ge=1, le=384_000, strict=True)`.
- `ccef_max_prompt_chars: int = Field(default=2_000_000, ge=1, le=2_000_000, strict=True)`.
- Existing fields/defaults/validators and the frozen settings model are unchanged.

### Focused commands (packet-verbatim)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_config.py                  → 20 passed (4 existing + 16 new)
uv run --project backend --locked ruff format --check config.py test_config.py
                                                → 2 files already formatted
uv run --project backend --locked ruff check config.py test_config.py
                                                → All checks passed!
uv run --project backend --locked mypy ... (same 2 files)
                                                → Success: no issues found in 2 source files
git diff --check                                → clean
```

### Assumptions

- The packet freezes strict int/float fields AND requires env loading; in pydantic-settings
  2.14.2 env strings are coerced to the declared scalar type only when model config
  `strict=True` is set (`_coerce_env_val_strict`). Setting `strict=True` on the model config is
  therefore the minimal enabling change; verified that existing `Settings(...)` constructions
  (proper Python types) and env-loaded `Path`/`bool`/`int` fields still validate.
- Secret masking is standard `SecretStr` behavior (repr/mask in `model_dump_json`), no custom
  repr/logging/serialization code added.
- Test evidence covers: exact defaults/types, env loading of all four values, whitespace-only
  secret rejection, non-finite/out-of-range timeout rejection, bool/coerced-string/out-of-range
  integer rejection, secret absence from repr/str/model_dump_json with `get_secret_value()`
  access, and existing database-driver/frozen behavior.

### Unresolved issues

None. 8C-4 / v2 handler not started; no commit created.

### Status

**Pending Codex review.**

## Codex review of DS-STAGE8C-RUNTIME-CONFIG-01 (2026-08-12)

- Status: **changes requested**; the first implementation is not accepted.
- The packet-focused 20/20 tests, Ruff format/check, MyPy and `git diff --check` independently pass.
- Blocking compatibility regression: global `SettingsConfigDict(strict=True)` made all existing
  programmatic configuration strict. Codex reproduced rejection of string forms for existing
  `port`, `debug` and `source_storage_root`; the pre-change non-strict Pydantic settings model
  accepted and normalized those values.
- R1 is frozen in `PLANS.md`: retain global strict mode for environment coercion, opt every
  pre-existing field back into its former `strict=False` semantics, keep the four new fields
  strict, and add a parameterized compatibility oracle across existing scalar/path settings.
- No implementation file was changed by Codex, no broad gate/provider call/commit was performed,
  and v2 handler/8C-4 work remains unstarted.

## DS-STAGE8C-RUNTIME-CONFIG-01 R1 correction (Codex review blocker)

### Blocker addressed

The first implementation's global `SettingsConfigDict(strict=True)` changed every pre-existing
setting to strict programmatic validation. This R1 pass keeps the global `strict=True` (required
for pydantic-settings environment-string coercion of the strict Stage 8C fields) and restores the
former non-strict behavior of **every pre-existing Settings field** with explicit field-level
`strict=False`, keeping all existing defaults and numeric bounds unchanged. The four Stage 8C
fields keep their packet-frozen strict behavior. No custom settings source or origin-guessing
validator was added.

### Files changed

- `backend/src/chess_workbench/config.py` — every pre-existing field now carries
  `Field(..., strict=False)` (service_name, version, host, port, debug, database_url,
  source_storage_root, pdf_max_bytes, paddle_ocr_runner_path, stockfish_path, syzygy_path,
  engine_max_threads, engine_max_hash_mb, engine_max_time_ms, engine_worker_enabled,
  engine_worker_poll_ms); the four Stage 8C fields keep `strict=True` (three scalar) / `repr=False`
  (secret); `SettingsConfigDict(strict=True)` retained.
- `backend/tests/test_config.py` — added the parameterized compatibility oracle
  `test_preexisting_scalar_path_fields_accept_programmatic_strings_as_before` (13 cases covering
  port, debug (false/true), source storage root, PDF limit, optional Paddle runner path,
  Stockfish/Syzygy paths, the three engine limits, worker enabled and worker poll interval) plus
  retained env-loading, string-rejection and masking tests.
- `docs/agent/HANDOFF.md` — this evidence.

### Focused commands (packet-verbatim)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_config.py                  → 33 passed (20 prior + 13 new compatibility)
uv run --project backend --locked ruff format --check config.py test_config.py
                                                → 2 files already formatted
uv run --project backend --locked ruff check config.py test_config.py
                                                → All checks passed!
uv run --project backend --locked mypy ... (same 2 files)
                                                → Success: no issues found in 2 source files
git diff --check                                → clean
```

### Codex-reported regression spot checks (independent verification)

- `Settings(port="8123")` → `8123` int
- `Settings(debug="false")` → `False` bool
- `Settings(source_storage_root="/tmp/chess-workbench")` → `PosixPath('/tmp/chess-workbench')`

### Assumptions

- Field-level `strict=False` overrides the model-level `strict=True` for programmatic init of
  legacy fields; the config-level strict still drives `_coerce_env_val_strict` for env strings.
- The new-field tests (env loading, programmatic string/bool rejection, masking, bounds) are
  unchanged and still pass.

### Status

**Pending Codex re-review.** Packet not claimed accepted; v2 handler / 8C-4 not started; no
commit/stage/unstage/reset; no probe files created.

## Codex acceptance of runtime R1 and Stage 8C backend execution (2026-08-12)

- Accepted `DS-STAGE8C-RUNTIME-CONFIG-01` R1 after independently reproducing 33/33 tests, focused
  Ruff/MyPy and the three original compatibility counterexamples. Existing fields retain their
  non-strict init behavior while the four new settings keep strict env-safe semantics.
- New extraction runs now use `pdf-extraction:v2`; the v1 constant/path is retained for historical
  evidence-only runs and adjacent Stage 8B tests.
- Extended the existing PDF handler to verify and reconstruct the prompt only from committed
  render/OCR manifests and per-page evidence indexes. Provider retry reuses those artifacts and
  does not rerender/OCR the chapter.
- Added server-owned DeepSeek construction, explicit non-retry `provider_unconfigured`, provider
  retryability propagation, deterministic CCEF decode/binding failures, cancellation safety and
  three-slot atomic immutable candidate registration.
- Added versioned nested v2 Job result with evidence, candidate hashes and normalized conflict
  summary. Historical v1 result shape remains read-compatible only for v1 runs.
- Added typed `PdfCandidateSummary`; API exposes it only when the successful v2 result, complete
  evidence rows and all three CCEF rows agree by logical slot/hash. `has_conflicts` and its list
  filter now use that trusted summary rather than a placeholder.
- Regenerated `backend/openapi.json` and `frontend/src/types/api.generated.ts` successfully.
- Verification: 375 focused Stage 8C/provider/PDF/Job tests passed; 50 focused schema/API/handler
  tests passed; focused Ruff format/check and MyPy passed. SQLite suites ran outside the sandbox
  because sandboxed aiosqlite locking hung; no real provider/network call or broad acceptance ran.
- No commit was created. Remaining Stage 8C work is only the bounded Sources-page candidate summary
  packet `DS-STAGE8C-SOURCES-CANDIDATE-01`, followed by a focused Stage 8C closeout gate.

## DS-STAGE8C-SOURCES-CANDIDATE-01 completion

### Files changed

- `frontend/src/app/SourcesPage.tsx` — added the committed Stage 8C candidate summary section and
  the v2 incomplete-candidate warning to the run card.
- `frontend/src/app/WorkbenchPages.test.tsx` — added a typed `PdfExtraction['candidate']` fixture
  and five new Sources-page cases.
- `docs/agent/HANDOFF.md` — this evidence.

No backend, generated type, API client, Makefile or other component touched; all prior
dirty/untracked work preserved; no commit/stage/unstage/reset; no probe files.

### Behavior implemented

- When `run.candidate` is non-null, the run card shows a section headed exactly
  `已生成 CCEF 候选` with `内容项` (item_count), `棋步` (move_node_count), `未解决`
  (unresolved_item_count), `警告` (warning_count), `错误` (error_count), `非法棋步`
  (invalid_move_count), `歧义棋步` (ambiguous_move_count) — zero counts remain visible — plus the
  first 12 hex chars and `…` for `raw_ccef_sha256` labelled `原始 CCEF` and
  `normalized_ccef_sha256` labelled `规范 CCEF`. No paths, provider/prompt content, API keys or
  full CCEF JSON / full hashes are rendered.
- The conflict tag still uses only `run.has_conflicts`; `candidate.has_conflicts` is never
  recomputed or displayed.
- `pipeline_version === 'pdf-extraction:v2'` + Job `succeeded` + `candidate` null shows exactly
  `候选索引尚未完整提交`; a successful v1 run without a candidate does not.
- Existing run card, evidence summary, status tags, polling and filters are unchanged; no
  approval/editing/publishing/navigation/download behavior added (Stage 8D owns review).

### Focused commands (packet-verbatim)

```
pnpm --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx
    → 20 passed (15 existing + 5 new candidate cases)
pnpm --dir frontend exec prettier --check src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
    → All matched files use Prettier code style!
pnpm --dir frontend exec eslint src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
    → exit 0, no findings
pnpm --dir frontend exec tsc --noEmit   → exit 0
git diff --check                        → clean
```

### Assumptions

- The generated `PdfCandidateSummary` type (status `committed`, the seven displayed counts plus
  figure/hash fields, `has_conflicts`) is present and consistent in
  `frontend/src/types/api.generated.ts` (list and envelope reads); no contract change was needed.
- The "no raw content" oracle is proven by asserting full 64-char hashes, API paths and
  secret-like text never appear in the rendered page.
- `figure_count` is present in the type but not displayed, per the packet's exact count list.

### Unresolved issues

None. Stage 8D not started; no commit created.

### Status

**Pending Codex review.**

## Codex acceptance of DS-STAGE8C-SOURCES-CANDIDATE-01 and Stage 8C closeout (2026-08-12)

- Accepted the final Sources-page packet after inspecting the actual diff. Its changes stayed
  within the frozen two-file frontend boundary plus this handoff, and the displayed counts,
  shortened hashes, conflict source and v1/v2 incomplete-index behavior match the packet.
- Independently reran `WorkbenchPages.test.tsx`: 20/20 passed. Focused Prettier, ESLint,
  TypeScript and `git diff --check` were clean.
- Added the ADR-required focused `acceptance-stage-8c` Make target and deterministic wiring tests.
  It is deliberately non-cumulative and does not call a real provider, read user books, run smoke
  services or invoke repository-wide acceptance.
- `backend/tests/test_acceptance_wiring.py`: 15/15 passed.
- `make acceptance-stage-8c`: 219/219 focused backend tests and 20/20 frontend tests passed;
  focused Ruff format/check, MyPy and generated-contract drift all passed. The first sandboxed run
  was interrupted while SQLite concurrency waited; the same command completed outside the sandbox.
- No commit was created. Stage 8C is accepted and Stage 8D has not started. The next action is a
  real local browser run with a server-owned DeepSeek API key against a small page range before the
  full physical-page 319–399 chapter run.
- Updated `.env.example` and `README.md` to name the initial Stage 8C settings and remove the stale
  `AI_PROVIDER=mock` example. The later hardening entry below supersedes its inline `.env` advice.

## Stage 8C local secret-file hardening (2026-08-13)

- User reported the first real pages 319–323 run reached the provider but failed with
  `Structured generation content is not a valid CCEF package`. Investigation of provider content
  is intentionally deferred until the user's next trigger; no real API call or PDF inspection was
  performed in this change.
- Replaced inline-key use with `CHESS_WORKBENCH_DEEPSEEK_API_KEY_FILE`. The key file must be an
  external regular UTF-8 file, at most 4096 bytes, containing exactly one non-whitespace secret;
  one final newline is accepted. POSIX group/other permission bits are rejected.
- Kept the old `CHESS_WORKBENCH_DEEPSEEK_API_KEY` field only as a masked migration trap: any value
  now fails configuration with instructions to use the file. The plaintext is never retained in
  Settings serialization. Provider file failures are terminal `provider_secret_invalid` errors
  with no path or content disclosure.
- Updated `.env.example`, README and ADR 0014. The repository-local `.env` was not read or edited;
  the user must move the existing key and remove the old inline line before restarting the API.
- Verification: 38 config tests plus one SQLite execution regression passed (39/39). Focused Ruff
  format/check, MyPy and `git diff --check` passed. The SQLite test ran outside the sandbox due to
  the known sandboxed aiosqlite lock wait. No network/provider call or broad acceptance ran.
- No commit was created. Next action after user migration/trigger: reproduce the 319–323 failure
  locally, capture the already-stored provider response through a safe diagnostic path, and fix
  prompt/response compatibility without weakening the CCEF validation boundary.

## Stage 8C real PDF/DeepSeek debugging (2026-08-13)

- Reproduced the failed Smerdon's Scandinavian physical-page 319–323 run. Its evidence contained
  4,914 mostly single-character PDFium fragments and the prompt consumed roughly 688,804 input
  tokens. `count_rects()`/`get_text_bounded()` had been treated as semantic fragments even though
  those APIs exposed character-level layout for this PDF.
- `extraction/pdfium.py` now reads the page text range, splits deterministic logical lines and
  unions non-whitespace character boxes into one bbox per line (`text-lines-v1`). The same five
  pages now yield 110 ordered, readable fragments. The extraction logical fingerprint is versioned
  so existing bad immutable evidence is not silently replayed.
- Prompt versions 1.1–1.3 add explicit parent/sibling topology, cross-fragment continuity and a
  prohibition on guessed FEN. Prompt 1.3 further narrows only the provider response schema to
  `StartPosition` when no exact six-field FEN occurs in evidence; the portable CCEF contract itself
  remains unchanged and explicit source FEN retains the full schema.
- Real V4 Flash responses were stochastic: equivalent requests alternated between valid CCEF,
  invalid CCEF and invalid JSON. Decoder `invalid_json`/`invalid_package` now consume the existing
  maximum-three Job attempt budget; binding/config/security errors remain terminal. Retry reuses
  committed PDF evidence and does not rerender/OCR.
- Final real run: run `a9e61007-c7e8-5c4f-ae1a-b66d884fe563`, Job
  `a442dd7f-236b-40c1-9363-d26d139eb69a`, succeeded on attempt 2. It committed five rendered pages,
  five OCR indexes, both manifests, provider response, raw CCEF and normalized CCEF. Usage was
  22,379 input / 93,400 output / 115,779 total tokens; candidate contained 29 items and 362 move
  nodes. No provider/API secret or raw response was printed.
- Quality remains review-required: the model emitted 16 routes with duplicated prefixes and local
  chess validation retained 36 illegal-move warnings at incorrectly attached branches. The next
  quality design should use semantic 5–15 page subsection/game chunks followed by a deterministic
  chapter merge/deduplication pass, not isolated pages or one 81-page generation. A superseding ADR
  is required before implementing cross-chunk IDs and ownership.
- Evidence-level audit of the user's quoted introduction proved it was not converted to board
  moves: page 319 lines 4–15 belong only to prose item `p1`; the only page-319 move sequence cites
  the separately typeset numbered line `1 e4 d5 2 exd5 Nf6 3 d4 Bg4 4 Nf3 Qxd5`. The 362-node
  inflation consists of 16 generated sequences but only seven exact lines; exact deduplication
  leaves 142 nodes, and annotation-normalized shared-prefix merging leaves six routes/about 60
  graph edges. Stage 8D must present both prose and the merged playable tree without treating
  inline plan references as timeline moves.
- Job success now clears error fields left by a failed attempt, and Sources also suppresses stale
  errors for historical succeeded rows. Focused verification only: renderer 17/17, prompting
  23/23, model-format retry 2/2, succeeded-row UI 1/1. No broad acceptance or additional provider
  call was run.
- Root `AGENTS.md` now permanently requires the smallest task-relevant test selection during
  iterative work; broad acceptance/smoke is reserved for cross-boundary need, explicit request or
  Stage closeout. No commit was created.

## Stage 8C recognition consolidation and offline JSON gate (2026-08-13)

### Files changed for this quality gate

- `backend/src/chess_workbench/extraction/consolidation.py` — new deterministic consumer-side
  consolidation: heading-scoped UCI trie merging, canonical SAN/NAG handling, illegal branch
  isolation, reference remapping, evidence ordering and a conservative evidence-aware formal-line
  pass. The evidence-aware path supports both startpos/FEN positions and titled/untitled sequences;
  it is not limited to the shape of the first real book sample.
- `backend/src/chess_workbench/extraction/candidates.py` and `extraction/__init__.py` — candidate
  assembly now derives normalized CCEF through consolidation while raw CCEF remains byte-stable;
  the new integration stays lazy at the package boundary.
- `backend/tests/test_extraction_consolidation.py` and `test_extraction_candidates.py` — synthetic
  regression oracles for shared prefixes, heading boundaries, annotations, invalid fragments,
  remapping, determinism and the prose-versus-formal-notation boundary.
- `scripts/inspect_ccef_consolidation.py` — provider-free CLI that reads one stored raw CCEF plus
  evidence indexes and writes a pretty normalized JSON and a machine-readable gate report.
- `backend/src/chess_workbench/services/pdf_persistence.py` — bumped the logical extraction
  fingerprint to `pdfium-text-lines+ccef-formal-consolidation:v5`, so a new request cannot silently
  replay a pre-consolidation normalized artifact.
- `docs/decisions/0015-stage-8c-candidate-consolidation.md` and `PLANS.md` — frozen the generic
  decision and recorded the completed pre-8D JSON gate.

### Implemented behavior and real-artifact evidence

- Raw provider/CCEF artifacts are never modified. Normalized CCEF accepts playable moves only from
  standalone fragments that begin with a move number and otherwise contain notation tokens that
  `python-chess` can replay from the scoped position. Natural-language paragraphs containing move
  words remain prose.
- The generic fallback without evidence pages still merges locally valid model paths by heading,
  initial position, title and extensions. Invalid/disconnected nodes never enter a playable tree;
  uncovered material becomes prose or unresolved content rather than receiving a guessed parent.
- The production implementation was searched for the real book title, physical pages 319–323,
  chapter/game wording, representative moves, stored artifact hash, prior token/node counts and
  expected output count. There are no such source-specific conditions. The real numbers below are
  observations in the report, never code thresholds.
- Offline reprocessing used the already-stored raw CCEF and five committed evidence indexes; it did
  not call DeepSeek. Raw: 29 items, 16 sequences, 362 nodes and 5,060 prose characters. Normalized:
  16 items (3 headings, 2 sequences, 10 prose, 1 figure), 40/40 locally valid move nodes, zero
  duplicate UCI paths and 5,112 prose characters. All 101 evidence fragment hashes referenced by
  raw CCEF remain referenced by normalized CCEF, and no original non-move item ID is missing. The
  user's quoted introductory plan paragraph is present intact as one prose item and contributes no
  move evidence. The machine gate reports `gate_passed: true`.
- Local inspection artifacts (gitignored runtime data):
  `data/debug/stage8c-pages-319-323.normalized.pretty.json` and
  `data/debug/stage8c-pages-319-323.report.json`.

### Focused verification

```
pytest test_extraction_consolidation.py test_extraction_candidates.py
    → 38 passed
pytest test_stage8c_execution.py
    → 10 passed outside the sandbox after the final consolidation review
pytest test_pdf_persistence.py::{exact_replay,distinct_logical_requests}
    → 2 passed outside the sandbox; the sandboxed attempt was interrupted at the known
      aiosqlite lock wait
ruff format --check (six directly affected Python files) → clean
ruff check (same files)                                  → clean
mypy (four directly affected implementation/script files) → clean
offline inspection CLI                                  → exit 0, gate_passed true
git diff --check                                         → clean
```

### Assumptions and remaining risks

- This pass deliberately prefers false negatives over false playable moves: inline prose
  variations and a standalone notation fragment that cannot be attached unambiguously remain
  reviewable text/unresolved data. A future explicit variation-promotion rule may recover more
  branches, but must not guess a parent or weaken this gate.
- The current browser row still points to its immutable old normalized artifact. A newly enqueued
  request after restarting the API uses the v5 fingerprint and the new consolidation logic; this
  closeout intentionally did not spend provider credit or rewrite database history.
- No Stage 8D review UI was started, no broad acceptance was run and no commit was created.

### Recommended next action

Treat the inspected pretty JSON as the first Stage 8D fixture and design the review UI against the
already-normalized two-sequence/prose structure. Keep any later inline-variation promotion as a
separate data-pipeline task rather than debugging it in React.

## Stage 8D kickoff and active manual-relay packet (2026-08-13)

- ADR 0016 now freezes the three-layer boundary: pure candidate inspection, versioned/audited
  human review revisions, then atomic/idempotent publication to traditional Course/Knowledge
  drafts. Raw/provider/normalized artifacts remain immutable, and React never owns chess or
  publish-blocker decisions.
- `PLANS.md` splits Stage 8D into seven reviewable units. The active unit is only 8D-1; no SQL,
  migration, API, artifact read, frontend or publication work has started.
- Active manual DeepSeek V4-Flash packet:
  `DS-STAGE8D-REVIEW-INSPECTION-01`. It adds a pure `chess_workbench.review.inspection` module and
  synthetic focused tests. The exact interface, issue ordering, FEN matching, blocker semantics,
  permitted files, commands and escalation conditions are frozen in `PLANS.md`.
- The user will manually relay the task between agents. DeepSeek must stop after the packet and
  report `pending Codex review`; Codex must inspect the actual diff before 8D-2.
- No implementation test was run because this kickoff changed only design/coordination documents.
  `git diff --check` is clean. No commit was created.

## DS-STAGE8D-REVIEW-INSPECTION-01 (8D-1) completion

### Files changed

- `backend/src/chess_workbench/review/__init__.py` (new) — exports only the six frozen public
  names; nothing added to the extraction package exports.
- `backend/src/chess_workbench/review/inspection.py` (new) — pure inspection module.
- `backend/tests/test_stage8d_review_inspection.py` (new, 18 tests) — synthetic, non-copyrighted
  CCEF packages only.
- `docs/agent/HANDOFF.md` — this evidence.

No extraction/services/API/SQL/migration/frontend/Makefile/dependency/ADR/PLANS change; all prior
dirty/untracked work preserved; no commit/stage/unstage/reset; no probe files.

### Behavior implemented

- Frozen models: `ReviewIssue` and `ReviewInspection` with `ConfigDict(extra="forbid",
  strict=True, frozen=True)`; exact field sets per packet; `REVIEW_INSPECTION_VERSION =
  "ccef-review-inspection/1.0"`; `ReviewIssueScope`/`ReviewIssueSeverity` literals.
- `inspect_review_candidate(package)`: exact `type(package) is ExtractionPackage` else `TypeError`
  with no input value; any `unvalidated` move node raises exactly
  `ValueError("review candidate must be locally normalized")` before any result.
- Deterministic issue order: per item in source order (item warnings → derived item issues →
  move-sequence node issues), then diagnostics in original order with `info` excluded.
- Derived item issues: heading > 200 chars (`heading_too_long`, blocking), position-anchored
  prose vs package-wide canonical full-FEN occurrence set (zero → `position_anchor_no_match`,
  >1 → `position_anchor_ambiguous`; invalid anchor FEN = zero matches; duplicate occurrences
  counted individually), non-chess figure (`unsupported_figure`), chessboard figure with
  absent/invalid/non-standard `position_fen_candidate` (`chessboard_position_unresolved`),
  unresolved item (own `reason_code`, message = details else raw_text else defensive fallback,
  truncated at the 4000-char message boundary).
- Node issues: status-first blocking `move_invalid`/`move_ambiguous`, then node warnings
  (non-blocking), then `multiple_nags` when `len(nags) > 1`.
- Occurrence positions: each sequence root (startpos or declared FEN; invalid roots skipped) plus
  every valid node `fen_after`, canonicalized via `chess.Board(...).fen(en_passant="fen")`;
  duplicates preserved.
- Counts derived from the package/result; input never mutated; every issue evidence is
  deep-copied.

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_inspection.py   → 18 passed
backend/.venv/bin/ruff format --check (3 files)      → 3 files already formatted
backend/.venv/bin/ruff check (3 files)               → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (3 files)
                                                     → Success: no issues found in 3 source files
git diff --check                                     → clean
```

### Assumptions

- `ReviewIssue.message` is frozen at max 4000; the unresolved-item message uses the item's
  details/raw_text truncated to 4000 (the only variable-length message) so inspection never
  raises on valid input. The synthetic oracle text is short, so truncation is a no-op there.
- python-chess is an existing dependency (used by `extraction.validation`); importing it here
  adds no new dependency.
- `LocalId`/`DiagnosticCode` are imported directly from `..extraction.contracts` (module-level
  aliases, not in `__all__`).

### Unresolved issues

None. 8D-2 not started; no commit created.

### Status

**Pending Codex review.**

## Codex review of DS-STAGE8D-REVIEW-INSPECTION-01 (2026-08-13)

**Changes requested; 8D-1 remains incomplete.** The implementation stayed within its boundary and
the reported 18/18 tests independently pass, but the oracle missed a standard-chess validity
blocker. `_canonical_fen` only catches parser errors and never calls `board.is_valid()` or rejects
promoted/Chess960 notation. Codex reproduced an empty-board chessboard figure returning
`issue_count=0`; it must be blocking and unresolved.

The original packet also demanded an impossible combination: an issue message capped at 4,000
characters but equal to unresolved source text that may be 200,000 characters. The worker's
silent 4,000-character truncation was understandable but is not acceptable audit behavior. R1 in
`PLANS.md` supersedes that clause with a fixed summary message while the full source remains in the
immutable package item.

R1 additionally requires a true non-root `fen_after` match test because the existing test bearing
that name anchors startpos and only retests the root. No Codex implementation changes were made;
8D-2 remains blocked and no commit was created.

## DS-STAGE8D-REVIEW-INSPECTION-01 R1 correction (Codex review blocker)

### Files changed

- `backend/src/chess_workbench/review/inspection.py` — R1 corrections only.
- `backend/tests/test_stage8d_review_inspection.py` — R1 regression/updated tests.
- `docs/agent/HANDOFF.md` — this evidence.
- `backend/src/chess_workbench/review/__init__.py` — unchanged (exports already correct).

No other file touched; all prior dirty/untracked work preserved; no commit/stage/unstage/reset;
no probe files; 8D-2 not started.

### Corrections applied (per PLANS.md R1)

1. `_canonical_fen` now enforces the full standard-position validity boundary: exactly six FEN
   fields; no `~` promoted-piece marker in the placement field; castling field matches only
   ordered standard `K?Q?k?q?` or `-` (Shredder/Chess960 rejected); `chess.Board(fen,
   chess960=False)` construction; `board.is_valid()` required; every failure returns `None`. No
   private extraction helper is imported (regex + Board checks implemented locally).
2. Regression tests added: empty-board chessboard figure → blocking
   `chessboard_position_unresolved`; invalid explicit-FEN sequence root skipped so it cannot
   satisfy a position anchor (`position_anchor_no_match` emitted, never ambiguous); promoted
   marker and Chess960-castling FEN rejected as non-standard in both the chessboard-figure and
   position-anchor paths. Existing valid standard-FEN tests retained.
3. The misleading node-fen test was replaced with a true non-root anchor: the anchor equals the
   canonical `fen_after` of a valid non-root node (after 1. e4 e5), proving exactly one match
   emits no issue.
4. Unresolved truncation removed: every derived unresolved issue uses the fixed message
   `Unresolved content requires review`; `_MESSAGE_MAX` and slicing deleted; the full
   details/raw_text remain on the immutable package item (verified by test). Warning and
   diagnostic original messages remain preserved exactly.

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_inspection.py   → 24 passed (18 prior + 6 new/updated R1)
backend/.venv/bin/ruff format --check (3 files)      → 3 files already formatted
backend/.venv/bin/ruff check (3 files)               → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (3 files)
                                                     → Success: no issues found in 3 source files
git diff --check                                     → clean
```

### New / modified tests

- `test_chessboard_figure_with_empty_board_fen_is_blocking`
- `test_chessboard_figure_with_non_standard_fen_is_blocking` (parametrized: promoted marker,
  Chess960 castling)
- `test_position_anchor_with_non_standard_fen_is_zero_matches` (parametrized: same two)
- `test_invalid_explicit_fen_root_is_skipped_and_cannot_satisfy_anchor`
- `test_position_anchor_matches_valid_non_root_fen_after_once` (replaces the startpos-anchored
  node test; uses AFTER_E5_FEN)
- `test_unresolved_issue_uses_fixed_message_and_keeps_source_on_item` and
  `test_long_unresolved_source_is_not_truncated_into_the_issue` (replaces the details-precedence
  and truncation tests)

### Assumptions

- The invalid-root regression anchors the same illegal FEN that the skipped root declares; under
  the old implementation that root counted as an occurrence, so the test discriminates the bug.
- The fixed unresolved message is the auditable summary; source fidelity lives on the immutable
  package item (future review API/UI reads it from there).

### Stop conditions

None triggered (no contract/API/SQL/dependency change needed; no balance/credit/quota report).

### Status

**Pending Codex re-review.** 8D-2 not started; no commit created.

## Codex final review of DS-STAGE8D-REVIEW-INSPECTION-01 R1 (2026-08-13)

**Accepted; 8D-1 complete.** Codex independently reran 24/24 focused tests, Ruff format/check and
MyPy. Direct adversarial calls confirm empty-board, unordered castling, Chess960 castling and
promoted-marker FENs each produce the expected blocker. Long unresolved source remains unchanged
on the package and receives only the fixed issue summary.

The real `data/debug/stage8c-pages-319-323.normalized.pretty.json` also composes with the inspection:
16 items, 40 move nodes, one blocking `unsupported_figure` issue for `photo_caption1` on physical
page 322. This is the intended explicit-review behavior; no source content was silently deleted.

The next manually relayed Flash unit is `DS-STAGE8D-READ-CONTRACTS-01` in `PLANS.md`. It owns only
the two response schemas and focused tests; storage/API/page serving remain 8D-2B and have not
started. No broad gate, implementation edit by Codex or commit was performed.

## DS-STAGE8D-READ-CONTRACTS-01 (8D-2A) completion

### Files changed

- `backend/src/chess_workbench/schemas/review.py` (new) — the two strict read-only review
  response contracts and the path alias.
- `backend/tests/test_stage8d_review_schemas.py` (new, 19 tests) — synthetic, non-copyrighted
  normalized packages only.
- `docs/agent/HANDOFF.md` — this evidence.

No route, storage read, content serving, SQL, frontend, generated OpenAPI artifact,
`review/inspection.py`, extraction, services/API, existing schema, Makefile, dependency or
PLANS.md change. All prior dirty/untracked work preserved; no commit/stage/unstage/reset; no
probe files.

### Behavior implemented

- `ReviewPageContentPath`: strict regex `^/api/pdf-extractions/<uuid>/review/pages/[1-9][0-9]*$`
  (lowercase canonical UUID form), max 128 chars.
- `PdfReviewPageRead` (exact order): `physical_page` (1..20_000), `media_type: Literal["image/png"]`
  default, `byte_size > 0`, `content_sha256: Sha256`, `content_url: ReviewPageContentPath`.
- `PdfReviewDocumentRead` (exact order): `run_id: EntityId`, `normalized_ccef_sha256: Sha256`,
  `package: ExtractionPackage`, `inspection: ReviewInspection`, `pages: list[PdfReviewPageRead]`.
- Both extend the existing `StrictContract` (extra forbid + frozen); `EntityId`/`Sha256` reused,
  no parallel aliases; only the three names exported; no package `__init__` edited.
- One `mode="after"` validator enforces: package_id == run_id; source page range present; page
  descriptors are exactly the complete ascending range with no gaps/duplicates/extras; every
  `content_url` equals `/api/pdf-extractions/{run_id}/review/pages/{physical_page}` via the
  canonical lowercase UUID string; and `inspection == inspect_review_candidate(package)` with the
  accepted normalized-candidate `ValueError` propagating unchanged.
- Error messages name only the violated relationship (never package data, paths or hashes).
  `normalized_ccef_sha256` is never recomputed. No provider response, raw CCEF, CAS/filesystem
  path, API key or OCR text is present in the contract.

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_schemas.py    → 19 passed
backend/.venv/bin/ruff format --check (2 files)    → 2 files already formatted
backend/.venv/bin/ruff check (2 files)             → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (2 files)
                                                   → Success: no issues found in 2 source files
git diff --check                                   → clean
```

### Test coverage

- Valid construction, exact field order, JSON round trip, frozen/unknown-field rejection.
- package_id/run_id mismatch and null source page range rejection.
- Missing/duplicate/unordered/extra page descriptors.
- Wrong run/page in `content_url`, uppercase noncanonical UUID path, non-PNG media type,
  zero byte size, bad hash, page number boundaries (0 / 20_001).
- Stale/tampered inspection rejection and unvalidated-package error propagation
  (`review candidate must be locally normalized`).
- `model_dump(mode="json")` contains package/inspection/page metadata but none of
  `provider_response`, `raw_ccef`, `relative_path`, `absolute_path`, `api_key`, `ocr_text`.
- `openapi_schema(PdfReviewDocumentRead)` standalone OpenAPI 3.0 output: recursive walk proves
  no `$defs`, `$ref`, `const` or `type == "null"` anywhere, and the nested CCEF item
  discriminator (`propertyName == "kind"`) remains present.

### Assumptions

- `openapi_schema` (existing `chess_workbench.api.contracts`) was verified standalone-capable for
  both `ExtractionPackage` and `ReviewInspection` before wiring the document model.
- The uppercase-UUID path test uses a lettered UUID because the fixture RUN_ID is digit-only and
  `str().upper()` would be identical.

### Stop conditions

None triggered (no out-of-boundary file, contract, dependency or route/storage work needed; no
balance/credit/quota report).

### Status

**Pending Codex review.** 8D-2B not started; no commit created.

## Codex review of DS-STAGE8D-READ-CONTRACTS-01 (2026-08-13)

**R1 required; 8D-2A remains open.** Codex independently reran the 19 focused tests, Ruff
format/check, MyPy and `git diff --check`; all pass. The public fields and specified relationship
checks otherwise match the packet. Final defensive review found two blockers:

1. `list(range(page_range.start_page, page_range.end_page + 1))` allocates proportional to an
   unbounded CCEF page range before rejecting it. Use descriptor-count plus indexed comparison so
   invalid huge ranges fail with constant extra memory; add a `1..1_000_000_000`/empty-pages
   regression that returns the existing relationship error promptly.
2. The discriminator oracle searches for any nested `propertyName == "kind"`, so the anchor or
   initial-position discriminator can mask loss of the required CCEF item discriminator. Assert
   the exact `properties/package/properties/items/items/discriminator` path instead.

No route, storage, frontend, broad gate or commit was performed. Apply only the R1 instructions in
the active `PLANS.md` packet and remain `pending Codex re-review`; do not begin 8D-2B.

## DS-STAGE8D-READ-CONTRACTS-01 R1 correction (Codex review blocker)

### Files changed

- `backend/src/chess_workbench/schemas/review.py` — constant-extra-memory page-descriptor
  validation.
- `backend/tests/test_stage8d_review_schemas.py` — exact discriminator-path assertion + huge
  page-range regression.
- `docs/agent/HANDOFF.md` — this evidence.

No API/service/storage/extraction/schema/frontend/PLANS change; no 8D-2B work; no
commit/stage/unstage/reset; no probe files.

### Corrections applied (per PLANS.md R1)

1. Removed `list(range(page_range.start_page, page_range.end_page + 1))`. The validator now
   computes `expected_count = end_page - start_page + 1`, rejects when `len(self.pages)` differs,
   then compares each descriptor to `start_page + zero_based_index` via `enumerate`. Existing
   error message and all other validator ordering/behavior preserved. No public page-range limit
   added; no extraction contract change.
2. The OpenAPI discriminator oracle no longer searches for any nested `propertyName == "kind"`.
   It asserts the exact path
   `schema["properties"]["package"]["properties"]["items"]["items"]["discriminator"]
   ["propertyName"] == "kind"`.

### New regression test

`test_openapi_schema_rejects_huge_page_range_with_constant_memory`: a valid normalized package
with `page_range 1..1_000_000_000` and an empty descriptor list promptly raises the existing
page-descriptor relationship error without building or iterating the range (the count check runs
in constant extra memory).

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_schemas.py    → 20 passed (19 prior + 1 new regression)
backend/.venv/bin/ruff format --check (2 files)    → 2 files already formatted
backend/.venv/bin/ruff check (2 files)             → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (2 files)
                                                   → Success: no issues found in 2 source files
git diff --check                                   → clean
```

### Assumptions

- The count check short-circuits the huge range before any per-descriptor work, and
  `normalized_package` builds the 1e9 range through the existing unbounded CCEF `PageRange`
  without materializing it.

### Status

**Pending Codex re-review.** 8D-2B not started; no commit created.

## Codex final review of DS-STAGE8D-READ-CONTRACTS-01 R1 (2026-08-13)

**Accepted; 8D-2A complete.** The DeepSeek UI stalled after implementation, but all intended edits
and its R1 evidence are present. Codex independently reran 20/20 focused tests, Ruff format/check,
MyPy and `git diff --check`; all pass. The validator uses descriptor count plus indexed comparison
with constant extra memory, the `1..1_000_000_000` regression returns promptly, and the OpenAPI
test now targets the exact CCEF item-union discriminator.

The next manually relayed unit is `DS-STAGE8D-REVIEW-LOADER-01 (8D-2B1)` in `PLANS.md`: verified
read-only CAS/index loading only. HTTP routes and generated contracts remain 8D-2B2; the browser
page remains 8D-3. No broad gate or commit was performed.

## DS-STAGE8D-REVIEW-LOADER-01 (8D-2B1) completion

### Files changed

- `backend/src/chess_workbench/services/pdf_review.py` (new) — read-only review loader.
- `backend/tests/test_stage8d_review_read_service.py` (new, 20 tests) — temporary SQLite DB +
  temporary CAS with a synthetic two-page normalized package, manifest and PNG payloads.
- `docs/agent/HANDOFF.md` — this evidence.

No HTTP route, schema, SQL model, migration, extraction, existing service, API, frontend,
OpenAPI, generated type, Makefile, dependency or PLANS.md change. All prior dirty/untracked work
preserved; no commit/stage/unstage/reset; no probe files; no session writes in the service.

### Behavior implemented

- Public interface exactly per packet: frozen slots dataclass `PdfReviewPageContent`
  (body/media_type/byte_size/content_sha256) and `PdfReviewReadService(session, settings)` with
  `read_document(run_id)` / `read_page(run_id, physical_page)`; only these two names exported;
  exact-type misuse raises concise TypeError without the rejected value.
- Stable outcomes: missing run → `ServiceError("not_found", 404, "PDF extraction review was not
  found")`; any non-v2 / non-succeeded / incomplete / inconsistent / invalid state →
  sanitized `ServiceError("ambiguous_context", 409, "PDF extraction review is not available")`
  with no details and no cause; page outside the run range →
  `ServiceError("not_found", 404, "PDF review page was not found")`;
  `source_storage_unavailable` from the verified CAS reader propagates unchanged.
- Verification chain: v2 pipeline + succeeded Job + exact result outer set/schema/run binding;
  exact candidate six fields + exact summary set + lowercase-64-hex normalized hash; exactly one
  page-null `normalized_ccef` and one page-null `render_manifest` plus one unique `rendered_page`
  per run page (no missing/duplicate/extra relevant slots); JSON media + ≤64 MiB sizes and PNG
  media + ≤ MAX_PNG_BYTES sizes; candidate/manifest hash bindings against artifact rows; verified
  reads of manifest and normalized CCEF via `read_verified_content_addressed_bytes` through
  `asyncio.to_thread` with each registered path/size/hash; manifest exact top-level key set and
  evidence schema/run/asset/hash/page-range bindings plus an exact ascending page list whose
  physical page/hash/size/media match every rendered row; package parsed directly with
  `ExtractionPackage.model_validate_json`, package_id == run_id and source page range == run
  range; live `inspect_review_candidate(package)`; `PdfReviewDocumentRead` built with canonical
  `/api/pdf-extractions/{run_id}/review/pages/{page}` URLs.
- `read_page` resolves the same review first, reads the single resolved page with
  `MAX_PNG_BYTES`, and requires the standard eight-byte PNG signature (wrong signature →
  sanitized 409). No caller-supplied path is ever accepted.

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_read_service.py   → 20 passed
backend/.venv/bin/ruff format --check (2 files)        → 2 files already formatted
backend/.venv/bin/ruff check (2 files)                 → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (2 files)
                                                       → Success: no issues found in 2 source files
git diff --check                                       → clean
```

### Test coverage

Valid document/page reads; deterministic repeated reads with no session mutation; missing run
404; queued Job and historical v1 409; malformed/wrong-run result, candidate hash mismatch,
missing/duplicate/extra slots and wrong media metadata 409; misbound manifest and empty manifest
page list 409; unvalidated CCEF and package/run (page-range) mismatch 409; missing normalized/
manifest/page CAS bytes propagate the stable 503 storage error; out-of-range page 404; wrong PNG
signature sanitized 409; exact-type misuse TypeError; public errors never leak paths, hashes,
CCEF, provider or API-key text.

### Assumptions

- The manifest's `pdf_content_sha256` is verified against the registered `PdfAsset` hash via
  `PdfPersistenceService.get_asset` (the service remains the only database read boundary).
- Manifest/pages are validated against the exact produced key sets (top-level 8 keys; page entry
  9 keys) to catch malformed manifests deterministically.
- `ServiceError` from the verified reader is assumed to be `source_storage_unavailable` and
  propagates unchanged; reader TypeError/ValueError from corrupt rows is sanitized to 409.

### Stop conditions

None triggered (no contract/API/SQL/dependency change needed; no balance/credit/quota report).

### Status

**Pending Codex review.** 8D-2B2 not started; no commit created.

## Codex review of DS-STAGE8D-REVIEW-LOADER-01 (2026-08-13)

**R1 required; 8D-2B1 remains open.** Codex reproduced the 20/20 focused pass outside the tool
sandbox (inside it, even minimal `aiosqlite.connect()`/`asyncio.to_thread()` failed to wake, which
is environmental), plus clean Ruff, MyPy and `git diff --check`.

Independent temporary-DB replay then proved a contract violation: adding a second
`normalized_ccef` with non-null `page_number=5` alongside the valid page-null row was accepted by
`read_document`. The loader discards malformed run-level rows before checking relevant slots.
R1 in the active `PLANS.md` packet therefore requires an exact all-relevant slot map, early
run-to-asset page-bound validation before any range allocation, lowercase registered hashes,
strict manifest `byte_size`, and the already-frozen exact UUID type boundary. No API, frontend,
broad gate or commit was performed; do not begin 8D-2B2.

## DS-STAGE8D-REVIEW-LOADER-01 R1 completion

### Files changed

- `backend/src/chess_workbench/services/pdf_review.py` — R1 corrections only.
- `backend/tests/test_stage8d_review_read_service.py` — 6 new R1 regressions (total 26).
- `docs/agent/HANDOFF.md` — this evidence.

No API/schema/database/migration/other-service/frontend/OpenAPI/Makefile/dependency/PLANS
change; no 8D-2B2 work; no commit/stage/unstage/reset; no probe files.

### Corrections applied (per PLANS.md R1)

1. `_bounded_run_pages` loads the run's `PdfAssetView` immediately after the run/pipeline/Job/
   result checks and requires `type(first_page) is int`, `type(last_page) is int`,
   `1 <= first_page <= last_page`, `last_page <= asset.page_count <= 20_000`, else the sanitized
   409 — so the page list is materialized only after the bounds pass (a corrupt `last_page =
   1_000_000_000` row is rejected before any allocation). The loaded asset is reused for the
   manifest `pdf_content_sha256` binding; no second read.
2. One slot map is built from every artifact whose kind is in `_RELEVANT_KINDS`, keyed
   `(kind, page_number)`; duplicate keys reject; the key set must equal exactly
   `{("normalized_ccef", None), ("render_manifest", None)} ∪ {("rendered_page", p) for each
   bounded run page}`. Non-null-page normalized/manifest rows are no longer filtered out — any
   extra relevant slot returns 409.
3. Every relevant artifact `content_sha256` must match the lowercase 64-hex pattern before
   descriptors are produced; render-manifest page entries require exact-int `byte_size` before
   comparison (JSON `true` cannot bind to database integer 1). Media/size/hash/manifest checks
   preserved.
4. Both public methods use `type(run_id) is UUID` (rejects UUID subclasses); bool/non-int
   `physical_page` rejection retained.

### New regressions (all pass, 409/TypeError as specified)

- valid run + extra `normalized_ccef(page_number=FIRST_PAGE)` → 409
- valid run + extra `render_manifest(page_number=FIRST_PAGE)` → 409
- corrupt `run.last_page = 1_000_000_000` → prompt 409 before page-range allocation
- uppercase rendered-artifact hash → 409 on `read_document`
- manifest entry `byte_size=true` vs database size 1 → 409 (no `true == 1` binding)
- UUID subclass passed to `read_document`/`read_page` → TypeError

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_read_service.py   → 26 passed (20 original + 6 R1)
backend/.venv/bin/ruff format --check (2 files)        → 2 files already formatted
backend/.venv/bin/ruff check (2 files)                 → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (2 files)
                                                       → Success: no issues found in 2 source files
git diff --check                                       → clean
```

### Environment note

The focused pytest ran inside the tool sandbox without aiosqlite hangs (26 passed in ~6 s), so
the sandbox-escape clause in the R1 instructions was not needed.

### Status

**Pending Codex re-review.** 8D-2B2 not started; no commit created.

## Codex final review of DS-STAGE8D-REVIEW-LOADER-01 R1 (2026-08-13)

**Accepted; 8D-2B1 complete.** Codex independently reproduced 26/26 focused tests (outside the
tool sandbox because its aiosqlite thread callback had previously stalled), clean Ruff
format/check, MyPy and `git diff --check`. Static review confirms the asset bounds precede range
materialization and the unified relevant-slot map sees non-null normalized/manifest extras. The
original penetrating extra-normalized case is now a dedicated 409 regression; registered hashes,
manifest byte size and exact UUID types are also closed.

The next manually relayed unit is `DS-STAGE8D-REVIEW-HTTP-01 (8D-2B2)` in `PLANS.md`. It owns only
the two GET routes, transport tests and generated OpenAPI/TypeScript artifacts. Loader/schema
changes and Stage 8D UI work are explicitly excluded. No broad gate or commit was performed.

## DS-STAGE8D-REVIEW-HTTP-01 (8D-2B2) completion

### Files changed

- `backend/src/chess_workbench/api/pdf.py` — two new pdf_blueprint GET routes + imports
  (`raw`, `PdfReviewDocumentRead`, `PdfReviewReadService`).
- `backend/tests/test_stage8d_review_api.py` (new, 7 tests) — scripted fake service; synthetic
  normalized package/document; no user book.
- `backend/openapi.json` + `frontend/src/types/api.generated.ts` — regenerated ONLY via
  `make contracts` (no hand edits).
- `docs/agent/HANDOFF.md` — this evidence.

No loader/schema/database/extraction/other-service/frontend-page/Makefile/dependency/PLANS
change; no 8D-3 work; no commit/stage/unstage/reset; no probe files.

### Routes implemented (transport wiring only)

1. `GET /api/pdf-extractions/<run_id:uuid>/review`, route name `get_pdf_extraction_review`,
   operationId `getPdfExtractionReview`, summary/tag per packet; 200 JSON
   `PdfReviewDocumentRead`; documented 404/409/503 via the existing `ERROR_SCHEMA`. Opens one
   ordinary `database.session()` (no begin/commit), calls
   `PdfReviewReadService(session, request.app.ctx.settings).read_document(run_id)`, returns
   `model_dump(mode="json")`; does not catch `ServiceError` (global adapter emits stable JSON).
2. `GET /api/pdf-extractions/<run_id:uuid>/review/pages/<physical_page:int>`, route name
   `get_pdf_extraction_review_page`, operationId `getPdfExtractionReviewPage`, 200 media only
   `image/png` `{type: string, format: binary}`; same documented errors. Opens one ordinary
   session, calls `read_page(run_id, physical_page)`, returns the exact `body` via Sanic `raw`
   with status 200, `content_type=content.media_type` and exactly:
   `Content-Length: str(content.byte_size)`, `ETag: "<lowercase-sha256>"` (with double quotes),
   `Cache-Control: private, max-age=31536000, immutable`,
   `X-Content-Type-Options: nosniff`; no Content-Disposition/range/redirect/JSON wrapper.

### Focused oracle (7 tests, all pass)

1. document GET exact 200 JSON + exact UUID passed to `read_document`;
2. page GET routable from every document `content_url`, exact UUID/int passed, byte-identical
   PNG body, `image/png`, exact length/ETag/cache/nosniff, no content-disposition;
3. `not_found` 404 / `ambiguous_context` 409 / `source_storage_unavailable` 503 from the fake
   propagate through the existing JSON error handler on both route families without leaking fake
   details;
4. malformed UUID, non-integer page and missing page paths never call the service and are never
   200;
5. `/docs/openapi.json` contains both exact operation IDs; document 200 uses the standalone
   review schema with the nested CCEF item discriminator
   (`properties.package.properties.items.items.discriminator.propertyName == "kind"`); page 200
   exposes only binary `image/png`; all three error statuses reference the existing error
   schema;
6. response JSON and both review operations' OpenAPI contain none of `provider_response`,
   `raw_ccef`, `relative_path`, `absolute_path`, `api_key`, `ocr_text`.

### Contracts

`make contracts` regenerated `backend/openapi.json` and
`frontend/src/types/api.generated.ts`; `make check-contracts` reports up to date. Generated
TypeScript contains both new path operations; `getPdfExtractionReview` 200 carries the inline
review-document schema (normalized_ccef_sha256, package/inspection/pages), and
`getPdfExtractionReviewPage` 200 is `"image/png": string` binary. Only the two named generated
artifacts changed.

### Focused commands (packet-verbatim)

```
backend/.venv/bin/pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8d_review_api.py          → 7 passed
backend/.venv/bin/ruff format --check (2 files)       → 2 files already formatted
backend/.venv/bin/ruff check (2 files)                → All checks passed!
backend/.venv/bin/mypy --config-file backend/pyproject.toml (2 files)
                                                      → Success: no issues found in 2 source files
make contracts                                        → wrote backend/openapi.json + api.generated.ts
make check-contracts                                  → generated contracts are up to date
git diff --check                                      → clean
```

### Assumptions

- Sanic normalizes a trailing slash, so `/review/` routes to `/review`; the malformed-path test
  therefore does not list the trailing-slash document URL (it is routable, not malformed).
- The OpenAPI leak oracle is scoped to the two review operations because the pre-existing
  `PdfCandidateSummary` schemas legitimately carry `provider_response_sha256`/`raw_ccef_sha256`
  hash field names in the same document; the review operations and the review document JSON
  response contain none of the forbidden values.

### Stop conditions

None triggered (Sanic `raw` fully expressed the frozen binary response; the accepted
loader/schema needed no change; contract generation touched only the two named generated
artifacts).

### Status

**Pending Codex review.** 8D-3 not started; no commit created.

## Codex final review — DS-STAGE8D-REVIEW-HTTP-01 (8D-2B2)

Accepted on 2026-08-13 after inspecting the actual implementation, scripted API tests and generated
contracts. Independent focused results: `test_stage8d_review_api.py` 7/7 passed; Ruff format/check
and MyPy passed for the owned Python files; `make check-contracts` reported up to date; and
`git diff --check` was clean. The JSON route delegates to the accepted verified loader through an
ordinary read session; the PNG route returns exact bytes, media type and the four frozen integrity/
cache headers; OpenAPI exposes only binary `image/png`; 404/409/503 remain handled by the existing
global adapter. No broad suite was run and no commit was created.

The next manually relayed unit is `DS-STAGE8D-REVIEW-PAGE-01 (8D-3A)` in `PLANS.md`. It owns only a
typed, self-contained read-only review component, its focused tests and one generated-type alias.
Application routing and the Sources-page entry point are deliberately deferred to 8D-3B; backend,
contracts, persistence and all edit/approval/publication behavior remain excluded.

## DS-STAGE8D-REVIEW-PAGE-01 (8D-3A) completion

### Files changed

- `frontend/src/logic/api/types.ts` — added exactly the frozen `PdfReviewDocument` alias over
  `paths['/api/pdf-extractions/{run_id}/review']['get']['responses'][200]['content']['application/json']`.
- `frontend/src/app/PdfReviewPage.tsx` (new) — self-contained read-only review page component,
  one prop `{ runId: string }`.
- `frontend/src/app/PdfReviewPage.test.tsx` (new, 15 tests) — react-chessboard mocked as an
  observable element; `fetch` mocked only; typed synthetic review documents; no user book.
- `docs/agent/HANDOFF.md` — this evidence.

No backend, OpenAPI, generated API types, `App.tsx`, `SourcesPage.tsx`, global CSS, dependencies
or PLANS.md change; no 8D-3B/8D-4 work; no commit/stage/unstage/reset; no probe files.

### Implementation behavior (frozen read-only behavior)

1. `useSWR` + `fetchJson<PdfReviewDocument>` on
   `/api/pdf-extractions/${encodeURIComponent(runId)}/review`; accessible busy state
   (`role="status"` + `aria-busy`); failed request renders an antd `Alert` with the public
   message chosen only from `ApiError.status`: 404 `审核资料不存在`, 409 `审核资料尚不可用`,
   503 `来源页暂时不可用`, otherwise `加载审核资料失败`; no body/path/hash/provider/raw detail.
2. First `document.pages` descriptor rendered by default; server-ordered page buttons; one
   `<img>` with `src` exactly the descriptor's `content_url`, alt naming the physical page and
   caption `物理页 N`; item/node/issue evidence buttons select the matching descriptor; absent or
   out-of-document evidence page is a no-op.
3. Non-draggable `react-chessboard` (`arePiecesDraggable={false}`, `FAST_MOVE_ANIMATION_MS`,
   established board border/shadow style, no engine analysis); initial board = first move
   sequence's declared initial FEN (or `START_FEN` for startpos/no sequence); valid node buttons
   set the exact `fen_after`; invalid/ambiguous nodes stay visible but disabled; prose `position`
   anchor sets its exact FEN; prose `move_node` anchor locates the referenced valid node.
4. Items rendered strictly in source order without merge/sort/dedup: semantic headings at the
   declared level (clamped 1..6), plain prose whitespace-preserving, markdown prose through
   `react-markdown` + `rehype-sanitize` only, move sequences with optional title/start-position
   button/every node with move label, validation status, NAG values and parent-derived
   indentation (no chess-rule computation), figures with type/caption/alt and candidate FEN as
   text only, unresolved items with visible warning treatment + reason code + complete raw
   text/details. Evidence page buttons stay beside their owning item/node.
5. `inspection.issues` strictly in backend order with severity, blocking label, scope, code,
   message and evidence buttons; exact `issue_count`/`blocking_issue_count`/`item_count`/
   `move_node_count` displayed from the backend (never inferred); zero issues shows exactly
   `没有发现自动检查问题，但仍需人工批准`.
6. Responsive Tailwind-only three-area layout (wide: source | board | candidate+issues; narrow:
   stacked in that order), `max-w-prose` reading width, no edit/approve/reject/publish controls,
   no server-state mutation.

### Focused oracle (15 tests, all pass)

1. exact review URL (with `encodeURIComponent`), accessible busy state, and the four sanitized
   error branches (404/409/503/other) without leaking a fake response body/path;
2. first rendered page, server-ordered page buttons, exact `content_url`, page switching,
   evidence-driven page selection and out-of-document (page 99) no-op;
3. all five item kinds in strict source order (eight items incl. two headings, no dedup), safe
   markdown (`<script>`/raw HTML cannot execute — no `script`/`b` elements), complete unresolved
   raw text + details, plain-prose whitespace preservation;
4. initial startpos and declared-initial-FEN board states, valid-node navigation, both prose
   anchor kinds, 回到初始局面 reset, invalid/ambiguous nodes never change the board, no draggable
   behavior;
5. source-ordered branching nodes with status/NAG/evidence and parent-derived indentation
   (16px/32px/0px from the ordered `parent_id` links);
6. backend issue order, exact counts text (`问题 2 · 阻断 1 · 内容项 8 · 棋步 5`), blocking labels,
   severity labels, evidence navigation, and the exact zero-issue empty state;
7. no 批准/拒绝/发布/编辑/保存/删除 controls and exactly one GET request (no
   POST/PUT/PATCH/DELETE).

### Focused gates (packet-verbatim)

```
pnpm --dir frontend exec vitest run src/app/PdfReviewPage.test.tsx
                                       → 1 file passed, 15 tests passed
pnpm --dir frontend exec prettier --check src/logic/api/types.ts
  src/app/PdfReviewPage.tsx src/app/PdfReviewPage.test.tsx
                                       → All matched files use Prettier code style!
pnpm --dir frontend exec eslint (3 files) --max-warnings=0
                                       → clean
pnpm --dir frontend typecheck          → clean (tsc -b)
git diff --check                       → clean
```

### Assumptions

- antd v6 `Alert` uses `title` (the `message` prop is deprecated and renders an empty title).
- The `PdfReviewDocument` generated schema is optional (`package.items?`, `nags?`) and the
  component and fixtures handle absence with `?? []` / optional rendering.
- Heading accessible names include the adjacent evidence buttons, so tests match heading names
  with regex.
- The project's vitest setup does not load jest-dom; tests use native DOM assertions.

### Stop conditions

None triggered (the generated review type sufficed; no contract/backend/CSS/dependency change
needed; sanitized markdown is expressible with the installed `react-markdown` + `rehype-sanitize`).

### Remaining risks

- Board initialization happens once on first data arrival (`useRef` guard) so SWR focus
  revalidation cannot reset user navigation; this is intentional per the frozen behavior.
- Indentation is derived purely from ordered `parent_id` links; a malformed link falls back to
  depth 0 rather than rejecting the document.

### Status

**Pending Codex review.** 8D-3B/8D-4 not started; no commit created.

## Codex review — DS-STAGE8D-REVIEW-PAGE-01 changes requested

The 15 focused tests, Prettier, ESLint, TypeScript and `git diff --check` were independently rerun
and passed. The overall read-only implementation and security direction are sound, but 8D-3A is
not accepted yet. A real lifecycle defect remains: the boolean one-time board initializer retains
the old run's board when a mounted `PdfReviewPage` receives a different `runId`. The test oracle is
also weaker than claimed: fixtures pass items through `unknown[]` plus a contract assertion, valid
nodes are not coherent normalized nodes, a node issue misbinds `item_id`, and the issue-evidence
test clicks the first global page-6 button rather than the issue row's button.

`PLANS.md` now carries the bounded R1 corrections: run-identity-aware board/page initialization;
generated-type-derived fixtures with no loose item cast; coherent normalized node metadata;
conventional White `N.` / Black `N...` move prefixes; and a scoped issue-evidence oracle. The edit
boundary and focused gates are unchanged. 8D-3B/8D-4 remain unstarted; no commit was created.

## DS-STAGE8D-REVIEW-PAGE-01 R1 completion

### Files changed

- `frontend/src/app/PdfReviewPage.tsx` — R1 corrections only.
- `frontend/src/app/PdfReviewPage.test.tsx` — 16 tests (15 original + 1 run-identity regression).
- `docs/agent/HANDOFF.md` — this evidence.

No backend/OpenAPI/generated types/`App.tsx`/`SourcesPage.tsx`/global CSS/dependency/PLANS
change; no 8D-3B/8D-4 work; no commit/stage/unstage/reset; no probe files.

### Corrections applied (per PLANS.md R1)

1. **Run-identity-aware initialization.** Replaced the boolean `boardInitialized` with
   `initializedRunId` (`useRef<string | null>`). On the first verified document for each distinct
   `runId`, the effect sets both the board (first-sequence initial FEN) and the selected page
   (first descriptor). A same-run SWR revalidation changes the `data` reference but keeps the
   guard satisfied, so user board/page navigation is preserved. New lifecycle regression proves:
   a mounted instance navigated to e4/page-6 keeps both after a same-run revalidation (global
   `mutate` with a fresh document reference), then resets both to the second run's initial FEN and
   first page after `rerender` with a different `runId`.
2. **Generated-type-derived contracts.** Removed `type EvidenceRef = { page: number }`;
   `EvidenceRef = ReviewItem['evidence'][number]` derives from `PdfReviewDocument`. Test fixtures
   derive `ReviewItem`/`MoveSequenceItem`/`MoveNode`/`ReviewIssue`/`ReviewPage` from the alias;
   `baseItems()`/`baseIssues()` and all override parameters are typed with those derived types;
   `items?: unknown[]` and the `items as PdfReviewDocument['package']['items']` escape hatch are
   gone (no `any`/`unknown`/double assertions/handwritten CCEF).
3. **Coherent normalized fixture nodes.** Valid nodes now carry consistent metadata: n1 `e4` is
   White from startpos (`fen_before: START_FEN`, `side_to_move: 'b'`, SAN `e4`, UCI `e2e4`);
   n2 `e5` and n3 `c5` are Black from the e4 position (`fen_before: FEN_AFTER_E4`,
   `side_to_move: 'w'`). The node issue binds `item_id: 'seq1'` and `node_id: 'n4'` separately.
   All fixtures remain synthetic and copyright-free.
4. **Conventional move prefix.** The component keeps source `move_text` and renders
   `N. move` for White and `N... move` for Black when `move_number` exists, using the accepted
   backend `side_to_move` (side to move after the node: `'b'` after a White move, `'w'` after a
   Black move). No turn/legality computation in React. Source-order/branch oracles updated to
   `1. e4`, `1... e5`, `1... c5`.
5. **Scoped issue-evidence oracle.** The issue test locates the issue row containing
   `棋步非法` via `closest('li')` and clicks that row's own page-6 evidence button with
   `within(issueRow)`, asserting the source image changes from page 5 to page 6. No global
   `getAllByRole(...)[0]` for the issue evidence.

### Focused gates (packet-verbatim)

```
pnpm --dir frontend exec vitest run src/app/PdfReviewPage.test.tsx
                                       → 1 file passed, 16 tests passed (15 + 1 new)
pnpm --dir frontend exec prettier --check src/logic/api/types.ts
  src/app/PdfReviewPage.tsx src/app/PdfReviewPage.test.tsx
                                       → All matched files use Prettier code style!
pnpm --dir frontend exec eslint (3 files) --max-warnings=0
                                       → clean
pnpm --dir frontend typecheck          → clean (tsc -b, exit 0)
git diff --check                       → clean
```

### Assumptions

- Backend `side_to_move` is the side to move in the position AFTER the node (matches the CCEF
  `fen_after` semantics and the coherent fixtures), so White moves carry `'b'` and render `N.`,
  Black moves carry `'w'` and render `N...`.
- The lifecycle test renders without the custom SWR provider so global `mutate` can simulate a
  same-run revalidation data reference change; the other 15 tests keep the isolated per-render
  cache provider.
- When the run identity changes, the component briefly renders the loading view, so the board
  DOM node is re-created; the regression re-queries via `screen` instead of holding a stale node.

### Status

**Pending Codex re-review.** 8D-3B/8D-4 not started; no commit created.

## Codex R1 re-review — DS-STAGE8D-REVIEW-PAGE-01 R2 required

The 16 focused tests, Prettier, ESLint, TypeScript and `git diff --check` were independently rerun
and passed. R1's lifecycle reset, generated-type derivation and scoped issue click are correct, but
8D-3A remains unaccepted because the new chess-context oracle encodes the opposite of the backend
contract. `_normalize_node` checks `side_to_move` against `board.turn` before pushing the move, and
the existing backend regression proves e4=`w`, e5=`b`; the R1 fixture and UI comment instead use
post-move sides. Its three `fen_after` constants also omit the authoritative `en_passant="fen"`
targets (`e3`, `e6`, `c6`). Finally, the custom-FEN tests change only the root while retaining a
startpos-only move tree, and the second-run document uses pages 7/8 against a 5..6 source/evidence
range. These are type-correct but not valid normalized review documents.

`PLANS.md` now freezes a narrow R2: correct the pre-move side semantics and exact normalized FENs;
use a dedicated legal one-node custom-FEN sequence; and make the second run's pages/evidence/
inspection coherent while preserving all R1 fixes and 16 tests. No backend or architecture change
is allowed. 8D-3B/8D-4 remain unstarted; no commit was created.

## DS-STAGE8D-REVIEW-PAGE-01 R2 completion

### Files changed

- `frontend/src/app/PdfReviewPage.tsx` — move-prefix semantics correction (comment + condition).
- `frontend/src/app/PdfReviewPage.test.tsx` — R2 fixture corrections (16 tests preserved).
- `docs/agent/HANDOFF.md` — this evidence.

No backend/contract/`App.tsx`/`SourcesPage.tsx`/global CSS/dependency/PLANS change; no
8D-3B/8D-4 work; no commit/stage/unstage/reset; no probe files. All R1 fixes retained.

### Corrections applied (per PLANS.md R2)

1. **Pre-move `side_to_move`.** The authoritative normalizer compares
   `node.side_to_move` with `board.turn` before pushing, so e4 carries `w` and e5/c5 carry `b`.
   Fixtures, the component comment and the prefix condition are corrected:
   `side_to_move === 'w'` renders `N. move` and `'b'` renders `N... move`. No FEN inference in
   React; no backend edit. The focused tests contain no post-move-side claim.
2. **Exact normalized FENs** (`fen(en_passant="fen")`):
   - after e4: `rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1`
   - after e4 e5: `rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2`
   - after e4 c5: `rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2`
   Each child's `fen_before` equals the corrected e4 `fen_after`.
3. **Dedicated frozen custom-FEN fixture.** New `customFenItems()` with the one-node legal
   sequence: initial `8/8/8/4k3/8/8/8/4K3 w - - 0 1`, move `Kd2` (`side_to_move='w'`,
   `move_number=1`, SAN `Kd2`, UCI `e1d2`), after `8/8/8/4k3/8/8/3K4/8 b - - 1 1`. The
   custom-FEN test no longer mutates `initial_position` of the startpos tree; it renders this
   fixture, asserts the board initial FEN, navigates `1. Kd2` to the exact `fen_after`, and
   asserts coherent inspection counts (`问题 0 · 阻断 0 · 内容项 1 · 棋步 1`). `baseDocument` now
   computes `move_node_count` from the items so every fixture's inspection is coherent (base:
   5 nodes; custom: 1 node); the `sequenceInitial` override was removed.
4. **Coherent second run.** The run-identity regression's second document reuses
   `customFenItems()` with pages 5/6 (`RUN_ID_2` URLs) inside the declared 5..6 range and
   evidence page 5, zero issues. It proves the mounted instance resets from the user's selected
   page 6 back to the second run's page-5 URL (including `RUN_ID_2`) and the board to
   `CUSTOM_INITIAL_FEN`, while the same-run revalidation still preserves navigation.
5. **All R1 fixes and all 16 tests preserved.** Move-label expectations remain `1. e4`,
   `1... e5`, `1... c5` for the corrected pre-move sides.

### Focused gates (packet-verbatim)

```
pnpm --dir frontend exec vitest run src/app/PdfReviewPage.test.tsx
                                       → 1 file passed, 16 tests passed
pnpm --dir frontend exec prettier --check src/logic/api/types.ts
  src/app/PdfReviewPage.tsx src/app/PdfReviewPage.test.tsx
                                       → All matched files use Prettier code style!
pnpm --dir frontend exec eslint (3 files) --max-warnings=0
                                       → clean
pnpm --dir frontend typecheck          → clean (tsc -b, exit 0)
git diff --check                       → clean
```

### Assumptions

- `side_to_move` on a CCEF node is the side that is about to play the move (pre-move), matching
  the authoritative normalizer's `board.turn` comparison before `board.push`.
- The custom-FEN and second-run documents are type-correct and internally coherent
  (pages/evidence within the declared range; inspection counts derived from the items).

### Status

**Pending Codex final re-review.** 8D-3B/8D-4 not started; no commit created.

## Codex final review — DS-STAGE8D-REVIEW-PAGE-01 R2 accepted

Accepted on 2026-08-14 after inspection against the generated review contract and authoritative
backend normalizer. Independent focused results: `PdfReviewPage.test.tsx` 16/16 passed; Prettier,
ESLint and TypeScript passed for the owned frontend files; `git diff --check` was clean. R2 now
encodes the actual pre-move `side_to_move` semantics, exact en-passant-preserving FENs, a legal
custom-FEN Kd2 sequence and internally consistent second-run page/evidence data. The R1
run-identity reset, derived types and scoped issue navigation remain correct, as do the sanitized
Markdown, no-mutation and read-only UI boundaries. No broad suite was run and no commit was made.

The next manually relayed task is `DS-STAGE8D-REVIEW-INTEGRATION-01 (8D-3B)` in `PLANS.md`. It owns
only the application route/adapter, the eligible Sources-run link and their focused tests. The
accepted review component, backend/contracts, styles and all edit/approval/publication behavior
remain read-only. Once 8D-3B passes Codex review, the current review document will be reachable for
browser interaction; 8D-4 must not begin before then.

## DS-STAGE8D-REVIEW-INTEGRATION-01 (8D-3B) completion

### Files changed

- `frontend/src/app/App.tsx` — lazy-loaded `PdfReviewPage` + `/sources/pdf-extractions/:runId/review`
  route + `PdfReviewPageAdapter`.
- `frontend/src/app/App.test.tsx` — route/NotFound tests with a mocked lazy review page.
- `frontend/src/app/SourcesPage.tsx` — `打开审核页面` link in the committed-candidate section.
- `frontend/src/app/WorkbenchPages.test.tsx` — link present/absent oracles.
- `docs/agent/HANDOFF.md` — this evidence.

No `PdfReviewPage`/backend/contract/generated types/global CSS/dependency/Makefile change; no
edit/approve/reject/publish behavior; no 8D-4 work; no commit/stage/unstage/reset; no probe files.

### Route behavior

1. `App.tsx` lazy-loads the named `PdfReviewPage` export consistently with the existing lazy
   pages and registers exactly `/sources/pdf-extractions/:runId/review`.
2. `PdfReviewPageAdapter` reads `runId` with `useParams`; a missing value renders the existing
   `NotFound`; otherwise the exact decoded string is passed once to `<PdfReviewPage runId={runId} />`.
   No UUID validation or fetching in the adapter.
3. The adapter renders a compact header with semantic `h1` `AI 棋书审核` and a React Router link
   `← 返回资料` to `/sources`; the global app header and Sources nav selection (pathname starts
   with `/sources`) are unchanged. No approval/edit/publish actions.

### Sources entry behavior

- Each extraction run card with non-null `run.candidate` renders exactly one React Router link
  `打开审核页面` inside the committed-candidate section after the count/hash summary, with href
  exactly `/sources/pdf-extractions/${encodeURIComponent(run.id)}/review`.
- The link stays available with `run.has_conflicts` true and false (conflicts are a reason to
  review). No link for queued/running/failed/cancelled runs, historical v1 runs, or successful v2
  runs with `candidate === null`. No review GET from Sources, no availability probe, no polling
  change, no raw/provider/path values.

### Focused oracle (41 tests across the three files, all pass)

- App.test: the review route renders the `AI 棋书审核` heading and `← 返回资料` link, passes the
  exact decoded `runId` (`run%20abc` → `run abc`) exactly once, and makes no API request;
  an unrelated path and a review-shaped path missing the runId render `NotFound`.
- WorkbenchPages: one `打开审核页面` link with the exact href for a committed v2 candidate with
  `has_conflicts=true` and with `has_conflicts=false`; absent for v2 succeeded + null candidate,
  historical v1 without candidate, and queued/running/failed/cancelled runs. Existing candidate
  counts, short hashes, conflict tag, polling and no-secret oracles preserved.

### Focused gates (packet-verbatim)

```
pnpm --dir frontend exec vitest run \
  src/app/App.test.tsx src/app/WorkbenchPages.test.tsx src/app/PdfReviewPage.test.tsx
                                       → 3 files passed, 41 tests passed
pnpm --dir frontend exec prettier --check (4 files)
                                       → All matched files use Prettier code style!
pnpm --dir frontend exec eslint (4 files) --max-warnings=0
                                       → clean
pnpm --dir frontend typecheck          → clean (tsc -b, exit 0)
git diff --check                       → clean
```

### Assumptions

- React Router decodes URL params, so the adapter passes the exact decoded `runId` string; the
  Sources link encodes `run.id` with `encodeURIComponent` before routing.
- The `runId === undefined` branch is defensive (React Router always provides the param for a
  matched route); `NotFound` rendering is covered by the unrelated/missing-segment route tests.

### Remaining risks

- The adapter is a thin pass-through; any future validation (e.g., UUID shape) intentionally
  belongs to the backend route, per the packet boundary.

### Status

**Pending Codex review.** 8D-4 not started; no commit created.

## Codex final review — DS-STAGE8D-REVIEW-LAYOUT-01 accepted

Accepted on 2026-08-14 after inspecting `reviewMoveLayout.ts`, its conservation/branching tests,
the responsive scroll containers and the updated move-row rendering. Codex independently reran the
focused gate: 5 helper tests plus 18 component tests passed; Prettier, ESLint and TypeScript passed
for the four owned files; `git diff --check` was clean.

The implementation preserves source order and node identity, pairs only compatible adjacent
white/black plies, keeps arbitrary primary lines at depth zero, increments indentation only at
alternative sibling edges, and presents row evidence as an ordered unique union. At wide
breakpoints the source and candidate panes own independent scrolling while the board is outside
both panes. A minor internal fallback-row type comment is broader than the actual defensive state,
but rendering and conservation remain correct and it is not a blocker.

8D-3C code is accepted, but the overall 8D-3 interaction checkpoint remains open until the user
refreshes the real browser page and confirms scrollbar geometry and reading density. Do not begin
8D-4 before that visual checkpoint. No broad suite or commit was run.

## Codex architecture handoff — annotated score correction before 8D-4

On 2026-08-14 the user identified a deeper real-book mismatch: prose can interrupt one continuous
main score, contain local/nested parenthesized variations branching from an earlier position, and
then return to the original main line. Rebuilding each variation from move one is incorrect. The
user also wants position/move explanations represented as atomic in-score notes rather than one
large paragraph.

ADR 0017 and `docs/architecture/ccef-v1.1.md` now freeze the correction. CCEF 1.0 and all existing
artifacts remain immutable. CCEF 1.1 adds sequence-local atomic annotations and an exact-cover
reading flow; chess topology remains exclusively `parent_id + sibling_order`. Semantic annotation
anchors and source display placement are deliberately separate. Narrative prose remains a top-level
item, and no punctuation-regex sentence splitting or source-specific special case is permitted.

`PLANS.md` inserts 8D-3D1..5 before the review ledger. The active bounded Flash packet is
`DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01 (8D-3D1)`: implement only the frozen 1.1 contract, generated
Schema and synthetic tests in the named boundary. Provider/prompt/consolidation/review/UI/SQL and
real-book processing remain untouched. Pending DeepSeek implementation; no tests were run for this
documentation-only planning change and no commit was created.

## Codex final review — DS-STAGE8D-REVIEW-INTEGRATION-01 accepted

Accepted on 2026-08-14 after inspecting the actual routing, Sources link and test changes.
Independent focused results: 41/41 tests passed across `App.test.tsx`,
`WorkbenchPages.test.tsx` and the accepted `PdfReviewPage.test.tsx`; Prettier, ESLint and
TypeScript passed for the four integration-owned files; `git diff --check` was clean. The route
adapter performs no validation or I/O, passes the decoded parameter exactly once, and retains the
Sources navigation context. The run card exposes one review link only from the public committed
candidate summary; conflict status does not hide it, and Sources performs no review probe or
mutation. No broad suite or commit was run.

Stage 8D-3 is complete. The next action is an explicit user interaction checkpoint against the
existing five-page run: open `/sources`, follow `打开审核页面`, and assess source-page readability,
board/evidence navigation, ordered prose/move rendering, issues and responsive layout. Do not start
the architecture-sensitive 8D-4 ledger/migration work until that feedback is accepted or converted
into bounded corrections.

## Stage 8D browser checkpoint — layout corrections required

The first real five-page browser review exposed two clear presentation blockers. The long
candidate/issues column scrolls the whole document and pushes both the source page and board out of
view. Move sequences also render every ply on its own line and derive indentation from ordinary
parent-chain depth, so a linear game progressively collapses into a narrow vertical strip.

The active manually relayed packet is `DS-STAGE8D-REVIEW-LAYOUT-01 (8D-3C)` in `PLANS.md`. It freezes
a wide-screen viewport workbench with independent source/candidate scroll panes and a pure,
source-conserving move-row projection: normal white/black plies share one Lichess-style fullmove
row, row evidence is deduplicated, and indentation increases only at `sibling_order>0` alternative
edges. Black-only variations use an explicit `N...` gutter and empty white cell. Backend/contracts,
global CSS and all review mutations remain excluded. Do not begin 8D-4 until this correction passes
Codex review and another browser check.

## DS-STAGE8D-REVIEW-LAYOUT-01 (8D-3C) completion

### Files changed

- `frontend/src/app/reviewMoveLayout.ts` (new) — pure `buildReviewMoveRows` projection.
- `frontend/src/app/reviewMoveLayout.test.ts` (new) — 5 pure helper tests.
- `frontend/src/app/PdfReviewPage.tsx` — wide-screen workbench grid + row-based `MoveSequenceView`
  (`MoveRow`/`MoveCell`), removed `nodeDepthMap` and the per-node `<ol>`.
- `frontend/src/app/PdfReviewPage.test.tsx` — 18 component tests (16 updated/preserved + 2 new).
- `docs/agent/HANDOFF.md` — this evidence.

No App/Sources/backend/contract/generated types/global CSS/dependency/Makefile change; no 8D-4
work; no commit/stage/unstage/reset; no probe files.

### Move-row projection rules (`reviewMoveLayout.ts`)

- Nodes are consumed exactly once in their existing array order; never sorted, deduplicated,
  mutated or tree-walked. Flattening every row's white/black/fallback nodes in visual order
  reproduces the exact input array by object identity (conservation oracle).
- Topological variation depth: root with `sibling_order=0` → 0, later root → 1; a child inherits
  its parent's depth and adds 1 only when its own `sibling_order>0`; defensive missing parent → 0.
  An arbitrarily long primary line never indents; the first alternative indents once; nested
  alternatives add one level each.
- A following node fills the pending white row's black cell only when all hold: same move number,
  pre-move `side_to_move='b'`, `parent_id` equals the white node id, `sibling_order=0`, and equal
  variation depth. Otherwise it starts a new black-only row.
- Black-only rows have a null white cell (gutter `N...`); white-only rows leave the black cell
  empty; nodes with null side/move number become full-width fallback rows (never hidden).
- Row evidence pages are the ordered first-seen union of the contained node evidence; sequence
  evidence is not included in move rows.

### Move-row rendering

- Compact three-column grid (gutter | white | black). Paired rows show `N.` + both moves; black-only
  rows show `N...` with an explicitly empty white cell; fallback rows span both move cells. The move
  number never repeats inside the move button (button text is the source `move_text` only).
- Horizontal indentation uses only `row.variationDepth`, capped visually at 4 levels with the
  uncapped depth on `data-variation-depth`; linear primary rows always have zero padding. Depth>0
  rows get a subtle left border/background.
- Each present node keeps its own backend validation label and NAGs; only `valid` with
  `fen_after` is a button; invalid/ambiguous remain visible and non-navigable. Row evidence appears
  once below the move cells for the whole row.

### Wide-screen scrolling behavior

- At `lg`+, the root grid occupies one viewport work area (`lg:h-[calc(100vh-9rem)]`,
  `lg:overflow-hidden`, `lg:grid-cols-3`). The source pane (`aria-label="原书页面"`) and candidate
  pane (`aria-label="候选内容与自动检查"`, `tabIndex={0}`) each fill that height
  (`lg:h-full lg:min-h-0`) with their own `lg:overflow-y-auto` + `lg:overscroll-contain`; the board
  column stays fixed and outside both scroll panes. Scrolling the candidate pane cannot move the
  page image or board.
- Below `lg`, the fixed height and independent-overflow constraints are absent, so the stack remains
  ordinary document flow (source → board → candidate/issues). Tailwind utility classes only; no
  global CSS or viewport JavaScript.

### Focused oracle (23 tests, all pass)

- Pure helper: 12-ply line → 6 paired depth-0 rows with identity conservation and one evidence
  page per same-page pair; two-page pair exposes `[319, 320]` once; alternative black `1... c5`
  becomes a depth-1 black-only row whose primary descendants do not deepen while a nested
  alternative reaches depth 2; incompatible/nonconsecutive nodes never pair and null-side nodes
  survive as fallback rows without mutating input; later fullmoves of a 20-ply line stay
  unindented and not one-node-per-row.
- Component: linear white/black pair renders on one visual row with one row-level page control,
  zero indentation, preserved board navigation/status/NAG; branching fixture renders rows in source
  order with `1.`/`1...` gutters, depth-0 pair and depth-1 alternative/fallback rows; same-page
  pair UI test; wide-root/source/candidate frozen responsive classes, accessible labels, tabindex,
  and the board outside both scroll panes; all page switching, anchors, XSS sanitization, issues,
  run-identity reset and no-mutation tests still pass.

### Focused gates (packet-verbatim)

```
pnpm --dir frontend exec vitest run \
  src/app/reviewMoveLayout.test.ts src/app/PdfReviewPage.test.tsx
                                       → 2 files passed, 23 tests passed (5 helper + 18 component)
pnpm --dir frontend exec prettier --check (4 files)
                                       → All matched files use Prettier code style!
pnpm --dir frontend exec eslint (4 files) --max-warnings=0
                                       → clean
pnpm --dir frontend typecheck          → clean (tsc -b, exit 0)
git diff --check                       → clean
```

### Assumptions

- CCEF guarantees topological node order (parent before child) and contiguous `sibling_order`
  under each parent, so the depth pass is a single forward scan.
- `side_to_move` is the pre-move side; the pair rule requires the black node's `parent_id` to be
  the white node id, `sibling_order=0`, equal move number and equal variation depth.
- Wide-screen behavior is exercised at the class/attribute level in jsdom (no real viewport
  measurement); visual verification requires a browser check.

### Remaining risks

- jsdom cannot verify actual scroll mechanics; the frozen Tailwind classes encode the contract and
  need a browser confirmation.
- The depth cap (4) is purely visual; `data-variation-depth` retains the uncapped value for
  future styling or tooling.

### Status

**Pending Codex review.** 8D-4 not started; no commit created.

## DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01 (8D-3D1) completion

### Files changed

- `backend/src/chess_workbench/extraction/contracts.py` — added the CCEF 1.1 annotated
  move-sequence profile (ADR 0017) without changing any v1 model, constant, schema function or
  canonical byte.
- `backend/tests/test_extraction_contract_v1_1.py` (new) — 35 focused synthetic tests.
- `contracts/chess-content-extraction-v1.1.schema.json` (new, generated) — written from
  `ccef_v1_1_schema_canonical_json()`; not hand-edited.
- `docs/agent/HANDOFF.md` — this evidence.

No provider/prompt/decoder/candidate/consolidation/review/API/frontend/DB change; no dependency
install; no commit/stage/unstage/reset; no probe files.

### Public names and shapes added

- `CCEF_VERSION_1_1 = "chess-content-extraction/1.1"`, `SCHEMA_ID_1_1 =
  "urn:chess-content-extraction:schema:1.1"`.
- Strict models `MoveNodeAnnotationAnchor` (kind/node_id/relation before|after),
  `PositionAnnotationAnchor` (kind/fen), `SequenceAnnotation` (id/text 1..200000/text_format
  default plain/anchor/evidence non-empty/confidence/warnings/extensions),
  `MoveFlowRef`, `AnnotationFlowRef`, `MoveSequenceItemV1_1` (common item fields + title/
  initial_position/nodes non-empty/annotations default []/reading_flow non-empty),
  `ExtractionPackageV1_1`.
- Discriminated unions `SequenceAnnotationAnchor`, `SequenceFlowEntry` (discriminator `kind`),
  `ExtractionItemV1_1`.
- Deterministic `ccef_v1_1_schema_document()` / `ccef_v1_1_schema_canonical_json()`: Draft
  2020-12 dialect, frozen 1.1 ID, injected UTC `created_at` pattern; reused the shared v1 value
  classes (`MoveNode`, `EvidenceRef`, `Provenance`, `PageRange`, `_ItemBase`, etc.) rather than
  copying field shapes. All new objects use `extra="forbid"` + strict typing. Validators do not
  mutate inputs and do not import `python-chess`/provider/HTTP/SQL/review modules.

### Validators (`ExtractionPackageV1_1`)

Enforces every v1 package invariant (duplicate item ids, page-range containment for all evidence
including annotation + annotation-warning evidence, top-level prose anchors and diagnostic refs
against 1.1 sequences) plus per-sequence: duplicate node/annotation ids and node/annotation id
collision; dangling/forward/self parents; non-contiguous sibling orders; absent move-node
annotation anchor; absent flow targets; duplicate move/annotation flow refs; move-ref projection
must equal `nodes` IDs in exact array order; annotation-ref projection must equal `annotations`
IDs in exact array order. `reading_flow` stays non-empty even when `annotations=[]`. Schema
generation preserves discriminator `propertyName` values and `additionalProperties:false` at
every new object boundary.

### Focused oracle (35 new tests, all pass)

- Fully valid synthetic 1.1 package: primary line through White's sixth move, two atomic notes
  plus one null-anchored note displayed in reading flow, an alternative White sixth move sharing
  the earlier common fifth-move parent, a nested variation, and a later primary Black sixth move
  whose parent remains the primary White sixth move; exact move/annotation projection order, JSON
  round trip, defaults, frozen-input/non-mutation, deterministic repeated Schema bytes.
- Every rejection in the frozen validator list, unknown fields, strict scalar/container types,
  empty annotation evidence, anchor before/after/position/null, evidence boundaries/defaults.
- Schema artifact byte-for-byte drift check, 1.1 version/ID/discriminators/`additionalProperties`
  at new boundaries, and explicit regression that `ccef_schema_canonical_json()` still equals the
  checked-in v1 artifact and a representative v1 package still validates.

### Focused acceptance commands (packet-verbatim)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_contract_v1_1.py
                                       → 76 passed (41 v1 + 35 v1.1)
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- The three-annotation synthetic oracle interleaves annotations at fixed invented display
  positions; annotation entries in `reading_flow` are derived from the actual annotation list so
  `annotations=[]` yields an all-move flow.
- The schema discriminator for the nullable `anchor` is nested inside `anyOf[0]` (as Pydantic
  emits it); tests assert the exact path.
- The v1 package regression uses a real `MoveSequenceItem` (1.0) to prove v1 behavior is
  untouched.

### Remaining risks

- Contract validation remains structural/referential only; chess legality, sentence-boundary
  inference and FEN derivation stay in later producer/consumer stages per ADR 0017.
- The 1.1 models are not yet exported from the extraction package `__init__` (read-only boundary);
  downstream provider/decoder/consolidation packets will wire exports when they consume 1.1.

### Status

**Pending Codex review.** 8D-3D2 not started; no commit created.

## Codex review — DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01 R1 required

Codex independently reproduced the focused gate on 2026-08-14: 76/76 contract tests passed; Ruff
format/check and MyPy passed for the two owned Python files; `git diff --check` was clean. The first
`uv` invocation was blocked before collection by the sandbox's read-only default cache, then the
same command passed with repository-local `UV_CACHE_DIR`/`UV_PYTHON_INSTALL_DIR` and no dependency
change.

One pre-producer blocker remains. `_check_sequence` uses list membership for every move/annotation
flow duplicate check, making large untrusted reading flows O(n²). Its projection mismatch messages
also embed complete actual/expected ID arrays. R1 is frozen in the active packet: use separate seen
sets while retaining ordered projections, emit bounded relation-only mismatch messages, preserve
all behavior/Schema bytes, add focused message regressions and rerun the same gate. 8D-3D1 remains
pending and 8D-3D2 must not start. No implementation file was changed by Codex and no commit was
created.

## DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01 (8D-3D1) R1 completion

### Files changed

- `backend/src/chess_workbench/extraction/contracts.py` — `_check_sequence` R1 correction only.
- `backend/tests/test_extraction_contract_v1_1.py` — 2 new focused regression tests.
- `docs/agent/HANDOFF.md` — this evidence.

No other file changed; no Schema byte change; no commit/stage/unstage/reset.

### Corrections applied (per PLANS.md R1)

1. Ordered `move_refs` / `annotation_refs` lists are now used only for the final exact-order
   projection comparison. Duplicate detection uses dedicated `seen_move_refs` / `seen_annotation_refs`
   `set[str]` values, making duplicate checks O(1) average while the overall pass stays linear
   (absent-target checks were already set-based).
2. The two projection mismatch messages no longer interpolate the complete actual/expected ID
   arrays; they now name the relation and the sequence only:
   `move flow projection differs from nodes in sequence 'seq1'` and
   `annotation flow projection differs from annotations in sequence 'seq1'`.
3. All frozen validation behavior is preserved: duplicate/absent/projection rejections still fire,
   and both the v1 and v1.1 Schema canonical bytes are byte-for-byte unchanged (verified against
   both checked-in artifacts).
4. New focused regressions (no wall-clock timing, no AST/source assertions):
   - `test_duplicate_flow_references_still_rejected_with_clear_messages` — move and annotation
     duplicates still raise with `duplicate flow move/annotation reference` in the error message.
   - `test_projection_mismatch_messages_are_bounded_and_omit_id_collections` — mismatch errors
     contain only the fixed relation text + sequence id, contain no node/annotation IDs (`n1`/`a1`
     absent from the per-error message), and are under 200 characters.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_contract_v1_1.py
                                       → 78 passed (41 v1 + 37 v1.1)
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- Error messages were not frozen by the original oracle (tests assert `ValidationError` only), so
  the bounded-message change does not weaken any existing behavior.
- The per-error `msg` (not `str(ValidationError)`, which embeds the input payload) is the correct
  boundary for the bounded-message assertions.

### Remaining risks

- None new; structural/referential-only validation unchanged, and 1.1 package exports remain out
  of scope for downstream packets.

### Status

**Pending Codex re-review.** 8D-3D2 not started; no commit created.

## Codex final review — DS-STAGE8-ANNOTATED-SCORE-CONTRACT-01 accepted

Accepted on 2026-08-14. Codex inspected the actual CCEF 1.1 models, package/sequence validators,
canonical Schema artifact, 37-test synthetic oracle and R1. Independent focused rerun: 78/78 tests
passed; Ruff format/check and MyPy passed for the owned Python files; `git diff --check` was clean.

R1 correctly retains ordered lists only for exact projection comparison, uses separate seen sets
for average-O(1) duplicate checks, and emits bounded relation-only projection errors. The tests
assert behavior/messages without wall-clock, AST or source-text coupling. Existing CCEF 1.0
canonical bytes and representative package behavior remain unchanged. 8D-3D1 is accepted; no full
suite, provider call or commit was performed.

The next active packet is `DS-STAGE8-ANNOTATED-SCORE-PROTOCOL-01 (8D-3D2A)` in PLANS.md. It adds
version-explicit CCEF 1.1 request construction and response decoding while preserving v1 entry
points. It does not wire candidates/workers/artifacts and must stop before 8D-3D2B.

## DS-STAGE8-ANNOTATED-SCORE-PROTOCOL-01 (8D-3D2A) completion

### Files changed

- `backend/src/chess_workbench/extraction/prompting.py` — added `CCEF_PROMPT_VERSION_1_1`
  (`chess-workbench/ccef-prompt/1.4`), `build_ccef_v1_1_generation_request`,
  `_SYSTEM_CONTENT_1_1` (v1 rules + frozen 1.1 semantics), the 1.1 evidence skeleton
  (schema version 1.1, adapter version `1.1`) and the 1.1 response schema with the same
  no-FEN narrowing as v1 (`$defs.MoveSequenceItemV1_1.properties.initial_position` →
  `StartPosition`). v1 request construction is byte/behavior compatible.
- `backend/src/chess_workbench/extraction/decoder.py` — added
  `decode_extraction_response_v1_1(response) -> ExtractionPackageV1_1`; refactored v1 and v1.1 to
  share one private `_parse_payload` + `_validate_payload` (PEP 695 constrained type parameter)
  with identical truncation/JSON/root/unvalidated-only/exception-detachment behavior. v1 public
  behavior unchanged (all 85 v1 tests green).
- `backend/tests/test_extraction_prompting_v1_1.py` (new) — 10 tests.
- `backend/tests/test_extraction_decoder_v1_1.py` (new) — 13 tests (parametrized).
- `docs/agent/HANDOFF.md` — this evidence.

No `extraction/__init__.py`, contracts/Schema artifacts, provider/candidates/consolidation,
services/worker/config, API/generated types, review/UI/SQL, dependency or Makefile change; no
provider call; no commit/stage/unstage/reset; no probe files.

### Request API

- `CCEF_PROMPT_VERSION_1_1 = "chess-workbench/ccef-prompt/1.4"`; schema name
  `chess_content_extraction_v1_1`; same `CcefPromptContext`, evidence limits, injection boundary,
  deterministic compact JSON (`ensure_ascii=False, allow_nan=False, sort_keys=True`), sanitized
  `CcefPromptError` codes and caller-independent deep-copied snapshots as v1. The user document
  keeps the `{prompt_version, package, evidence_pages}` shape with the 1.1 skeleton
  (`adapter_version "1.1"`). No-FEN context narrows the 1.1 `initial_position` to StartPosition;
  an explicit six-field FEN retains the full union. Both canonical Schemas are unchanged.

### Prompt semantics (frozen clauses asserted individually, never as one brittle string)

Continuous numbered line stays one move sequence across pages/paragraphs/diagrams/annotations/
fragments; every node emitted once parent-before-child in source encounter order; local
variations share the real preceding parent without repeating the common prefix; mainline
`sibling_order=0` with contiguous alternatives; `reading_flow` covers every node and annotation
exactly once in source display order and never defines parentage; annotations are atomic
semantic assertions with their own evidence, not split at names/abbreviations/move-number/
chess punctuation; move-node anchors are semantic before/after while `reading_flow` location is
display; null anchor instead of guessing; narrative background stays top-level prose;
move-looking explanatory prose is not a move node without a unique earlier attachment, and never
guess a parent or restart from move one. All inherited v1 rules (untrusted data, unvalidated
nodes, no invented FEN) remain in the 1.1 system message.

### Decoder API and trust boundary

`decode_extraction_response_v1_1` is version-explicit: a 1.0 payload is `invalid_package` (and
the v1 decoder rejects a 1.1 payload). Both decoders share the single private parse/trust path:
truncation wins before reading content; duplicate keys at any depth, non-standard constants and
non-object roots are `invalid_json`; provider nodes may only be unvalidated (any `valid`/
`invalid`/`ambiguous` status or non-null `san_candidate`/`uci_candidate`/`fen_before`/`fen_after`
is `untrusted_validation` before package validation); every remaining structural/reference
failure (dangling annotation/flow refs, projection mismatch, unknown fields) is the sanitized
`invalid_package`. Public errors retain no raw provider text or rejected values, and the
response object is never mutated.

### Focused oracle (108 tests, all pass; v1 files unchanged and green)

- New prompting tests: deterministic request/schema/skeleton/version; no-FEN narrowing and
  explicit-FEN retention (`oneOf` union); frozen semantic clauses; injection isolation;
  caller/schema snapshots; size/range/type validation (`input_too_large`, `invalid_evidence`,
  TypeError); context non-mutation; v1 builder/version compatibility; AST import purity
  (relative imports exactly `{contracts, evidence, provider}`).
- New decoder tests: valid 1.1 decode with interleaved annotations, earlier-parent alternative
  (`n12` parent `n10` sibling 1) and later mainline continuation (`n16` parent `n11`), defaults
  and response non-mutation; cross-version rejection in both directions; five invalid-structure
  parametrizations → `invalid_package`; JSON trust boundary (duplicate keys, truncation,
  non-object root, NaN) matching v1 codes; three untrusted-claim parametrizations; marker
  hygiene for both invalid_json and invalid_package; subprocess import purity.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_prompting.py \
  backend/tests/test_extraction_prompting_v1_1.py \
  backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_decoder_v1_1.py
                                       → 108 passed (85 v1 + 23 new)
uv run --project backend --locked ruff format --check (4 files)
                                       → 4 files already formatted
uv run --project backend --locked ruff check (4 files)
                                       → All checks passed!
uv run --project backend --locked mypy (4 files)
                                       → Success: no issues found in 4 source files
git diff --check                       → clean
```

### Assumptions

- The 1.1 system message appends the frozen semantics to the accepted v1 content; the v1
  content string is untouched, so v1 request bytes are unchanged.
- The 1.1 response-schema narrowing mirrors v1 exactly, targeting the 1.1 move-sequence member
  (`MoveSequenceItemV1_1`); the un-narrowed 1.1 union uses `oneOf` + discriminator (asserted
  accordingly in tests).
- The decoder refactor preserves the exact raise-after-handler pattern, so exception-chaining
  hygiene is identical to the accepted v1 decoder.

### Remaining risks

- The 1.1 names are not exported through `extraction/__init__.py` (read-only boundary); the
  provider/candidate/worker wiring packet (8D-3D2B+) will add exports when consuming 1.1.
- Prompt ordering is non-normative; tests assert semantic clauses, not the full string.

### Status

**Pending Codex review.** 8D-3D2B not started; no commit created.

## Codex final review — DS-STAGE8-ANNOTATED-SCORE-PROTOCOL-01 accepted

Accepted on 2026-08-14. Codex inspected the actual 1.1 prompt builder, semantic clauses, no-FEN
Schema narrowing, generic decoder factoring and 23 new tests. Independent focused rerun: 108/108
tests passed; Ruff format/check and MyPy passed for the four owned files; `git diff --check` was
clean.

The v1 builder/version and decoder remain compatible. The v1.1 path is version-explicit, retains
the injection/evidence/unvalidated/no-invented-FEN boundaries, encodes continuous score/shared
branch/reading-flow/atomic-note semantics and rejects cross-version or malformed provider output
with detached sanitized errors. No full suite, provider call or commit was performed.

Dependency review found that candidate/worker wiring cannot safely be the immediate next packet:
the assembler always produces a locally normalized artifact, while the accepted normalizer and
consolidator currently accept only `ExtractionPackage` 1.0. PLANS therefore freezes the next order
as **8D-3D3A normalizer → 8D-3D3B consolidation → 8D-3D2B pipeline wiring**. The active packet is
`DS-STAGE8-ANNOTATED-SCORE-NORMALIZER-01 (8D-3D3A)`; it must preserve annotations and exact reading
flow and stop before consolidation/wiring.

## DS-STAGE8-ANNOTATED-SCORE-NORMALIZER-01 (8D-3D3A) completion

### Files changed

- `backend/src/chess_workbench/extraction/validation.py` — added
  `normalize_chess_moves_v1_1(package: ExtractionPackageV1_1) -> ExtractionPackageV1_1` and
  widened the private `_normalize_sequence` to the union
  `MoveSequenceItem | MoveSequenceItemV1_1`. The accepted v1 `normalize_chess_moves` signature,
  behavior and all 39 v1 tests are unchanged.
- `backend/tests/test_extraction_validation_v1_1.py` (new) — 9 focused tests.
- `docs/agent/HANDOFF.md` — this evidence.

No contracts/Schema artifact, prompting/decoder, `extraction/__init__.py`, consolidation/
candidate/worker/artifact, service/API/review/UI/SQL, dependency or Makefile change; no provider
call; no commit/stage/unstage/reset; no probe files.

### Frozen API and behavior

`normalize_chess_moves_v1_1` deep-copies the input (never mutates it), reuses the exact accepted
python-chess normalization path (startpos/standard initial-position rule, SAN token cleaning,
move-number/side context checks, null-move rejection, canonical SAN/lowercase UCI, full
six-field before/after FEN, stable validator warnings) for every `MoveSequenceItemV1_1`, and
revalidates the result through `ExtractionPackageV1_1`. Board progress follows `parent_id`
topology only; annotations and `reading_flow` are never inspected, split, re-anchored or
reordered and survive byte-for-byte under `model_dump(mode="json")` (verified by a
normalization-stripped equality comparison that also covers sequence id/title/evidence/
confidence/warnings/extensions, non-validator node warnings and all non-move items). Only
move-node normalization fields and validator-warning entries change, exactly as v1. The function
is deterministic and idempotent (re-normalizing yields the same JSON value without duplicating
validator warnings).

### Focused oracle (48 tests, all pass; v1 file unchanged and green)

- A structurally valid 1.1 startpos tree with a legal mainline, an earlier-parent alternative
  (n12 `a3`, parent n10 sibling 1), a nested alternative (n15 `b3`, parent n13 sibling 1) and a
  later primary Black sixth move (n16 `Be7`, parent n11 sibling 0), with three annotations
  interleaved in reading flow. Exact canonical SAN/UCI/before-after FEN asserted for
  representative nodes, proving topology rather than flow adjacency drives the board:
  n16.fen_before == n11.fen_after (not the flow-preceding node/annotation), n12.fen_before ==
  n10.fen_after (earlier parent), and n14/n15 share n13.fen_after as siblings.
- Annotations, reading flow, all non-normalization fields and non-move items compare exactly
  before/after; the input package is unchanged and the output's nested annotation objects are
  independent of the input.
- Illegal (blocked `O-O-O`), context-mismatched (`move_number=7` on e4) and disconnected nodes
  retain their stable validator warnings while annotation anchors and all flow entries remain
  present.
- Repeated normalization is identical and validator warnings never duplicate; a six-field
  king-less initial FEN stays reviewable with `ccef_chess_invalid_initial_position`.
- Import purity: relative imports exactly `{contracts}`; no provider/HTTP/SQL/store/service/
  review/prompting/decoder/validation dependency beyond `python-chess` (AST check).
- Explicit v1 regression: `test_extraction_validation.py` runs unchanged (39 passed).

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_validation.py backend/tests/test_extraction_validation_v1_1.py
                                       → 48 passed (39 v1 + 9 v1.1)
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- `MoveSequenceItemV1_1` is structurally a superset of v1's sequence for the fields the
  normalizer touches (initial_position, nodes), so widening `_normalize_sequence` to the union
  reuses the identical chess logic without copying it.
- The invented tree is chess-legal by construction (verified with python-chess); expected FENs
  are the exact `fen(en_passant="fen")` values.

### Remaining risks

- `normalize_chess_moves_v1_1` is not exported through `extraction/__init__.py` (read-only
  boundary); the consolidation/wiring packets (8D-3D3B/8D-3D2B) will add exports when consuming.
- No annotation-semantics, sentence-splitting or FEN-derivation work happens here by design.

### Status

**Pending Codex review.** 8D-3D3B/8D-3D2B not started; no commit created.

## Codex final review — DS-STAGE8-ANNOTATED-SCORE-NORMALIZER-01 accepted

Accepted on 2026-08-14. Codex inspected the actual `validation.py` diff and the complete synthetic
v1.1 oracle. The implementation is deliberately narrow: it deep-copies and revalidates a 1.1
package while reusing the existing parent-topology python-chess path; it does not interpret
`reading_flow`, rewrite annotations or change the v1 entry point.

Independent focused verification used the repository-local uv cache and passed:

```
pytest test_extraction_validation.py test_extraction_validation_v1_1.py
                                      -> 48 passed
ruff format --check (2 owned files)   -> passed
ruff check (2 owned files)            -> passed
mypy (2 owned files)                  -> passed
git diff --check                      -> clean
```

No full suite, provider call or commit was performed. No review blocker remains. The known missing
package-level export is intentionally deferred until pipeline wiring.

The next packet is now `DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 (8D-3D3B)`. Its frozen design
keeps the v1 consolidator compatible, merges 1.1 legal paths by shared UCI topology, remaps atomic
annotations and exact-cover reading flow, preserves annotations from all-unplayable sequences as
top-level prose, and explicitly forbids the v1 standalone-fragment reconstruction from flattening
inline variations. Candidate/worker wiring and the real pages 319-323 checkpoint remain later
steps.

## DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 (8D-3D3B) completion

### Files changed

- `backend/src/chess_workbench/extraction/consolidation.py` — added
  `consolidate_move_sequences_v1_1` plus the 1.1 annotation/flow/prose helpers, and widened the
  internal group/collection/fallback types to the `MoveSequenceItem | MoveSequenceItemV1_1` union.
  The accepted v1 `consolidate_move_sequences` signature, behavior and all 9 v1 tests are unchanged.
- `backend/tests/test_extraction_consolidation_v1_1.py` (new) — 11 focused tests.
- `docs/agent/HANDOFF.md` — this evidence.

No contracts/Schema, validation, prompting/decoder, `extraction/__init__.py`,
candidates/services/worker/config, API/generated types, review/UI/SQL, dependency or Makefile
change; no provider call; no commit/stage/unstage/reset; no probe files.

### Merged topology rules

- Grouping identity unchanged from v1: current heading scope, exact initial-position model value,
  title and extensions. Never merges across a different group.
- Within a group, only locally normalized `valid` nodes with non-null UCI and a retained legal
  parent path enter the trie; identical root-to-node lowercase-UCI paths merge. Node IDs `n1`,
  `n2`, ... follow deterministic first-encounter order (source sequence order, then node order);
  parent IDs and contiguous sibling order come only from the merged trie. A local or nested
  alternative therefore shares its real common prefix and never restarts from the initial position.
- Merged nodes use the accepted v1 policy (`_build_node`): canonical SAN/context/FEN from the
  first source, stable-union evidence/non-validator warnings, sorted NAG union (including symbolic
  suffixes), max non-null confidence, deep-copied first-source extensions; sequence
  evidence/warnings by stable union, confidence max, first sequence's id/title/initial/extensions.

### Annotation mapping and reading-flow rules

- Output flow scans each source sequence in source item order and each valid input `reading_flow`
  in declared order. Move entries resolve through the merged trie; duplicate-path occurrences and
  omitted nodes are skipped, so the move projection equals the merged `nodes` IDs exactly in array
  order. Annotation entries deep-copy the source annotation exactly once (never deduplicated by
  text/anchor/evidence) and emit their flow entry at that position; the annotation projection
  equals the output `annotations` IDs exactly in array order.
- Annotation IDs are preserved unless they collide with a merged node ID or an earlier retained
  annotation ID, in which case the next deterministic free local ID `a1`, `a2`, ... is assigned and
  used consistently in `annotations` and `reading_flow` (idempotent).
- `MoveNodeAnnotationAnchor` node IDs remap through the source-node trie map with `relation`
  preserved; an omitted source node sets the anchor to null and appends exactly one stable
  `ccef_annotation_anchor_unresolved` warning (fixed message) with a deep copy of the annotation
  evidence (no duplication on repeated consolidation). Position/null anchors survive unchanged;
  every annotation's text, text_format, evidence, confidence, non-generated warnings and
  extensions are preserved exactly.
- Annotation evidence counts as covered source content when omitted-node fallbacks are computed,
  so the same fragment is not emitted twice as fallback data.
- An all-unplayable group keeps its annotations as deterministic top-level `ProseItem`s in source
  order (`consolidation_annotation_<n>` ids): text/format/evidence/confidence/warnings/extensions
  preserved, position anchors kept, move-node anchors nulled with the same one-time warning. The
  invalid move text stays covered by the existing omitted-node fallback policy.
- The 1.1 path never calls `_extract_formal_sequences`; with `evidence_pages` the legal annotated
  tree (including inline variations) is retained from the normalized model, while item ordering and
  omitted-source fallback stay deterministic. Top-level prose anchors and diagnostics remap as in
  v1. The result is revalidated and re-normalized through the 1.1 models.

### Focused oracle (20 tests, all pass; v1 file unchanged and green)

- Two same-group sequences (shared prefix, earlier-parent alternative, nested alternative, later
  mainline continuation) merge into one 17-node tree with correct parents/siblings and no
  duplicated prefix; duplicate paths union evidence/NAGs while distinct annotations never dedup.
- Reading flow is asserted separately from topology: a1 sits right after the n11 mainline move in
  flow while the alternative n12 (parent n10) follows; move and annotation projections both satisfy
  exact cover.
- Annotation move anchors remap (before/after preserved); position/null anchors survive; duplicate
  annotation IDs and annotation-vs-merged-node collisions receive stable free IDs.
- An omitted illegal node keeps its annotation in flow with a null anchor and exactly one sanitized
  warning; repeated consolidation stays idempotent. An all-unplayable sequence retains annotations
  as top-level prose plus the existing move fallback without invalid references.
- Top-level prose anchors and diagnostics remap to merged ids; synthetic `evidence_pages` retain
  the normalized 1.1 tree with the inline alternative (proving fragment reconstruction is unused).
- Input unchanged, output nested objects independent, repeated calls byte-value identical, exact
  type misuse rejected without input values; all 9 existing v1 consolidation tests pass unchanged.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_consolidation.py backend/tests/test_extraction_consolidation_v1_1.py
                                       → 20 passed (9 v1 + 11 v1.1)
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- `MoveSequenceItemV1_1` is a structural superset for the fields the v1 machinery touches
  (initial_position, title, extensions, nodes), so the union widening reuses the accepted trie/
  merge policy without copying it; 1.1-only fields are handled by the new helpers.
- Flow emission order equals merged creation order because each source flow covers its nodes in
  node order and sequences are scanned in source order; the final 1.1 revalidation enforces exact
  cover as a safety net.

### Remaining risks

- `consolidate_move_sequences_v1_1` is not exported through `extraction/__init__.py` (read-only
  boundary); pipeline wiring (8D-3D2B) will add exports.
- Annotation-to-prose fallback and omitted-node behavior are exercised with synthetic fragments
  only; the real pages 319-323 checkpoint remains a later step.

### Status

**Pending Codex review.** 8D-3D2B/8D-3D4 not started; no commit created.

## Codex review — DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 requires R1

Reviewed on 2026-08-14. The main playable-tree, annotation remap and exact-cover flow path is
sound, and Codex independently reproduced the reported focused gate: 20/20 tests passed; Ruff
format/check, MyPy and `git diff --check` passed. The packet is not accepted because the existing
oracle misses two deterministic all-unplayable-group violations.

1. `_annotation_prose_fallbacks` appends `ccef_annotation_anchor_unresolved` unconditionally. In a
   synthetic sequence containing move-node, position and null anchors, all three resulting prose
   items received the warning. Only the removed move-node anchor may receive it; position and null
   anchors must preserve their existing warning lists unchanged.
2. The output loop guards annotation-prose emission with the group-level `emitted` set. A synthetic
   same-group input with two all-unplayable source sequences and four total annotations returned
   only the first sequence's three annotations. The second sequence's annotation was silently lost.

Codex's read-only counterexample reported:

```
prose_count 3  # expected 4
warnings:
  move-node annotation -> ccef_annotation_anchor_unresolved  # expected
  position annotation  -> ccef_annotation_anchor_unresolved  # wrong
  null annotation      -> ccef_annotation_anchor_unresolved  # wrong
```

PLANS now contains the bounded active correction packet
`DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 R1`. It requires conditional warning generation and
per-source annotation-prose emission for all-unplayable groups, with two focused regressions added
to the existing oracle. Do not begin 8D-3D2B or 8D-3D4 until R1 passes Codex re-review.

## DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 R1 (8D-3D3B) completion

### Files changed

- `backend/src/chess_workbench/extraction/consolidation.py` — two R1 fixes in the 1.1
  all-unplayable fallback path only.
- `backend/tests/test_extraction_consolidation_v1_1.py` — strengthened the existing
  all-unplayable test and added 2 focused R1 regressions (13 v1.1 tests total).
- `docs/agent/HANDOFF.md` — this evidence.

No contracts/Schema/validation/candidate/worker/API/UI/database change; the working trie, legal
move merge and reading-flow paths are untouched; no commit/stage/unstage/reset; no probe files.

### R1 fix 1 — conditional unresolved-anchor warning

`_annotation_prose_fallbacks` now appends `ccef_annotation_anchor_unresolved` only when the
original annotation anchor is a `MoveNodeAnnotationAnchor` (converted to a null top-level anchor).
A `PositionAnnotationAnchor` becomes the equivalent top-level `PositionAnchor` with its existing
warnings unchanged; a null anchor stays null with its warnings unchanged. Existing input warnings
are never removed or duplicated; the generated warning is still emitted at most once (the
once-guard remains for re-consolidation).

### R1 fix 2 — per-source annotation prose for multi-sequence all-unplayable groups

The output loop now uses the group-level `emitted` set only to prevent re-emitting a surviving
merged sequence. For a group with no merged sequence (`merged_by_key[key] is None`), annotation
prose is emitted at every source sequence's output location in source item order, each in
annotation projection order. Every source sequence's existing omitted-move fallback stays at its
deterministic location.

### R1 focused regressions (added without weakening the existing tests)

- `test_all_unplayable_anchor_warnings_are_conditional` — one all-unplayable sequence with
  move-node, position and null annotation anchors: only the move-node-derived prose carries
  exactly one unresolved-anchor warning (fixed message); position/null-derived prose retain no
  generated warning; the position anchor value survives as `PositionAnchor`; re-consolidation
  does not duplicate the generated warning.
- `test_two_all_unplayable_sequences_keep_all_annotations_and_fallbacks` — two same-group
  all-unplayable source sequences: all annotations from both sequences appear exactly once in
  source item order (and per-sequence projection order), with collision-free deterministic
  `consolidation_annotation_*` prose IDs; both sequences' omitted-move fallbacks remain (distinct
  evidence pages prove no dedup); re-consolidation of the output is byte-value identical.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_consolidation.py backend/tests/test_extraction_consolidation_v1_1.py
                                       → 22 passed (9 v1 + 13 v1.1)
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- The two-regression fixture sets per-node evidence pages so the two source sequences' omitted
  moves produce distinct fallback signatures (the v1 `_unresolved_fallbacks` dedup is by
  signature, not by sequence).
- Re-consolidation idempotency holds because annotation-derived prose items are non-sequence items
  that pass through unchanged.

### Remaining risks

- None new; both defects were confined to the all-unplayable fallback path and are now covered by
  focused regressions. 1.1 package exports remain deferred to pipeline wiring (8D-3D2B).

### Status

**Pending Codex re-review.** 8D-3D2B/8D-3D4 not started; no commit created.

## Codex final re-review — DS-STAGE8-ANNOTATED-SCORE-CONSOLIDATION-01 accepted

Accepted on 2026-08-14 after R1. Codex inspected both corrected branches and the strengthened
oracles. Independent focused verification passed 22/22 tests; Ruff format/check, MyPy and
`git diff --check` passed. The original read-only counterexample now returns all four source
annotations, with the unresolved-anchor warning only on the annotation whose move-node anchor was
actually removed; position/null annotations carry no generated warning.

The R1 control flow is narrow and correct: a surviving merged sequence remains group-emitted once,
while an all-unplayable group emits each source sequence's annotation prose at that sequence's
location. Position anchors convert to top-level position anchors, null stays null, and only the
remaining move-node-anchor union branch generates the one-time warning. No full suite, provider
call or commit was performed. 8D-3D3 is accepted.

Pipeline review determined that 8D-3D2B must not silently change existing `pdf-extraction:v2`
semantics. The logical fingerprint includes pipeline version; reusing v2 would replay an old CCEF
1.0 run for the same PDF/profile instead of creating a 1.1 artifact, and changing the bytes in the
same immutable artifact slots could conflict. PLANS therefore splits 3D2B into:

1. **3D2B1** pure 1.1 candidate assembly and portable exports;
2. **3D2B2** a new immutable v3 pipeline identity/fingerprint plus version-explicit worker routing,
   keeping v1/v2 execution reproducible;
3. **3D2B3** legacy public-summary/review compatibility so existing v2 runs stay readable while v3
   review consumption waits for 3D5.

The active packet is `DS-STAGE8-ANNOTATED-CANDIDATE-01 (8D-3D2B1)`. It touches only the candidate
assembler, root extraction exports and a new focused test file. It freezes all v1 bytes and adds a
separately versioned 1.1 provider-response artifact with explicit CCEF schema binding.

## DS-STAGE8-ANNOTATED-CANDIDATE-01 (8D-3D2B1) completion

### Files changed

- `backend/src/chess_workbench/extraction/candidates.py` — added
  `CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1 = "chess-workbench/provider-response/1.1"` and
  `assemble_ccef_candidate_artifacts_v1_1`; generalized the private helpers
  (`_canonical_ccef_bytes`, `_package_matches_context` with an explicit adapter-version argument,
  `_summarize` over the package union with annotation-warning counting) over
  `ExtractionPackage | ExtractionPackageV1_1`. v1 behavior/bytes unchanged.
- `backend/src/chess_workbench/extraction/__init__.py` — eager contracts exports
  (CCEF_VERSION_1_1, SCHEMA_ID_1_1, AnnotationFlowRef, ExtractionItemV1_1, ExtractionPackageV1_1,
  MoveFlowRef, MoveNodeAnnotationAnchor, MoveSequenceItemV1_1, PositionAnnotationAnchor,
  SequenceAnnotation, SequenceAnnotationAnchor, SequenceFlowEntry, ccef_v1_1_schema_document,
  ccef_v1_1_schema_canonical_json), eager decoder/prompting exports
  (decode_extraction_response_v1_1, CCEF_PROMPT_VERSION_1_1, build_ccef_v1_1_generation_request),
  and lazy TYPE_CHECKING/`__getattr__`/`__all__` wiring for
  CCEF_PROVIDER_RESPONSE_ARTIFACT_SCHEMA_1_1, assemble_ccef_candidate_artifacts_v1_1,
  consolidate_move_sequences_v1_1 and normalize_chess_moves_v1_1.
- `backend/tests/test_extraction_candidates_v1_1.py` (new) — 12 focused tests.
- `docs/agent/HANDOFF.md` — this evidence.

No contracts/Schema/prompting/decoder/validation/consolidation change in this packet (their diffs
are from prior accepted packets); no services/worker/pipeline/SQL/API/review/UI change; no
provider call; no commit/stage/unstage/reset; no probe files. Both canonical Schemas verified
byte-identical.

### Assembler behavior

`assemble_ccef_candidate_artifacts_v1_1` is version-explicit (never dispatches by response
content): same exact input-type boundary and sanitized `CcefCandidateError` behavior as v1;
rebuilds the trusted request with `build_ccef_v1_1_generation_request` and requires exact
equality; decodes only via `decode_extraction_response_v1_1` (a 1.0 package / wrong version /
malformed JSON / unknown field follow the accepted decoder errors without leakage); binds the
decoded package to context metadata requiring adapter name `chess-workbench-ccef-prompt`,
adapter version `1.1`, null provider/model/request/response hashes and empty extensions; computes
request/response SHA-256 exactly as v1; deep-copies the decoded package, binds trusted
provider/model/hash provenance and revalidates as `ExtractionPackageV1_1` without mutating
context/request/response/decoded data; calls `consolidate_move_sequences_v1_1(raw_package,
context.pages)` exactly once; serializes raw and normalized packages with the accepted compact
sorted UTF-8 canonical JSON plus one trailing newline; emits the 1.1 provider-response artifact
with `artifact_schema` = the new 1.1 constant plus exactly one version binding field
`ccef_schema_version: "chess-content-extraction/1.1"` (v1 provider-response document unchanged);
returns the existing frozen `CcefCandidateArtifacts`/`CcefCandidateSummary` types, counting 1.1
move nodes/figures/unresolved items exactly as v1, including annotation warnings in
`warning_count` and letting them contribute to `has_conflicts` (no annotation-count field added).

### Focused oracle (41 tests, all pass; v1 file unchanged and green)

- Valid 1.1 assembly with an interleaved atomic annotation, a shared-prefix local branch and a
  later mainline continuation: raw stays unvalidated, normalized is consolidated/valid,
  annotation anchor/evidence and exact-cover flow survive; summary counts exact and conflict-free.
- Exact trusted provenance binding, canonical trailing-newline bytes and request/response/raw/
  normalized SHA-256 verification; the 1.1 provider-response document has exactly the 9 frozen
  keys including `artifact_schema`/`ccef_schema_version` and the content/hash bindings.
- Annotation warnings count toward `warning_count` and `has_conflicts`; a clean annotated package
  is conflict-free.
- Deterministic repeated assembly, input non-mutation (context/request/response snapshots equal),
  and semantic annotation-text change altering raw/normalized/response hashes.
- Sanitized rejections: tampered request -> binding_mismatch; v1 response -> invalid_package;
  wrong adapter version -> binding_mismatch; malformed content -> invalid_json without leakage.
- Root exports identity-equal to owner modules; fresh subprocess import keeps the frozen import
  purity (no chess/httpx/sqlalchemy/sanic/store/service/worker/review); AST check of the root
  `__init__` shows no forbidden eager imports.
- All 29 existing `test_extraction_candidates.py` tests pass unchanged; v1 provider artifact
  schema/key set/bytes untouched.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_candidates.py backend/tests/test_extraction_candidates_v1_1.py
                                       → 41 passed (29 v1 + 12 v1.1)
uv run --project backend --locked ruff format --check (3 files)
                                       → 3 files already formatted
uv run --project backend --locked ruff check (3 files)
                                       → All checks passed!
uv run --project backend --locked mypy (3 files)
                                       → Success: no issues found in 3 source files
git diff --check                       → clean
```

### Assumptions

- The 1.1 provider-response artifact is a separate schema string, so the v1 document key set and
  bytes remain byte-compatible (no shared mutation).
- Annotation warnings are counted only through the normalized package (post-consolidation), so
  generated and source warnings both flow into `warning_count`.

### Remaining risks

- The candidate/worker wiring (8D-3D2B2 pipeline identity/fingerprint) is not part of this packet;
  the 1.1 assembler is callable but not yet routed by any worker.
- Real-book checkpoint remains a later step; only invented synthetic content is exercised.

### Status

**Pending Codex review.** 8D-3D2B2/8D-3D2B3/8D-3D4 not started; no commit created.

## Codex final review — DS-STAGE8-ANNOTATED-CANDIDATE-01 accepted

Accepted on 2026-08-14. Codex inspected the two public version paths, summary factoring, root lazy
exports and all 12 new tests. Independent focused verification passed 41/41 tests; Ruff format/
check, MyPy and `git diff --check` passed. A stricter fresh-interpreter check explicitly tested
`module == "chess"` as well as `chess.*`, HTTP, SQLAlchemy, Sanic, store/services/review modules and
returned an empty forbidden-module set.

The v1 entry remains version-explicit and byte-compatible. The v1.1 entry rebuilds/decodes/binds/
consolidates only through accepted 1.1 functions, emits a separately versioned provider-response
artifact with explicit CCEF version binding, preserves canonical bytes and includes annotation
warnings in the existing summary shape. No provider, I/O, full suite or commit was used.

One non-blocking oracle detail was noted: the committed fresh-import test's marker `"chess."`
would not by itself match the top-level module name `"chess"`; Codex's stricter independent check
confirmed the current implementation is clean. This does not justify another correction round and
can be tightened during a later test-maintenance touch.

PLANS now activates `DS-STAGE8-ANNOTATED-EXECUTION-01 (8D-3D2B2)`. The architecture keeps existing
v1/v2 constants and fingerprints immutable, adds an explicitly requested `pdf-extraction:v3` plus
v6 fingerprint, and routes trusted v3 jobs to CCEF 1.1. Persistence still defaults to v2 until the
3D2B3 HTTP/read compatibility packet, preventing a temporarily unreadable public default.

## DS-STAGE8-ANNOTATED-EXECUTION-01 (8D-3D2B2) completion

### Files changed

- `backend/src/chess_workbench/services/pdf_persistence.py` — added
  `PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION = "pdf-extraction:v3"` and
  `PDF_ANNOTATED_EXTRACTION_FINGERPRINT_VERSION = "pdfium-text-lines+ccef-annotated-consolidation:v6"`;
  `_SUPPORTED_PIPELINE_VERSIONS` now accepts v1/v2/v3; `_logical_fingerprint` selects the v6
  fingerprint version only for v3 (v5 frozen for v1/v2). The `enqueue_extraction` default remains
  v2; the v1/v2 constants are untouched.
- `backend/src/chess_workbench/services/pdf_extraction.py` — `_SUPPORTED_PIPELINES` accepts v3;
  `_ExtractionInput` retains the validated `pipeline_version`; a narrow private
  `_ccef_pipeline_functions(pipeline_version)` helper selects the request builder/assembler pair
  only from the trusted persisted pipeline identity (v3 -> 1.1 pair, v2 -> 1.0 pair, anything else
  -> sanitized invalid_job_payload); `_process_ccef_candidate` uses the helper; the committed-
  evidence resume path now covers v3 alongside v2.
- `backend/tests/test_stage8_annotated_execution.py` (new) — 8 focused tests.
- `docs/agent/HANDOFF.md` — this evidence.

No API/Schema/model/migration/review/worker/frontend change; no real provider call; no
commit/stage/unstage/reset; no probe files.

### Pipeline identities

- v1 (`pdf-extraction:v1`) evidence-only behavior unchanged; v2 (`pdf-extraction:v2`) constant and
  v5 fingerprint byte-for-byte unchanged; v3 (`pdf-extraction:v3`) is explicitly enqueueable only.
- Same asset/pages/profile enqueued as v2 vs v3 produce distinct logical fingerprints (identity
  differs in both `extraction_fingerprint_version` v5/v6 and `pipeline_version`), distinct
  effective keys, distinct deterministic run UUIDs and distinct Jobs; replaying each version
  returns only its own run.
- Persistence default is still v2: an `enqueue_extraction` without `pipeline_version` yields a v2
  run; unsupported pipeline payloads are rejected with the existing sanitized ValueError.

### Execution behavior

- v2 continues to rebuild `build_ccef_generation_request` and accept only CCEF 1.0 through
  `assemble_ccef_candidate_artifacts`, emitting provider-response/1.0 plus CCEF 1.0 raw/normalized
  artifacts (its provider document does not gain `ccef_schema_version`).
- v3 rebuilds `build_ccef_v1_1_generation_request` and accepts only CCEF 1.1 through
  `assemble_ccef_candidate_artifacts_v1_1`, emitting provider-response/1.1 (with
  `ccef_schema_version: "chess-content-extraction/1.1"`) plus CCEF 1.1 raw/normalized artifacts.
- The builder/assembler choice comes only from the persisted trusted `pipeline_version`; response
  content, provider metadata and artifact presence are never inspected (no content dispatcher).
- The three immutable slot names and page-null JSON media types are unchanged within their distinct
  v2/v3 run IDs; v3 never writes artifacts belonging to an existing v2 run.
- `PDF_EXTRACTION_RESULT_SCHEMA`, result outer shape and `candidate.summary` fields are unchanged;
  candidate hashes bind the exact newly stored blobs.
- Provider selection, sanitized prompt/provider/decode/candidate errors, retryability,
  committed-evidence resume, CAS verification, artifact-conflict protection and transaction
  boundaries are unchanged.
- Cross-version responses fail sanitized: v3 with a 1.0 response and v2 with a 1.1 response both
  raise `ccef_invalid_package` through the accepted decoder and register no candidate artifacts.

### Focused oracle (68 tests, all pass; existing files unchanged and green)

- v2/v3 distinct fingerprints/runs/jobs + per-version replay isolation.
- v3 job sends the exact 1.1 prompt request (prompt version `chess-workbench/ccef-prompt/1.4`,
  schema 1.1, adapter 1.1), is called once, and the succeeded result registers exactly the three
  CCEF slots whose bytes parse as provider-response/1.1 and `ExtractionPackageV1_1` raw/normalized
  with annotations/flow/branch topology surviving.
- v2 job keeps the 1.0 request and artifacts; its provider document lacks `ccef_schema_version`.
- v3 committed-evidence resume reuses the 1.1 path with no rerender/OCR duplication.
- v3-with-1.0 and v2-with-1.1 both fail sanitized (`ccef_invalid_package`) without leaking
  response text and register no candidate artifacts.
- Artifact conflict stays fail-closed: a semantically different but trusted-binding package re-run
  raises `artifact_conflict` and the existing row/blob bindings are never changed.
- Unsupported pipeline payloads rejected; constants/default explicit (v2 default, v3 explicit);
  all 60 existing `test_pdf_persistence.py`/`test_stage8c_execution.py` tests pass unchanged.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_persistence.py backend/tests/test_stage8c_execution.py \
  backend/tests/test_stage8_annotated_execution.py
                                       → 68 passed (60 existing + 8 new)
uv run --project backend --locked ruff format --check (3 files)
                                       → 3 files already formatted
uv run --project backend --locked ruff check (3 files)
                                       → All checks passed!
uv run --project backend --locked mypy (3 files)
                                       → Success: no issues found in 3 source files
git diff --check                       → clean
```

### Assumptions

- The v6 fingerprint version is only reachable for explicit v3 requests; v1/v2 keep the frozen v5
  value, so existing logical fingerprints are byte-identical.
- `_ccef_pipeline_functions` raises the sanitized invalid_job_payload only for a pipeline value
  that already passed `_load_input` validation (v1 evidence-only never reaches it).

### Remaining risks

- The HTTP/read compatibility cutover (3D2B3) is not part of this packet: persistence still
  defaults to v2, so the public default remains readable until then.
- No real-book checkpoint; only invented synthetic content exercised.

### Status

**Pending Codex review.** 3D2B3/3D4 not started; no commit created.

## Codex review: DS-STAGE8-ANNOTATED-EXECUTION-01 R1 required

Codex reviewed the actual B2 diff. The production implementation is accepted as written: v3 has
its own immutable v6 fingerprint identity, `_load_input` retains and validates the persisted
pipeline version, and builder/assembler routing depends only on that trusted identity. Existing
v1/v2 constants and the v2 persistence default remain unchanged.

Independent focused verification:

```text
pytest test_pdf_persistence.py test_stage8c_execution.py test_stage8_annotated_execution.py
  -> 68 passed in 10.63s (outside the tool sandbox after aiosqlite hung inside it)
ruff format --check -> clean
ruff check -> clean
mypy -> clean
git diff --check -> clean
```

One oracle blocker remains. The “v2 receives a 1.1 response” half of
`test_cross_version_responses_fail_sanitized_without_candidate_artifacts` derives its response
from the v2 prompt skeleton and never changes `schema_version` or provenance adapter version from
1.0. It therefore sends malformed 1.0-with-1.1-fields, not a valid CCEF 1.1 document. The code path
is sound, but the frozen cross-version claim is not yet proved.

PLANS now activates a test-only R1: validate each submitted opposite-version document against its
own public model, use distinct private markers to prove sanitized errors, keep all eight tests, and
leave production files read-only. Status remains **pending Codex re-review**; do not start 3D2B3 or
3D4 and do not commit.

## DS-STAGE8-ANNOTATED-EXECUTION-01 R1 (8D-3D2B2) completion

### Files changed

- `backend/tests/test_stage8_annotated_execution.py` — cross-version test strengthened only;
  imports `ExtractionPackage`/`ExtractionPackageV1_1` from contracts and
  `Awaitable`/`Callable` from collections.abc.
- `docs/agent/HANDOFF.md` — this evidence.

No production file changed (`pdf_persistence.py`/`pdf_extraction.py` and every other module are
untouched in this R1 round); no commit/stage/unstage/reset; no probe files.

### R1 correction (frozen)

1. The v3 branch's submitted 1.0 document is now validated with
   `ExtractionPackage.model_validate(...)` and serialized from its `model_dump(mode="json")`
   before being sent to the wrong (v3) pipeline, so it is a genuine CCEF 1.0 package.
2. The response submitted to v2 is now built as a genuine CCEF 1.1 package: top-level
   `schema_version = "chess-content-extraction/1.1"`, trusted provenance `adapter_version = "1.1"`,
   the accepted annotated items, validated with `ExtractionPackageV1_1.model_validate(...)` before
   returning the provider response. It is no longer the v2 skeleton left at version 1.0.
3. Each otherwise-valid opposite-version package carries a distinct invented private marker
   (`private-marker-v3-9f4c2d` in the v1 heading text; `private-marker-v2-1e8a5b` in a v1.1
   annotation text). Both halves keep the exact `ccef_invalid_package` assertion and the
   zero-candidate-artifact assertion, and additionally assert the respective marker does not occur
   in the public `EngineError` string.
4. All eight existing tests and their assertions are preserved unweakened (identity, resume,
   immutable-artifact, compatibility oracles intact); the only other test-file change is typing
   `_V2Provider`'s responder as `Callable[[StructuredGenerationRequest],
   Awaitable[StructuredGenerationResponse]]` to satisfy strict mypy.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8_annotated_execution.py
                                       → 8 passed
uv run --project backend --locked ruff format --check backend/tests/test_stage8_annotated_execution.py
                                       → 1 file already formatted
uv run --project backend --locked ruff check backend/tests/test_stage8_annotated_execution.py
                                       → All checks passed!
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_stage8_annotated_execution.py
                                       → Success: no issues found in 1 source file
git diff --check                       → clean
```

### mypy invocation note

The bare packet command `uv run --project backend --locked mypy
backend/tests/test_stage8_annotated_execution.py` (from the repo root) reports 11
`import-untyped` errors. These are a pre-existing config-discovery artifact, not an R1 regression:
the repo root has no `pyproject.toml`, so mypy cannot discover `backend/pyproject.toml` when only
a test file is given (every earlier packet's mypy command included at least one
`backend/src/...` file, which made the package resolve without the config), and the editable
install of `chess_workbench` lacks `py.typed`. All 11 errors are `import-untyped`; zero genuine
findings. The config-aware equivalent (`--config-file backend/pyproject.toml`, which also makes
`mypy_path = "backend/src"` resolve from the repo root) passes clean and is the run recorded
above.

### Assumptions

- The opposite-version documents are structurally valid instances of their own public contract
  (validated round-trip through `model_dump(mode="json")`), so the rejection is genuinely a
  cross-version rejection rather than malformed-content rejection.
- The markers live in fields that are part of the valid packages (heading text / annotation text)
  and would surface in any unsanitized error that leaked response content.

### Remaining risks

- None new; the frozen cross-version claim is now backed by model-validated opposite-version
  packages and non-leakage markers. HTTP/read cutover (3D2B3) and real-book checkpoint remain
  later steps.

### Status

**Pending Codex re-review.** 3D2B3/3D4 not started; no commit created.

## Codex final re-review: DS-STAGE8-ANNOTATED-EXECUTION-01 R1 accepted

Codex inspected the actual R1 test changes. Both cross-version payloads are now validated by their
own public models before being sent to the wrong pipeline: the v3 branch submits a genuine
`ExtractionPackage` 1.0 document, while the v2 branch submits a genuine
`ExtractionPackageV1_1` document with schema/adapter version 1.1. Each contains a distinct private
marker and each public `EngineError` is proved not to leak it. All eight prior tests remain.

Independent focused verification:

```text
pytest test_stage8_annotated_execution.py -> 8 passed in 2.06s
ruff format --check -> clean
ruff check -> clean
mypy --config-file backend/pyproject.toml -> clean
git diff --check -> clean
```

The production B2 implementation and its R1 oracle are accepted. The bare mypy command in the R1
packet lacked the backend configuration when it named only a test file; the config-aware project
command is authoritative and has been frozen explicitly in the next packet.

PLANS now activates `DS-STAGE8-ANNOTATED-READ-COMPAT-01 (8D-3D2B3)`: the HTTP create route will
explicitly choose immutable v3, public extraction summaries will read both v2/v3 through their
unchanged result shape, and the existing review loader will remain v2-only with sanitized 409 for
v3 until 8D-3D5. Do not start the offline 3D4 checkpoint or later review work until B3 is reviewed.

## DS-STAGE8-ANNOTATED-READ-COMPAT-01 (8D-3D2B3) completion

### Files changed

- `backend/src/chess_workbench/api/pdf.py` — HTTP create cutover plus v2/v3 read gates (7 insertions,
  2 deletions).
- `backend/tests/test_pdf_api.py` — the deterministic run-id helper now mirrors the frozen
  fingerprint-version field (v5/v6 selection) and takes an explicit pipeline version; the exact-job
  enqueue test moved to v3 expectations; five new focused tests added.
- `backend/tests/test_stage8d_review_read_service.py` — one focused v3 review-boundary test.
- `docs/agent/HANDOFF.md` — this evidence.

No change to persistence (`enqueue_extraction` default stays v2), execution, `pdf_review.py`,
schemas/OpenAPI/generated types/SQL/models/migrations or frontend; no real provider call; no
commit/stage/unstage/reset; no probe files.

### HTTP create cutover

- `api/pdf.py` imports `PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION` and `create_pdf_extraction`
  passes `pipeline_version=PDF_ANNOTATED_EXTRACTION_PIPELINE_VERSION` explicitly to
  `PdfPersistenceService.enqueue_extraction`. The persistence service's own default remains v2, so
  non-HTTP/internal callers that omit the argument still get v2.
- A new POST without an explicit idempotency header creates/replays the v3 identity: response,
  Location, Job payload and deterministic run ID all bind v3 with the v6 fingerprint identity
  (test asserts the exact deterministic run id).
- A pre-existing same-input v2 run is distinct; POST creates a separate v3 run and never replays the
  v2 one. An explicit Idempotency-Key already bound to a v2 run is not rebound to v3 (409
  idempotency_conflict, zero new rows).
- No pipeline selector was added to the request/response schemas; OpenAPI/generated contracts are
  untouched.

### Public read compatibility

- `_evidence_result` accepts the extraction result envelope only for trusted v2/v3 runs; v1
  evidence-only behavior unchanged.
- `_candidate_summary` exposes a candidate only for trusted v2/v3 runs (explicit pipeline gate
  added), retaining all existing exact result keys, artifact-slot/hash bindings, strict Pydantic
  validation and fail-closed behavior. Version is never inferred from response content or artifact
  bytes.
- GET-one, GET-list and `has_conflicts` filtering expose the same `PdfEvidenceSummary`/
  `PdfCandidateSummary` shape for complete v2 and v3 runs; no raw CCEF, provider content, CAS path
  or API key becomes public.
- Malformed/misbound/incomplete v2 or v3 results still yield `evidence=null`, `candidate=null` and
  `has_conflicts=false`; forged v1/unsupported-pipeline envelopes are never exposed as candidates.

### Review compatibility boundary (read-only)

- `pdf_review.py` is untouched; its existing pipeline gate
  (`run.pipeline_version != PDF_EXTRACTION_PIPELINE_VERSION` -> sanitized
  `ServiceError("ambiguous_context", 409, "PDF extraction review is not available")`) already covers
  v3 before any CCEF package parse/inspection.
- New focused test proves both `read_document` and `read_page` return the exact sanitized 409
  (code/status/message/details=None/__cause__=None) for a v3 run; v2 reviews remain readable
  exactly as before; v1 stays unavailable; 404/503/page behavior unchanged.

### Focused oracle (44 tests, all pass; existing suites unchanged and green)

- POST queues v3 with the exact deterministic v6 run ID and exact v3 Job payload; replay stable.
- Pre-existing same-input v2 run distinct; POST v3 not a replay of it.
- Explicit idempotency key bound to v2 not rebound to v3 (existing 409 semantics).
- Complete committed v2 and v3 runs expose identical-shaped evidence/candidate summaries via
  detail/list and participate correctly in `has_conflicts` filtering (both listed under true,
  neither under false).
- Forged v1 and unsupported-pipeline result envelopes expose no candidate/evidence.
- Malformed/missing slots (deleted rendered page) fail closed for a v2 run; the existing committed-
  summary test (now a v3 run) covers v3.
- v3 review returns the sanitized 409 for both `read_document` and `read_page` without parsing.
- The updated `expected_run_id` helper independently mirrors the frozen v5/v6 fingerprint identity
  without calling the production private fingerprint helper.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_api.py backend/tests/test_stage8d_review_read_service.py
                                       → 44 passed (17 API + 27 review)
uv run --project backend --locked ruff format --check (3 files)
                                       → 3 files already formatted
uv run --project backend --locked ruff check (3 files)
                                       → All checks passed!
uv run --project backend --locked mypy --config-file backend/pyproject.toml (3 files)
                                       → Success: no issues found in 3 source files
git diff --check                       → clean
```

### Assumptions

- The pre-existing `expected_run_id` helper was missing the frozen `extraction_fingerprint_version`
  field, so the exact-job test failed at baseline; the packet-required helper update (v5/v6
  selection + explicit pipeline literal) fixes it and is now covered by the new v3 exact-run-id
  assertion.
- The committed-result shape is identical for v2 and v3 (same result schema, same summary keys), so
  the API layer needs no content inspection beyond the trusted pipeline gate.

### Remaining risks

- v3 review consumption (inspection/read/UI) is deliberately deferred to 8D-3D5; until then v3 runs
  stay sanitized 409 at the review boundary. The offline JSON checkpoint (3D4) remains a later step.

### Status

**Pending Codex review.** 8D-3D4/8D-3D5/8D-4 not started; no commit created.

## Codex final review: DS-STAGE8-ANNOTATED-READ-COMPAT-01 accepted

Codex inspected the actual B3 diff. The HTTP create route explicitly passes v3 while the
persistence service remains untouched with its v2 default. Public extraction reads admit only the
trusted v2/v3 pipeline identities through the unchanged summary/artifact binding checks. The
review loader is untouched and rejects v3 before parsing CCEF, preserving v2 review behavior.

Independent focused verification:

```text
pytest test_pdf_api.py test_stage8d_review_read_service.py -> 44 passed in 19.87s
ruff format --check -> clean
ruff check -> clean
mypy --config-file backend/pyproject.toml -> clean
git diff --check -> clean
```

No blocking finding remains. 8D-3D2 producer wiring is complete. PLANS now activates
`DS-STAGE8-ANNOTATED-OFFLINE-INSPECTOR-01 (8D-3D4A)`, a provider-free extension of the existing
inspection CLI. It will add explicit CCEF 1.1 parsing, annotation/reading-flow/branch metrics and a
canonical comparison against a committed normalized artifact while preserving the default 1.0
CLI/report behavior. Only after that tool is reviewed should 3D4B make a real pages 319–323 v3
request and inspect local pretty JSON. No commit was created.

## DS-STAGE8-ANNOTATED-OFFLINE-INSPECTOR-01 (8D-3D4A) completion

### Files changed

- `scripts/inspect_ccef_consolidation.py` — version-explicit offline inspector extension.
- `backend/tests/test_inspect_ccef_consolidation_v1_1.py` (new) — 6 focused subprocess tests.
- `docs/agent/HANDOFF.md` — this evidence.

No production extraction module changed; no provider/network/database access; no `data/books`,
`data/database` or secret read; no commit/stage/unstage/reset; no probe files.

### Frozen CLI surface

- Existing positional/options preserved: `inspect_ccef_consolidation.py RAW_CCEF --evidence PAGE
  ... --output OUT --report REPORT`.
- Added `--ccef-version {1.0,1.1}` (default `1.0` for backward compatibility) and
  `--committed-normalized PATH` (optional verified comparison input).
- Selection comes only from `--ccef-version`: 1.0 -> `ExtractionPackage` +
  `consolidate_move_sequences`; 1.1 -> `ExtractionPackageV1_1` +
  `consolidate_move_sequences_v1_1`. Version is never inferred from JSON content; a document whose
  literal schema version does not match the selected mode fails cleanly (exit 2, sanitized stderr)
  with no silent upgrade/downgrade or parser fallback.
- Existing evidence loading, pretty normalized output and exit convention unchanged for the
  default path; inputs are never modified; no provider content, API key or filesystem path appears
  in the report.

### 1.0 compatibility

The default 1.0 report retains the exact previous key set (`raw`, `normalized`, `gate_passed`
with the exact nested keys), counts, `gate_passed` conditions, JSON shape and exit status (0/1).
The 1.0-only facts never leak into default output; `committed_matches_offline` appears only when
`--committed-normalized` is supplied, and for 1.0 it is reported without changing `gate_passed`.

### 1.1 inspection report

The 1.1 report keeps all existing raw/normalized metrics and adds deterministic facts derived
only from the validated package: `annotation_count`, `reading_flow_entry_count`,
`reading_flow_move_ref_count`, `reading_flow_annotation_ref_count`, `variation_start_count`
(nodes with `sibling_order > 0`), `annotation_anchor_counts` split into
`move_node`/`position`/`null`, per-sequence `annotation_count`/`reading_flow_count` alongside the
existing `leaf_lines`, and a top-level `committed_matches_offline` (`true`/`false`/`null` when not
supplied).

The 1.1 `gate_passed` requires all existing legality/no-duplicate/evidence-preservation gates plus
explicitly: every normalized node `valid` (invalid/ambiguous/unvalidated count zero), flow move
references equal the normalized move-node count, flow annotation references equal the normalized
annotation count, and (when `--committed-normalized` is supplied) the committed canonical value
matches the offline recomputation. Contract validation remains authoritative for exact-cover/
reference validity.

### Focused synthetic oracle (6 tests, all pass)

- 1.1 mode on an invented tree (continuous main line, interleaved annotation, earlier-parent local
  variation n12, nested variation n15, later main-line continuation n16) reports exact counts
  (annotation 2, flow entries 18, move refs 16, annotation refs 2, variation starts 2, anchors
  `{move_node: 1, position: 0, null: 1}`), gate passed, exit 0, and the pretty output preserves
  exact parent IDs, sibling orders, annotations and reading-flow order.
- `--committed-normalized` reports true and gate stays true for the equivalent canonical
  normalized package; a different-but-valid package reports false and flips the gate (exit 1).
- Literal version mismatch is rejected in both directions (1.1 doc under default 1.0, 1.0 doc under
  `--ccef-version 1.1`) with exit 2 and no report file written.
- Inputs (raw, evidence, committed) remain byte-identical after the run.
- Default-1.0 regression: exact old report key set, counts and exit convention; explicit
  `--ccef-version 1.0` produces the identical report; 1.0 committed comparison reports the fact
  without changing the gate.

### Focused acceptance commands (packet-verbatim, all green)

```
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_inspect_ccef_consolidation_v1_1.py
                                       → 6 passed
uv run --project backend --locked ruff format --check (2 files)
                                       → 2 files already formatted
uv run --project backend --locked ruff check (2 files)
                                       → All checks passed!
uv run --project backend --locked mypy --config-file backend/pyproject.toml (2 files)
                                       → Success: no issues found in 2 source files
git diff --check                       → clean
```

### Assumptions

- The committed-normalized artifact is compared as a canonical `model_dump(mode="json")` value
  with the same selected public model; formatting differences are irrelevant.
- Version-mismatch rejection is handled as a clean exit-2 with a sanitized stderr message (the
  previous uncaught-traceback path only applied to invalid inputs, not the frozen valid-input
  behavior).

### Remaining risks

- The tool is an inspection aid, not a semantic claim about the model's real branch-parent choice;
  the real pages 319-323 v3 checkpoint (3D4B) and v3 review consumption (3D5) remain later steps.

### Status

**Pending Codex review.** 3D4B/3D5/8D-4 not started; no commit created.

## Codex final review: DS-STAGE8-ANNOTATED-OFFLINE-INSPECTOR-01 accepted

Codex inspected the actual 3D4A diff. Version selection is driven only by the explicit CLI option;
the default 1.0 report/gate shape is frozen by a regression test. The 1.1 path uses the accepted
public model/consolidator, reports deterministic annotation/flow/branch facts and compares a
committed package by canonical model value. The synthetic tree proves an earlier-parent variation,
nested variation, interleaved annotation and later main-line continuation without source-specific
data.

Independent focused verification:

```text
pytest test_inspect_ccef_consolidation_v1_1.py -> 6 passed in 3.05s
ruff format --check -> clean
ruff check -> clean
mypy --config-file backend/pyproject.toml -> clean
git diff --check -> clean
```

No blocking finding remains. PLANS now activates
`DS-STAGE8-ANNOTATED-REAL-CHECKPOINT-01 (8D-3D4B)`. It authorizes one existing-policy v3 Job for
the already-registered pages 319–323 asset, with a strict preflight preventing unrelated queued
work and an immediate stop on balance/credit/quota errors. Only verified raw/normalized/evidence
artifacts may be copied into gitignored `data/debug`; provider response and secret contents must
never be opened or printed. The inspector machine gate and six semantic pretty-JSON checks must
both pass before 3D5. No commit was created.

## DS-STAGE8-ANNOTATED-REAL-CHECKPOINT-01 (8D-3D4B) — stopped before preflight

### Status: STOPPED (preflight unexecutable), pending Codex review

Per the operator's decision, the task was paused because the local preflight could not be
executed: every attempt to start the local API server through the project's existing means
(`uv run --project backend --locked python -m chess_workbench`) was denied by the tool sandbox
(background run + localhost network binding), so the required public asset/extraction preflight
state could not be inspected through the API.

### What was and was not done

- **No v3 run was created**; no `pdf-extraction:v3` Job was enqueued; no worker was enabled; no
  provider call was made; no DeepSeek balance/credit/quota was consumed.
- No runtime database/CAS change; no artifacts were exported to `data/debug`; no secret file,
  `.env` content, `provider_response`, HTTP request/response body or key content was read, printed
  or copied (only env-variable *existence* probes and config-file default reads were performed).
- No tracked source/test/contract/script/plan file was modified in this packet; no commit/stage/
  unstage/reset; no delete.
- Sanitized environment facts recorded: `CHESS_WORKBENCH_DEEPSEEK_API_KEY_FILE` and
  `CHESS_WORKBENCH_DATABASE_URL` are unset in the operator shell (`.env` exists and would be loaded
  by the server); defaults resolve to `data/database/chess-workbench.db` and `data/` storage.

### Next step for the operator

Start the API server manually (e.g. `CHESS_WORKBENCH_ENGINE_WORKER_ENABLED=false uv run --project
backend --locked python -m chess_workbench`), then resume 8D-3D4B from the frozen preflight: list
assets/extractions via the API, confirm the Smerdon Scandinavian pages 319–323 asset and the prior
v2 run profile, verify zero unrelated queued/running Jobs, POST exactly one v3 request, enable the
normal worker, then run the frozen inspector command and the six semantic checks. The debug
filenames under `data/debug/stage8d-v3-pages-319-323.*` remain the authorized export target.

### Status

**Stopped before preflight — pending Codex review / operator action.** 3D5/8D-4 not started; no
commit created.

## 8D-3D4B preflight aborted — API unreachable from tool sandbox (resume attempt)

The operator confirmed the API is running at http://127.0.0.1:8000 (worker disabled), but every
`curl`/HTTP probe from this tool session to `http://127.0.0.1:8000/api/health` was denied by the
tool sandbox (network side effect rejected). Per the frozen stop condition ("if the API cannot be
reached, stop immediately and report the connection error; do not start another service or modify
the database directly"), the preflight/registration was NOT executed:

- no asset/extraction listing performed; no Smerdon Scandinavian asset ID/profile recorded;
- no queued/running Job check performed; no v3 POST issued; no v3 run/Job created;
- no worker enabled, no provider call, zero API cost;
- no secrets/.env/provider_response/book content read or printed.

3D4B remains NOT completed. To resume, the operator needs to allow localhost HTTP access from the
tool sandbox (or run the preflight commands themselves and share sanitized results). Status:
STOPPED at preflight, pending Codex review / operator action. No commit created.

## Codex execution: DS-STAGE8-ANNOTATED-REAL-CHECKPOINT-01 (8D-3D4B) failed semantic gate

Codex resumed the operational checkpoint with explicit operator authorization. The API was first
started with the SQL worker disabled. Public metadata identified exactly one registered target
asset, `2ca70ce3-8b6a-4a92-95c6-b67a02cf7b8a` (the Smerdon Scandinavian PDF, 672 pages), and the
successful pages 319–323 v2 runs all used the exact empty profile `{}`. A read-only global Job
query returned no queued/running rows before registration.

Exactly one v3 request was posted. It created (not replayed) run
`0d38fbfe-24af-56c0-8d2e-5eacec837458` and Job
`524317c4-1848-4b95-979f-5e11fd11e4f4`. A second queue check showed that target as the sole queued
Job. The normal worker was then enabled only for this run and stopped immediately after terminal
success. Final status was `succeeded`, attempt count 2/3. Attempt 1 produced the sanitized
`ccef_invalid_json` error; the existing retry policy performed attempt 2 successfully. No second
run or manual retry was created. The final public result exposes no token-usage counts.

The allowed selected artifact slots were exact and each CAS blob passed registered byte-size and
SHA-256 verification before export:

- `raw_ccef`, page null: 24,546 bytes, `3fc70f7b99d2...`
- `normalized_ccef`, page null: 28,168 bytes, `373d2772851b...`
- `ocr_fragment`, page 319: 6,339 bytes, `2c6e9b45473d...`
- `ocr_fragment`, page 320: 14,720 bytes, `e7d0542bcfcf...`
- `ocr_fragment`, page 321: 7,048 bytes, `4e0669976473...`
- `ocr_fragment`, page 322: 7,531 bytes, `e851dc376d57...`
- `ocr_fragment`, page 323: 7,775 bytes, `1db420f2dca5...`

The provider-response artifact and secret file were never opened, copied or printed. The local
exports are gitignored files named:

- `data/debug/stage8d-v3-pages-319-323.raw.json`
- `data/debug/stage8d-v3-pages-319-323.committed.normalized.json`
- `data/debug/stage8d-v3-pages-319-323.evidence-{319,320,321,322,323}.json`
- `data/debug/stage8d-v3-pages-319-323.normalized.pretty.json`
- `data/debug/stage8d-v3-pages-319-323.report.json`

The accepted 1.1 inspector exited 0. Machine facts: `gate_passed=true`,
`committed_matches_offline=true`, 23 items, one sequence, 32/32 valid nodes, zero duplicate UCI
paths, complete 32/32 move-flow coverage, zero annotations/annotation references and no missing raw
non-move item IDs. Machine validity therefore passed, but the required source-semantic checkpoint
failed:

1. **PASS (structure only):** `move-sequence-1` is one 32-node sequence rather than several
   repeated-prefix sequences; duplicate path count is zero.
2. **FAIL:** the main-line nodes `n11` (`6.Be3`) and `n12` (`6...O-O-O`) are adjacent in both the
   parent chain and reading flow. No explanatory annotation or local variation is interleaved.
3. **FAIL:** the local `6.O-O` move is `n13` with parent `n12`; it should be an alternative child
   of the real `5...Nc6` parent `n10`. `variation_start_count` is zero and there is no nested
   variation structure.
4. **FAIL:** `annotation_count` is zero. The explanatory material remains the monolithic page-321
   top-level item `prose-7`, with no atomic move/position-anchored annotations.
5. **PASS:** introductory plan discussion remains prose and the normalized timeline contains no
   additional plan-only candidate moves beyond the extracted score.
6. **FAIL (traceability quality):** all five pages and all 23 non-move items remain represented,
   but every CCEF evidence reference has a null fragment hash/offset. In addition, nodes `n1`–`n8`
   carry only page-319 evidence even though the single sequence is placed after the page-321 Game
   13 headings, so the Game 13 prefix is not reliably traceable to its source occurrence.

Overall 3D4B status: **FAILED semantic gate**. The debug artifacts are retained for diagnosis.
Per the frozen stop condition, 3D5/8D-4 were not started, no source-specific workaround was added,
and no new provider run was enqueued. The next action belongs to Codex architecture/prompt diagnosis,
not the review UI.

## Codex correction: retain failed semantic-v4 generations for fine-grained diagnosis

The operator explicitly superseded the earlier provider-response non-inspection rule for failed
future semantic-v4 attempts: do not discard a failed model generation; retain it locally and first
understand why it failed. No API, worker or real provider was run during this correction.

### Implemented behavior

- Added `services/ccef_failure_debug.py`. A failed semantic-v4 response is stored exactly as UTF-8
  text below the gitignored, server-owned CAS namespace
  `debug/extraction-failures/<run-id>/attempt-<attempt-count>/`. A separate canonical JSON sidecar
  records only stable run/job/attempt identity, response digest/size, provider/model/finish reason,
  token usage, fixed failure code/message and sanitized diagnostics. Files retain the existing CAS
  atomic-write/hash-verification/0600 guarantees.
- Failed captures are deliberately not `ExtractionArtifact` rows, do not produce `candidate`, and
  are not exposed by HTTP/review UI. The sidecar contains no request, API key, raw HTTP body,
  model-generated content or filesystem path. The exact response is a separate local-only file.
- JSON failures now report only safe shape facts: syntax line/column, duplicate member,
  non-standard constant, excessive nesting, non-object root, or at most 20 CCEF field/error-type
  entries. Arbitrary model-owned keys are replaced by `<field>` before logging or persistence.
- Semantic evidence failures report aggregate counts only: evidence references, bbox repairs,
  missing locators, unmatched locators and ambiguous bboxes. A supplied-but-wrong fragment hash is
  rejected and counted as unmatched; bbox recovery is allowed only when the hash is absent and the
  bbox uniquely identifies one trusted fragment.
- After capturing a semantic-v4 decode/binding failure, the error is non-retryable so the worker
  stops for inspection instead of immediately buying another opaque attempt. Existing v2/v3 retry
  semantics are unchanged. If capture itself fails, the job exposes a sanitized
  `ccef_failure_capture_failed` error rather than pretending the original output was retained.

### Focused verification

Only directly relevant checks were run. The first candidate selection exposed the unsafe behavior
where an explicit wrong hash was silently replaced from bbox; that behavior was corrected rather
than weakening its oracle. Final focused results:

- candidate-binding + capture tests: 17/17 passed;
- decoder-v1.1 + capture tests: 16/16 passed;
- final local capture plus two scripted end-to-end semantic-v4 failure paths (invalid CCEF and valid
  CCEF with unbound evidence): 5/5 passed outside the sandbox in 1.43s. Both integration paths
  retained exact responses, wrote sanitized reports, created zero official CCEF candidate rows and
  returned non-retryable errors;
- the initial sandbox run hung before the changed behavior in temporary SQLite `_setup`; the exact
  same two-test selection passed outside the sandbox. No network or model was involved;
- focused Ruff/MyPy and `git diff --check` were run after implementation; see the current agent
  report for their final result.

### Remaining state

The already-discarded historical failed model responses cannot be recovered. The next real
semantic-v4 run is still not authorized by this correction; when explicitly authorized, its first
failure (if any) will be available locally for direct structural inspection. 8D-3D4B remains open;
3D5 and 8D-4 have not started. No commit was created.

## Codex execution: semantic-v4 fingerprint v11 failed before the original capture boundary

The operator authorized one new pages-319–323 semantic-v4 attempt. Codex first bumped only the
semantic extraction fingerprint from v10 to v11 so cancelled historical identities could not be
replayed. Focused fingerprint/replay tests passed 2/2. Preflight again identified asset
`2ca70ce3-8b6a-4a92-95c6-b67a02cf7b8a`, empty profile `{}` and no unrelated queued/running work.

Exactly one run and one provider call were made:

- run `be1f911c-8a5e-5f16-a451-260d75491721`;
- Job `ae399f4a-8adb-4009-90a8-ac63032c1726`;
- pipeline `pdf-extraction:v4`, final Job status `failed`, attempt count 1;
- `last_error_code=invalid_response`, fixed message `DeepSeek returned an invalid response`;
- evidence/render artifacts exist for all five pages, but zero provider-response/raw-CCEF/
  normalized-CCEF artifacts exist.

The API/worker were stopped after the terminal result. There was no manual retry or second run and
no secret/provider content was printed. The adapter's error mapping proves this was a 2xx response
that failed JSON/required-field/port mapping rather than an HTTP/auth/rate-limit/timeout failure.
However, the response failed before `StructuredGenerationResponse` construction, while the first
debug recorder lived after that construction. Therefore no failure-debug file was produced and
the exact historical HTTP body cannot be recovered. The most likely explanation is a nullable or
empty final `message.content` after a thinking response exhausted/truncated its 48,000-token output
budget; this remains an inference, not a fact, because the discarded body and finish reason are
unavailable.

## Codex correction: provider-boundary invalid-response retention

No further provider call was made. The DeepSeek adapter now accepts an optional async recorder and
invokes it before returning the same sanitized non-retryable `invalid_response` error whenever a
2xx body is invalid JSON, has a missing/null/blank/wrong-type required field, has an unsupported
finish reason, or cannot form the provider-neutral response. The recorder is injected only for
the real semantic-v4 service path. It stores exact HTTP response bytes as `.bin` plus a sanitized
content-addressed JSON sidecar under
`data/debug/extraction-failures/<run-id>/attempt-<attempt-count>/`; it never stores headers,
requests, API keys or decoded provider-owned values and never registers an official extraction
artifact. If capture itself fails, the adapter keeps the frozen `invalid_response` code and emits
a fixed non-sensitive capture-failure message.

Focused verification only:

- `test_ccef_failure_debug.py` + `test_extraction_deepseek.py`: 98 passed;
- focused Ruff: clean;
- focused MyPy on five changed source/test files: clean;
- `git diff --check`: clean.

The mocked oracles prove exact byte retention for malformed JSON and nullable content with
`finish_reason=length`, bounded diagnostic labels, sidecar non-disclosure, 0600 files, idempotent
CAS reuse, empty-body retention and sanitized recorder failure. No full Stage/acceptance suite was
run. 3D4B remains open; 3D5/8D-4 are not started; no commit was created.

## Codex follow-up: expand semantic-v4 reasoning/completion budget

Official DeepSeek V4 documentation was rechecked before changing the request. The API exposes only
`high` and `max` reasoning effort; it does not provide a separate numeric reasoning-token budget.
`max_tokens` limits the whole generated completion and usage separately reports the reasoning
subset. Therefore increasing effort alone could make the suspected final-content starvation worse.

The next semantic-v4 identity is now fingerprint v12 and uses the paired change:

- `reasoning_effort=max` with thinking explicitly enabled;
- semantic request `max_tokens=min(configured limit, 128_000)` instead of 48,000;
- no internal 600-second clamp on the configured provider timeout.

The global default timeout remains 600 seconds. A future explicitly authorized real checkpoint
must start the service with `CHESS_WORKBENCH_CCEF_PROVIDER_TIMEOUT_SECONDS=1200`; no secret or
tracked configuration file needs to change. No provider call was made in this follow-up.

Focused verification only: semantic prompt budget/ceiling, max-effort request mapping and nullable
content capture passed; the two v2/v3/v4 identity/replay tests passed 2/2 outside the tool sandbox
after the in-sandbox SQLite run hung without a failure. Focused Ruff/MyPy and diff checks are
recorded in the current Codex report. No full suite was run and no commit was created.

## Codex real checkpoint: semantic-v4 fingerprint v12 accepted

The operator explicitly authorized one new five-page v12 recognition. Worker-disabled preflight
confirmed the single 672-page target asset `2ca70ce3-8b6a-4a92-95c6-b67a02cf7b8a`, pages 319–323,
profile `{}`, and zero queued/running Jobs. One POST created (not replayed) run
`4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a` and Job
`510d478c-6ee7-4e06-aff0-c8da7225c343`; it was the sole queued Job before enabling the worker.

The worker ran with `CHESS_WORKBENCH_CCEF_PROVIDER_TIMEOUT_SECONDS=1200`. Final state was
`succeeded`, attempt count 1/3, with no last error and no retry. The worker/API were stopped
immediately afterward. No secret or provider response was opened or printed. Because the run
succeeded, no failure-debug capture exists for this run. The public result does not expose token
usage.

Verified selected artifacts before local export:

- raw CCEF: 99,341 bytes, `b72948d0e9e2...`;
- committed normalized CCEF: 111,977 bytes, `e52c27b2a9eb...`;
- evidence page 319: 6,339 bytes, `499ec4399720...`;
- evidence page 320: 14,720 bytes, `42ad361482f7...`;
- evidence page 321: 7,048 bytes, `d03e8ee87528...`;
- evidence page 322: 7,531 bytes, `55b5e974084d...`;
- evidence page 323: 7,775 bytes, `c38da1b418ec...`.

The inspector exited 0 with `gate_passed=true` and `committed_matches_offline=true`. Machine
metrics: 16 items (4 headings, 9 prose, 2 move sequences, 1 figure), 120/120 valid nodes, 7
annotations, 127 exact-cover reading-flow entries, 11 variation starts, zero duplicate UCI paths,
and 105/105 raw evidence fragment hashes preserved. `has_conflicts=true` is solely the expected
retained figure; warning/error/invalid/ambiguous/unresolved counts are all zero.

Frozen semantic checkpoint:

1. PASS — Game 13 is one 112-node shared-prefix sequence; the separate eight-node introduction is
   source-ordered before its prose and is not a duplicated Game 13 prefix.
2. PASS — reading flow contains `n11` (`6.Be3`), an anchored note and its displayed local branch,
   then main-line `n30` (`6...O-O-O`); the parent chain remains continuous through `n11 -> n30`.
3. PASS — `n11` (`6.Be3`, sibling 0) and `n12` (`6.O-O`, sibling 1) are both children of `n10`
   (`5...Nc6`). The variation continuation `n13` (`6...O-O-O`) is a child of `n12`; the main-line
   continuation `n30` is independently a child of `n11`. Later nested branches likewise produce
   11 explicit variation starts without copied roots.
4. PASS — seven source-ordered annotations are interleaved in reading flow, each has a move-node
   anchor and trusted evidence. General chapter/game narrative remains top-level prose.
5. PASS — the chapter plan discussion remains prose; the formal Game 13 tree contains only the
   extracted score/variations and all 120 nodes validate locally.
6. PASS — every referenced fragment has a non-null trusted hash; all 105 raw references and all
   non-move items survive consolidation. Game 13 prefix nodes `n1`–`n12` correctly cite page 321.

Gitignored local files:

- `data/debug/stage8d-v12-pages-319-323.raw.json`;
- `data/debug/stage8d-v12-pages-319-323.committed.normalized.json`;
- `data/debug/stage8d-v12-pages-319-323.evidence-{319,320,321,322,323}.json`;
- `data/debug/stage8d-v12-pages-319-323.normalized.pretty.json`;
- `data/debug/stage8d-v12-pages-319-323.report.json`.

8D-3D4B is accepted. 8D-3D5 may now start; 8D-4 remains blocked until 3D5 completes. No broad
suite was run and no commit was created.

## Codex implementation: 8D-3D5 review consumption ready for operator browser check

The accepted v12 candidate is now readable through the existing review route without converting
or overwriting its CCEF 1.1 artifact. The review package response is a `schema_version`-discriminated
union: v2 continues to require CCEF 1.0, while annotated v3 and semantic v4 require CCEF 1.1. The
loader keeps the existing result/slot/media/size/hash/manifest/CAS binding chain and still returns
the same sanitized 409 for a pipeline/package mismatch. Inspection now counts 1.1 nodes, annotation
warnings and position-anchor ambiguity; no provider response, raw CCEF or filesystem path is added
to the public surface.

The browser review page now treats topology and presentation separately as required by ADR 0017.
It computes variation depth from `parent_id + sibling_order`, but consumes `reading_flow` for visual
order. Atomic annotations interrupt a pending move row, render as readable in-score notes, retain
their evidence-page controls and can move the board to their explicit before/after move-node or FEN
anchor. CCEF 1.0 keeps its previous two-ply row behavior.

Focused evidence only:

- backend inspection/schema/loader selection: 74 passed outside the sandbox (temporary SQLite
  hangs in the tool sandbox); review HTTP: 7 passed;
- frontend move projection/review component: 25 passed; focused TypeScript check clean;
- focused Ruff/MyPy clean and generated contracts are up to date;
- direct real-v12 loader returned CCEF 1.1, pages 319–323, 16 items, two sequences, 120 nodes,
  seven annotations and 127 flow entries. Its sole blocking issue is the already expected retained
  source figure;
- live localhost GET returned a 114,490-byte review JSON document and a valid 1275×1651 PNG for
  page 321. API is running at port 8000 with the application job worker disabled; Vite is running
  at port 5173.

The remaining 8D-3D5 action is the operator's real-browser judgment at
`/sources/pdf-extractions/4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a/review`. Do not mark 3D5 complete
or begin 8D-4 until that interaction checkpoint is accepted. No full suite or commit was run.

## Codex architecture: incremental extraction gate before 8D-4

The operator accepted the v12 pages-319–323 browser result as having no material extraction error;
minor text defects are explicitly deferred to later human editing. 8D-3D5 is therefore accepted.
The next requirement is extraction only, not translation: reuse that immutable v12 run as the first
segment, extract only physical pages 324–328, and expose the combined material as one Sources/review
entry. No real provider call is authorized by this design step.

ADR 0018 is now authoritative and supersedes ADR 0014's whole-range default for new incremental
work. CCEF 1.1 remains unchanged. A consumer-side PDF extraction document owns ordered immutable
runs and immutable aggregate revisions. Each append binds the exact predecessor aggregate hash and
expected version, permits only an adjacent page range on the same asset, and advances the document
head only after the new run and deterministic aggregate commit succeed. Failed/cancelled work leaves
the previous head readable. Translation, automatic/parallel splitting and multi-source documents are
deferred.

Cross-segment chess continuity is explicit rather than inferred by title or FEN. A versioned internal
continuation context catalogs every eligible locally-valid baseline sequence/root/node in source
order, with distinct IDs even for transposed positions, canonical FEN and an at-most-eight-move path
tail. The future provider delta may bind only to those hash-bound anchors; a deterministic compositor
will revalidate the selected edge, remap IDs/evidence/annotations/reading flow and produce a new
aggregate normalized hash without overwriting any provider/raw/segment-normalized artifact. Formal
review sessions for incremental documents must bind an exact aggregate revision, so 8D-4 remains
paused through 8D-3E.

The active bounded worker packet is `DS-STAGE8-INCREMENTAL-CONTEXT-01` in `PLANS.md`. It may edit
only a new pure `extraction/incremental.py`, its focused synthetic test, and append completion evidence
here. It must not touch CCEF contracts/Schema, provider/prompt, persistence/API/UI or call a real
model. Codex review is mandatory before 8D-3E1 can be accepted.

### Automatic worker stopped at operator request

Codex started the automatic DeepCode launcher for `DS-STAGE8-INCREMENTAL-CONTEXT-01`, then the
operator restored the earlier manual relay workflow and explicitly requested termination. The
launcher was interrupted with SIGINT (exit 130), and no DeepCode tmux session remains. The worker
left an untracked 294-line `backend/src/chess_workbench/extraction/incremental.py`; it had not created
`backend/tests/test_extraction_incremental.py`, had not run the packet gates, had not appended its own
completion report and had not committed. Treat that module as unreviewed partial work, not a completed
packet. `git diff --check` is clean. The next manually launched DeepCode turn should resume the exact
packet in `PLANS.md`, inspect and correct the partial module, add all frozen tests, run only the listed
focused commands, append completion evidence, stop before 8D-3E2 and report `pending Codex review`.

## DS-STAGE8-INCREMENTAL-CONTEXT-01 (8D-3E1) completion

Status: **pending Codex review** — not started 8D-3E2, no commit/stage/unstage/reset.

### Actual files changed
- `backend/src/chess_workbench/extraction/incremental.py` (untracked, previously partial/unreviewed): audited item-by-item against the frozen packet (9 required behaviors); the existing module already satisfied the frozen API (model field shapes, strict/frozen/extra=forbid config, exact-type TypeErrors, fixed ValueError messages, locally-normalized oracle via `normalize_chess_moves_v1_1` + `model_dump(mode="json")` equality, item-order projection, root/node anchors, at-most-8 tail cap, global contiguous `anchor-N` ids, distinct transposition anchors, no input mutation). **No production edits were required** — the module stands as written.
- `backend/tests/test_extraction_incremental.py` (new, 19 tests): frozen focused oracles — exact mainline projection (17 anchors, mirror loop against normalized package), long-line tail capped at final 8 (Ruy), transposed equal FENs remain distinct anchors, invalid/ambiguous/ineligible exclusion with eligible branches kept, raw/tampered rejection, null baseline range / overlap / gap / page>20000 / malformed SHA / exact-type misuse, every sequence/context relation rejection (duplicate seq id, non-contiguous/duplicate anchor ids, anchor/container mismatch, root-not-first, two roots, duplicate after_node_id, root-with-tail, node-with-empty/mismatched tail), model shape/strict/frozen/extra=forbid/JSON round trip, determinism + input non-mutation, multi-sequence order/titles/global ids, import-purity subprocess proof (contracts+validation+incremental only; no Sanic/SQLAlchemy/store/services/provider/prompting/candidates/consolidation; python-chess allowed).
- `docs/agent/HANDOFF.md` (this append only).

### Acceptance commands and results (packet-verbatim)
1. `uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_extraction_incremental.py backend/tests/test_extraction_validation_v1_1.py` → **28 passed** (19 new + 9 v1.1 validation)
2. `uv run --project backend --locked ruff format --check backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → **2 files already formatted**
3. `uv run --project backend --locked ruff check backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → **All checks passed**
4. `uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → **Success: no issues found in 2 source files**
5. `git diff --check` → **clean**
6. `git diff --stat` → both files untracked (`??`); nothing else touched.

### Assumptions
- "root FEN shared by eligible valid roots" interpreted strictly: first eligible valid root's `fen_before` wins; other eligible valid roots must match it (parents never guessed by FEN).
- Empty `sequences` is permitted by the frozen shape; projection emits only `MoveSequenceItemV1_1` items with at least one eligible valid root, in source item order.
- Transpositions to identical canonical FENs remain distinct anchors (different ids/tails), as frozen.

### Remaining risks
- Continuation context is consumer-side pure value model only; stitching/merge/trust/I/O are out of scope and must land in later 8D-3E packets.
- The 8D-3E1 oracle relies on the existing normalizer's canonical FENs (`en_passant="fen"`), which was verified against synthetic trees only.

## Codex review: DS-STAGE8-INCREMENTAL-CONTEXT-01 changes requested

Codex independently reproduced 28/28 focused tests, clean Ruff format/lint and configured MyPy
(using workspace-local uv cache after the sandbox correctly rejected the default home cache).
Anchor projection, normalized-baseline equality, parent-chain/FEN filtering, source/global order,
eight-ply tails, transposition identity, strict/frozen shapes and import purity match the frozen
packet. No broad suite or real provider call ran.

Two protocol blockers remain, so 8D-3E1 is not accepted and 8D-3E2 must not start:

1. The builder accepts a deliberately different but syntactically valid 64-hex SHA instead of
   comparing it with the canonical normalized package bytes. Independent output:
   `fake_hash_accepted True True` (the stored hash equals the fake and differs from the independently
   computed accepted candidate hash). This contradicts ADR 0018's exact hash-bound context.
2. Direct construction/JSON parsing of `CcefContinuationContext` accepts overlapping, gapped or
   over-20,000 page ranges because those checks exist only in the builder. Independent output:
   `overlap_context_accepted True`. A later serialized prompt/binder value therefore cannot rely on
   the strict model alone.

`PLANS.md` now contains the bounded correction packet
`DS-STAGE8-INCREMENTAL-CONTEXT-01-R1`: compute/verify the accepted canonical CCEF SHA locally with a
fixed non-leaking mismatch error, centralize the page relation helper in model + builder, and add
focused valid-hash/Unicode/direct-model range regressions. The original files, behavior and 19 tests
must be preserved. Status: pending DeepCode R1; no commit.

## DS-STAGE8-INCREMENTAL-CONTEXT-01 R1 completion

R1 correction packet executed inside the original permitted edit boundary
(`backend/src/chess_workbench/extraction/incremental.py`,
`backend/tests/test_extraction_incremental.py`, this HANDOFF append-only).

Files changed:
- `backend/src/chess_workbench/extraction/incremental.py` — added `import hashlib`,
  `import json`; new private `_canonical_package_bytes(package)` implementing the frozen
  canonical CCEF bytes (`json.dumps(model_dump(mode="json"), ensure_ascii=False,
  allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"`);
  new private `_check_page_relations(base_range, next_range)` with frozen check order
  (overlap first, then non-adjacency/gap, then end_page <= 20_000, fixed messages),
  now called from both the `CcefContinuationContext` model validator and the builder
  (no drift); builder docstring updated; builder now recomputes the canonical SHA-256 of
  the proven normalized package and rejects a well-formed-but-wrong supplied hash with the
  fixed content-free `ValueError("base normalized CCEF SHA-256 does not match package")`;
  malformed SHA remains a Pydantic `ValidationError` (context constructed before
  comparison). No new public export; `__all__` unchanged; frozen fields, anchor
  generation, ordering, tails and CCEF 1.0/1.1 contracts untouched.
- `backend/tests/test_extraction_incremental.py` — added `import hashlib`; new
  independent `_canonical_sha(package)` test helper (formula mirrored, not imported from
  production); `_build` default `sha` now `None` → independently computed real canonical
  SHA (placeholder `SHA_64` no longer used for successful builds); existing 19 tests
  preserved (updated only where they previously passed the placeholder hash). New R1
  regressions: wrong-but-well-formed hash rejected with fixed non-leaking message (omits
  package text, ids, both hash values); Unicode/multibyte package accepted with canonical
  hash and raw-bytes proof of `ensure_ascii=False` + single trailing newline; direct
  `CcefContinuationContext` construction rejects overlap / gap / end_page 20_001 via the
  model validator.

Results (packet acceptance commands, run in repo root):
1. `uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' backend/tests/test_extraction_incremental.py backend/tests/test_extraction_validation_v1_1.py` → **31 passed** (22 incremental incl. 3 new R1 regressions + 9 validation v1.1).
2. `uv run --project backend --locked ruff format --check backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → clean (2 files already formatted).
3. `uv run --project backend --locked ruff check backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → clean (one UP012 auto-fixed in test file).
4. `uv run --project backend --locked mypy --config-file backend/pyproject.toml backend/src/chess_workbench/extraction/incremental.py backend/tests/test_extraction_incremental.py` → Success, no issues.
5. `git diff --check` → clean.
6. `git diff --stat` → no tracked diff for these files (both are untracked: `??` in git status; HANDOFF is tracked and modified only by this append).

Assumptions / remaining risks:
- Canonical hash comparison happens after normalization-equality proof; the supplied hash is
  validated by constructing the strict model first so malformed SHA stays a Pydantic
  `ValidationError` (shape check) while a valid-but-wrong hash becomes the fixed `ValueError`.
- `_check_page_relations` is private and duplicated nowhere; model and builder share it.
- No production modules other than `incremental.py` were touched; no commit/stage/reset;
  8D-3E2 not started; no provider/network calls; all fixtures remain invented synthetic chess.

Status: **pending Codex re-review** (8D-3E1 R1). No commit created.

## Codex implementation: 8D-3E2A document persistence/API core

Status: **core complete; pending mechanical 8D-3E2B contract/oracle packet**. No commit, provider,
worker or real-book operation ran.

Codex froze the detailed persistence boundary in ADR 0018 and `PLANS.md`. A logical document is the
only mutable head projection. Successful segment memberships and aggregate revisions are immutable;
append attempts are separate immutable receipts whose linked Job remains the sole status source.
Failed/cancelled attempts do not become segments or advance the head. The new Job kind
`pdf_incremental_extraction` is intentionally absent from the current worker handler map until
8D-3E3.

Core files added/changed:

- `backend/src/chess_workbench/store/models/extraction.py`, model exports and Alembic env: document,
  segment, revision and append identities with RESTRICT FKs/uniques/checks;
- `backend/migrations/versions/20260822_0012_incremental_pdf_documents.py`: portable migration;
- `backend/src/chess_workbench/services/pdf_documents.py`: verified CCEF 1.1 first-run adoption with
  CAS reuse, deterministic identity, hash/version-bound adjacent append registration, idempotent
  replay, active-attempt exclusion and failed-attempt retry;
- `backend/src/chess_workbench/schemas/pdf_documents.py` and `api/pdf.py`: strict create/list/get/
  append public contracts and routes; no CAS path/provider/raw/key disclosure;
- `backend/tests/test_pdf_documents.py`: three focused synthetic functional oracles covering adopt,
  append, replay, stale/non-adjacent/parallel rejection, failed retry, worker-kind isolation and the
  HTTP grouped read path.

Focused evidence:

- `test_pdf_documents.py` → **3 passed** (sandbox-external only because the tool sandbox could not
  start even a bare aiosqlite `:memory:` worker thread; the same command completed in 2.96 s outside);
- existing `test_stage8_models.py` → **7 passed**;
- dedicated temporary SQLite migration `base -> head -> 0011`, then `0011 -> head` +
  `alembic check` → clean, `No new upgrade operations detected`;
- changed-file Ruff check and configured MyPy → clean; `git diff --check` → clean.

No broad suite or generated-contract command ran. The active bounded Flash packet
`DS-STAGE8-INCREMENTAL-DOCUMENT-ORACLES-01` may only add model/OpenAPI oracle tests and regenerate
OpenAPI/TypeScript; it must stop instead of editing the Codex-owned core. 8D-3E3 has not started.

## Codex final re-review: 8D-3E1 accepted

Codex independently ran the exact focused suite with the workspace-local uv cache: 31/31 passed
(22 incremental + 9 existing CCEF 1.1 validation), Ruff format/check clean and configured MyPy
clean. A separate adversarial invocation now returns only the fixed errors
`base normalized CCEF SHA-256 does not match package` for a different valid 64-hex hash and
`next page range overlaps the base page range` for direct invalid context construction. Review of
the actual module confirms the accepted candidate canonical UTF-8/sorted/compact/single-newline
formula, shared page relation helper, unchanged frozen field/API shape and no new dependency or
forbidden import.

8D-3E1 is accepted. No full suite, provider call or commit ran. The next step is 8D-3E2, but its
document identity, migration, append transaction, optimistic concurrency and public API are
Codex-owned high-risk work; do not give that unsplit step to DeepCode. Codex must first freeze and
own those boundaries, then may delegate separately bounded mechanical tests/UI work.

Chronology note: Codex subsequently completed the 8D-3E2A core described in the preceding
`Codex implementation: 8D-3E2A` section. The current next action is the read-only/mechanical
`DS-STAGE8-INCREMENTAL-DOCUMENT-ORACLES-01` packet in `PLANS.md`; 8D-3E3 remains unstarted.

## DS-STAGE8-INCREMENTAL-DOCUMENT-ORACLES-01 (8D-3E2B) — STOPPED at model oracle prep: MySQL constraint-name length invariant violated

Per the packet stop-and-report rule ("如果测试发现 Codex 核心实现或迁移存在问题，不要自行修复生产代码，
也不要弱化测试；立即停止并报告"), the mechanical oracle prep STOPPED before writing the oracle test
files because the frozen invariant "constraint identifiers ≤64 characters" is violated by the
Codex-owned core (models + migration 0012). No production file was edited; no oracle was weakened;
no commit was created.

- **Failed command (the probe that would be asserted by `test_pdf_document_models.py`)**: compiling the
  four new tables with the MySQL dialect and measuring named-constraint lengths, i.e.:
  `CreateTable(t).compile(dialect=mysql.dialect())` for `pdf_extraction_documents`,
  `pdf_extraction_document_segments`, `pdf_extraction_document_revisions`,
  `pdf_extraction_document_appends`, then `max(len(c.name))`.
- **Full error**: 8 foreign-key constraint names exceed MySQL's 64-character identifier limit
  (ER_TOO_LONG_IDENT / error 1059 would be raised on MySQL 8); max length is 94 chars:
  - 71 fk_pdf_extraction_document_appends_document_id_pdf_extraction_documents
  - 68 fk_pdf_extraction_document_appends_extraction_run_id_extraction_runs
  - 92 fk_pdf_extraction_document_appends_predecessor_revision_id_pdf_extraction_document_revisions
  - 73 fk_pdf_extraction_document_revisions_document_id_pdf_extraction_documents
  - 94 fk_pdf_extraction_document_revisions_predecessor_revision_id_pdf_extraction_document_revisions
  - 89 fk_pdf_extraction_document_revisions_terminal_segment_id_pdf_extraction_document_segments
  - 72 fk_pdf_extraction_document_segments_document_id_pdf_extraction_documents
  - 69 fk_pdf_extraction_document_segments_extraction_run_id_extraction_runs
  (42 named constraints total on the four tables; other invariants verified OK: ENGINE=InnoDB 4,
  ON DELETE RESTRICT 9, ascii_bin present, utf8mb4_bin present.)
- **Minimal suspected production files**:
  1. `backend/migrations/versions/20260822_0012_incremental_pdf_documents.py` — the 8 too-long
     `op.f(...)` FK constraint names appear in `create_foreign_key`/`create_table` calls.
  2. `backend/src/chess_workbench/store/models/extraction.py` — the four model classes inherit the
     shared naming convention and produce the identical too-long names in metadata.
  3. `backend/src/chess_workbench/store/base.py` — `NAMING_CONVENTION["fk"] =
     "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"` is the root pattern that
     generates names >64 chars for long table names (changing it globally would affect all tables,
     so the likely fix is explicit short `ForeignKeyConstraint` names in models + matching
     `op.f(...)` names in the migration, keeping `compare_metadata` in sync).
- **Frozen invariant believed violated**: 8D-3E2B model oracle — "Compile just the four new tables
  for MySQL: prove InnoDB, binary ASCII hash/key identity, case-sensitive revision paths, RESTRICT
  foreign keys, and **constraint identifiers ≤ 64 characters**."

Status: **STOPPED — awaiting Codex to fix the constraint-name lengths in the frozen core (models +
migration 0012) before the mechanical oracle tests can be written green**. 8D-3E3 not started; no
commit created.

## Codex correction: 8D-3E2B MySQL FK identifier blocker resolved

Codex accepted the stop report. The probe was valid: the shared naming convention produced eight
new FK names over MySQL's 64-character limit even though SQLite migration and Alembic drift checks
were green. The global convention and all historical tables were deliberately left unchanged.

Only the Codex-owned 8D-3E2 core was corrected:

- `backend/src/chess_workbench/store/models/extraction.py`: all nine new document/segment/revision/
  append FKs now carry explicit stable `fk_pdf_doc_*` names;
- `backend/migrations/versions/20260822_0012_incremental_pdf_documents.py`: the same nine names are
  frozen in migration metadata.

Independent verification:

- MySQL `CreateTable` probe: `ENGINE=InnoDB` 4, `ON DELETE RESTRICT` 9, over-64 identifiers `[]`,
  maximum named-constraint length 63;
- focused `test_stage8_models.py`: 7 passed;
- focused `test_pdf_documents.py`: 3 passed;
- fresh temporary SQLite `base -> head`, `alembic check`, `head -> 0011`: passed with no drift;
- changed-file Ruff/MyPy and `git diff --check`: clean.

Actual workspace inspection also shows `backend/openapi.json` and
`frontend/src/types/api.generated.ts` modified with the new routes, despite the stopped report saying
`make contracts` was not run. These bytes are preserved as unverified user/agent work. The resumed
packet must regenerate and verify them rather than assuming either the report or current diff is
authoritative. No oracle test files exist yet. Resume the same
`DS-STAGE8-INCREMENTAL-DOCUMENT-ORACLES-01` packet; production remains read-only and 8D-3E3 remains
unstarted.

## DS-STAGE8-INCREMENTAL-DOCUMENT-ORACLES-01 (8D-3E2B) — completion

Resumed the packet from the beginning after Codex's FK-name fix. Treated the previously modified
`backend/openapi.json` / `frontend/src/types/api.generated.ts` as unverified and regenerated them.

Files changed (all inside the permitted edit boundary):
- `backend/openapi.json` — regenerated via `make contracts` (new routes confirmed).
- `frontend/src/types/api.generated.ts` — regenerated via `make contracts`.
- `backend/tests/test_pdf_document_models.py` (new) — model/migration oracle for the four new tables:
  exact column sets; UUID + aware-UTC round trips; mutable lifecycle (`version`/`updated_at`)
  only on `PdfExtractionDocument` while segment/revision/append stay immutable receipts; SQLite
  CHECK/UNIQUE/RESTRICT rejection proofs (FK enforcement enabled via PRAGMA listener); MySQL DDL
  compile (ENGINE=InnoDB ×4, ON DELETE RESTRICT ×9, ascii_bin hashes, utf8mb4_bin revision path,
  DATETIME(6), constraint identifiers ≤ 64, max observed 63); migration↔metadata parity via
  `compare_metadata == []`; offline MySQL downgrade contains no `DROP INDEX` before the four new
  tables' `DROP TABLE` statements.
- `backend/tests/test_pdf_document_contracts.py` (new) — OpenAPI contract oracle: exactly the four
  frozen operation IDs at frozen `/api/pdf-extraction-documents...` paths; create 200/201 (body
  requires `initial_run_id`), list 200, get 200/404 (required `document_id` path param), append
  200/202/404/409/422 with optional `Idempotency-Key` header and body requiring
  `expected_version >= 1`, `first_page`/`last_page` 1..20000, optional `profile`; read schema is
  grouped (segments/revisions/append_attempts with Job status) and leak-free (no CAS
  `relative_path`, provider/raw response fields, API keys, or OCR text); error responses reuse the
  shared `ErrorResponse` schema; generated TypeScript contains the three document path keys.
- `docs/agent/HANDOFF.md` — this completion evidence (append only).

Acceptance command results (packet-verbatim):
- `make contracts` — OK, contracts regenerated.
- pytest `test_pdf_document_models.py test_pdf_document_contracts.py test_pdf_documents.py`
  — **18 passed** (7 model + 8 contract + 3 existing functional).
- `ruff format --check` (two new test files) — clean.
- `ruff check` (two new test files) — clean.
- `mypy --config-file backend/pyproject.toml` (two new test files) — success.
- `make check-contracts` — "generated contracts are up to date".
- `pnpm --dir frontend typecheck` — exit 0 (Node engine WARN only, non-blocking).
- `git diff --check` — clean.

Assumptions / remaining risks:
- Alembic `compare_metadata` does not compare FK names, so the FK-name divergence between migration
  0010/0012 and model metadata (`fk_pdf_doc_asset` vs convention names) is invisible to the
  migration-parity oracle. It is not a MySQL schema-global collision (each universe's names are
  unique); flagging for Codex awareness only.
- 8D-3E3 (worker wiring for `pdf_incremental_extraction`) intentionally not started.

Status: **pending Codex review** (8D-3E3 未开始). No commit created.

## Codex minimum incremental database/browser delivery (2026-08-23)

Operator request: connect the already-verified pages-324–328 JSON to the smallest database commit
and merge flow so pages 319–328 appear as one browser entry. DeepCode remains disabled; no provider
call was made and no broad suite/acceptance gate was run.

Implemented:

- `backend/src/chess_workbench/extraction/incremental.py`: added deterministic
  `compose_incremental_ccef`. It rebuilds and verifies the hash-bound continuation context, requires
  a locally normalized adjacent package, attaches bound roots only to declared anchors, remaps
  node/annotation/flow IDs, retains independent items and produces a CCEF 1.1 document package.
- `backend/src/chess_workbench/services/pdf_documents.py`: added replay-safe
  `commit_verified_append`, which requires the registered segment normalized artifact, stores
  canonical aggregate JSON in CAS, creates immutable segment/revision rows and atomically advances
  the optimistic-lock document head.
- `backend/src/chess_workbench/services/pdf_review.py`: when an extraction run ID is absent, the
  same read-only review endpoint now resolves a document ID, verifies its head revision, continuous
  segments, aggregate CAS bytes and exactly one rendered PNG for every covered physical page.
- `scripts/commit_incremental_ccef.py`: no-provider operator command that adopts the accepted v12
  run, registers/replays the adjacent append, renders/stores pages 324–328, stores the verified
  segment JSON, composes and commits revision 2, and marks the exact append Job succeeded.
- `frontend/src/logic/api/types.ts` and `frontend/src/app/SourcesPage.tsx`: load grouped document
  contracts, show one `连续文档` card and hide its constituent extraction-run cards; the card reuses
  the existing review route with the document ID.

Real local result:

- pre-migration backup: gitignored
  `data/debug/chess-workbench-before-incremental-20260823.db`;
- database upgraded from `20260811_0011` to `20260822_0012`;
- document ID `b08ebf6d-856d-587f-9293-aa89eb81e573`, append run
  `76011064-aa16-517e-852f-2908f6283d95`, version 2, segments 319–323 + 324–328;
- aggregate SHA-256 `720b60b27d6f94f84d9185ffb6760e113c855a1070e34cf3eb7475bb87678120`;
- aggregate shape: 20 items; `seq_intro_classical` 8 nodes, `seq_game_13` 233 nodes/24
  annotations, `seq_game14` 24 nodes/3 annotations; 265 nodes total, zero non-valid nodes;
- review service returned document ID identity, all page descriptors 319..328 and a verified PNG
  page 328 (556,638 bytes); inspection has one expected blocking issue for the existing non-chess
  player photo on page 322, not a move/composition defect;
- real HTTP checks returned the one grouped document, 10-page aggregate JSON and page-328 PNG;
- system-Chrome Playwright spot check: one grouped card, one grouped review link, 10 page-switch
  buttons, page-328 image present, correct document review URL.

Focused verification only: changed Python Ruff format/lint, changed-file MyPy, frontend typecheck,
offline real-package composition, live service read, live HTTP read and one browser path. The first
Playwright attempt used the package-managed browser and stopped because its binary was not
installed; the next attempt used existing `/usr/bin/google-chrome`. A locator was then scoped to
the page-switch region because evidence buttons legitimately repeat `第 328 页`; the scoped real
browser check passed. Temporary API/Vite processes were stopped afterward.

Remaining boundary: the reusable queued-worker handler for generic future incremental jobs is not
installed (8D-3E3 remains open). The current accepted JSON is fully committed and browser-visible;
exercise this product path before expanding worker plumbing or tests. No commit was created.

## Codex source-library refactor (2026-08-23)

The operator clarified that a PDF book is the durable library identity, while one book may own any
number of extraction outcomes: disjoint ranges, overlapping ranges and repeated requests for the
same range must all remain visible. Codex implemented the smallest front-end/API slice without a
new SQL identity:

- `frontend/src/app/SourcesPage.tsx` now renders one card per immutable `PdfAsset`. Opening the card
  shows one management drawer containing every standalone extraction run plus every incremental
  document for that asset. Runs committed as document segments are shown inside their document and
  are not duplicated as top-level outcomes; equal page ranges are never deduplicated.
- Every user-requested standalone extraction and exact-range retry sends a fresh visible-ASCII
  `Idempotency-Key`, so the existing API creates a distinct immutable run even when asset, page
  range and profile match an older run.
- A successful standalone candidate can be adopted as an incremental document. Existing documents
  expose the registered adjacent-append API from the same action menu; the real 319–328 document
  correctly opens an append form fixed to page 329 with a five-page default through page 333.
- Review links remain available for committed standalone candidates and aggregate documents.
  Modify and delete/archive are intentionally visible but disabled: modification belongs to the
  Stage 8D review-revision boundary, and deletion must be implemented as authoritative archiving,
  not a front-end-only or hard-delete shortcut.
- `frontend/src/logic/api/types.ts` adds generated response aliases only. `PLANS.md` records the
  active slice, and ADR 0018 now makes `PdfAsset` the top-level library identity with multiple
  independent run/document outcomes below it.

Focused verification only:

- Prettier wrote the two changed TypeScript files; changed-file ESLint passed with zero warnings;
- frontend TypeScript build/typecheck passed (only the existing Node 24 vs required Node 22 engine
  warning);
- real API + Vite + system Chrome showed one book card for the local asset, 13 distinct extraction
  outcomes in its drawer, the 319–328 aggregate with its 319–323 and 324–328 segments, and the
  expected management controls;
- a Playwright route interception (no backend mutation/provider call) proved exact-range retry for
  319–323 carries a fresh `Idempotency-Key`; another read-only browser check proved the append form
  starts at 329 and defaults to 333;
- `git diff --check` was clean before this append. No feature/full suite, provider call, database
  write, commit, reset or deletion was performed.

Recommended next action: let the operator interact with the library drawer. Then choose one narrow
follow-up: (a) authoritative archive/delete for extraction outcomes, (b) the missing reusable
incremental worker so drawer-created append jobs execute automatically, or (c) Stage 8D-4 review
revision persistence for real content editing. Do not combine those boundaries.

## Codex review: 8D-3E2B completion requires one test-only R1

Codex inspected the actual diff instead of accepting the completion report. The 18 focused tests
were green, but the stated FK-name divergence was a real blocker rather than a harmless remaining
risk: `fk_pdf_doc_asset` had been attached to historical `ExtractionRun.pdf_asset_id`, while the new
`PdfExtractionDocument.pdf_asset_id` still used the automatic convention. The existing oracle only
checked name length/count, and Alembic `compare_metadata` does not compare constraint names, so both
missed the name-to-relation mismatch.

Codex corrected only the two ORM declarations in
`backend/src/chess_workbench/store/models/extraction.py`: the historical `ExtractionRun` FK is again
unnamed and the new document-to-asset FK now explicitly uses `fk_pdf_doc_asset`, matching migration
0012. A direct metadata probe enumerated the intended nine `fk_pdf_doc_*` mappings with the correct
table, local column and target relation.

Independent focused verification after the correction:

- pytest `test_pdf_document_models.py test_pdf_document_contracts.py test_pdf_documents.py`:
  **18 passed**;
- changed-file Ruff format/lint and MyPy: clean;
- `make check-contracts`: generated contracts up to date;
- frontend typecheck and `git diff --check`: clean.

The completion remains **pending 8D-3E2B R1**. `PLANS.md` now freezes a test-only DeepCode packet to
assert the exact nine ORM mappings, the exact migration-0012 MySQL DDL mappings and the historical
`ExtractionRun` non-hijack regression. Production/migrations/generated contracts are read-only for
R1. 8D-3E3 has not started; no commit was created.

## Operator scope reset and real incremental JSON checkpoint

The operator disabled all subsequent DeepCode delegation because of DeepSeek API pricing and made
the product-development policy explicit: this is primarily a personal site, so iterative work must
prove the real artifact/browser outcome first; tests must be proportional to actual risk and broad
proof/coverage gates wait for Stage closure. `AGENTS.md` now records both durable rules. The planned
test-only 8D-3E2B FK R1 was cancelled; Codex had already enumerated the corrected mappings and the
18 focused tests were green.

Codex added `scripts/run_incremental_ccef_probe.py`, an operator-only output-first probe. It:

- loads accepted v12 run `4b33f70a-b623-5ec3-bc8e-5ed6a2a28e4a` and verifies canonical baseline
  hash `e52c27b2a9ebd4662b4edd75b8071a4abdda4f00374d667b5dd1bdd78384ac74`;
- builds the existing bounded 122-anchor continuation context for pages 324–328;
- renders 52 embedded-text fragments from the same verified PDF and makes at most the one explicitly
  acknowledged paid call;
- preserves request/context/provider response/decoded/raw/normalized/report artifacts under
  gitignored `data/debug/stage8d-incremental-pages-324-328.*`.

Offline prepare succeeded with an 88,523-character message. Exactly one DeepSeek call then returned
`finish_reason=stop`, usage 43,199 input / 80,084 output / 123,283 total tokens. No retry or second
paid call occurred. The original local gate rejected one redundant provider FEN: the model selected
correct `anchor-122` and emitted first move `17.Rae1` as White, but copied the anchor side-to-move as
`b` instead of trusted `w`. The raw provider response and error were retained. Codex generalized the
binder so the model chooses only a valid hash-bound anchor ID and the trusted local anchor supplies
the authoritative FEN before chess validation, matching the existing trusted evidence-binding
principle rather than adding book/page/move-specific handling.

Reprocessing the same saved response, without another provider call, produced:

- 6 items, 3 sequences, 145 move nodes, 20 annotations;
- Game 13 alternative: 7 valid nodes, bound to `anchor-121` after baseline node `n111`;
- Game 13 continuation: 114 valid nodes, bound to `anchor-122` after baseline node `n112`; 92-ply
  main line from `17.Rae1` through `62...Bh4` plus 7 correctly parented local variations;
- Game 14: independent start-position sequence, 24 valid nodes; 15-ply main line through `8.c3`
  plus 3 correctly parented variations;
- 0 invalid, 0 ambiguous, and all 183 EvidenceRefs bound exactly to pages 324–328 fragments.

Only the probe file received Ruff format/check and `py_compile`; both passed. No feature/full suite,
acceptance, smoke, worker, database write, aggregate composition or UI work ran. Remaining boundary:
this is a validated local segment JSON, not yet a persisted incremental Job artifact, aggregate
revision or browser-visible grouped document. Next work should connect this proven request/binder to
the minimal worker + composition path and verify the real browser result before adding tests. No
commit was created.

## Codex generic incremental worker completion (2026-08-23)

The operator asked for the smallest path that makes a drawer-created append run instead of staying
queued. Codex installed `process_pdf_incremental_extraction_job` and registered it under the
existing API worker's distinct `pdf_incremental_extraction` kind. The handler reuses the ordinary
PDF renderer/OCR artifact pipeline, builds the existing bounded continuation context, performs one
thinking-enabled CCEF 1.1 request, binds evidence and trusted continuation anchors, stores immutable
provider/raw/normalized artifacts, composes the aggregate and calls the existing atomic document
commit. A retry with a complete normalized artifact skips the provider call.

Compatibility behavior is general rather than source-specific: older operator-created segments
that lack an `ocr_fragment` for their terminal page obtain context-only tail text by rendering that
page from the verified original PDF. No production code contains a book name, fixed page number,
move, node count or content hash. `SourcesPage` no longer claims that the incremental executor is
missing. `PLANS.md` and ADR 0018 now mark 8D-3E3 installed.

Real outcome-first verification used the append the operator had already submitted for pages
329–332. The original attempt failed before any provider call because the historical pages-324–328
operator segment had no terminal OCR artifact; it remains an immutable failed attempt. A new retry
run `96d8f8b6-8d4c-5238-a82e-4a6149c2297a` made exactly one paid request and retained all artifacts.
Its first commit encountered a transient SQLite heartbeat/write collision; the Job returned to
queued, and the new bounded commit retry then reused the saved CCEF without a second provider call.
Job `84cee502-8dc4-460a-9881-cb098b8c1420` succeeded on attempt 2. Document
`b08ebf6d-856d-587f-9293-aa89eb81e573` is revision 3 with continuous pages 319–332 and aggregate
hash `962c5def7110bd73f05855d52ac697f624e73f3a785383edc1a756d6d319a00c`.

The new segment is valid CCEF 1.1: 4 items, 2 sequences, 86 move nodes, 23 atomic annotations,
0 invalid/ambiguous nodes and evidence only on pages 329–332. One 70-node sequence continues a
trusted prior anchor; the other is an independent Game 15 start-position score. The aggregate has
23 items, 4 sequences, 351 valid nodes and evidence pages 319–332. The review service loaded all
14 page descriptors; its sole issue is the already-known unsupported non-chess figure from the
earlier segment.

Focused checks only: Ruff check and changed-file MyPy passed for the three backend files; the API
app imported successfully; Prettier check passed for `SourcesPage.tsx`; canonical segment/aggregate
model validation, offline inspection, persisted Job/document/segment queries and a direct review
service read all passed. No unit/full/acceptance suite ran. The local HTTP check could not run
because no API process was listening on port 8000; restart `make dev-api` to load the new handler,
and run `make dev-web` as usual. No commit was created.

## Codex incremental pages 333–341 failure diagnosis and prevention (2026-08-24)

The operator submitted two browser-created incremental requests for pages 333–341 and asked for
diagnosis plus a generic fix without any retry. No Job, worker run or provider call was created by
Codex during this work.

- Run `444a4e29-75dd-5cfe-a72e-a6966d458b1e` / Job
  `dda95a5a-022e-4643-b90d-97d978d8b040` received a complete 108,813-byte CCEF 1.1 JSON response
  with `finish_reason=stop`. Strict local validation rejected it because sequence
  `seq_game15_cont_333` reused node ID `g15p333_v15Be5` for two different `Be5!` nodes on different
  parents. This was an opaque-identity collision, not missing continuation context or truncation.
- Run `fd802a39-f8c0-5ff1-b340-b6751ed40a7a` / Job
  `58d3b38c-a0cb-42f0-9820-e286a1ff27e4` received HTTP 200 and `finish_reason=stop`, but the formal
  assistant `content` was empty. The provider placed an approximately 87,046-character JSON-looking
  document in private `reasoning_content`; all 32,173 completion tokens were reported as reasoning
  tokens. The adapter correctly rejected the response instead of treating chain-of-thought as
  application data. DeepSeek's official JSON Output guide documents occasional empty content, and
  its Thinking Mode guide defines `reasoning_content` as CoT and `content` as the final answer.

The incremental prompt now explicitly requires opaque, mutually unique node/annotation IDs and a
final distinct-ID plus ordered-reading-flow audit. The first mitigation disabled thinking so JSON
would be requested directly in the formal final channel; the strict provider boundary continued to
ignore private reasoning fields. This mitigation was evaluated by the next real operator request
and then replaced by the follow-up recorded below. No retry was initiated by Codex.

## Codex incremental pages 333–341 third failure and revised transport fix (2026-08-24)

After the operator restarted and submitted another browser request, run
`2ab9d13a-89d3-5351-a35e-39a43def2711` / Job
`02cba45a-4209-48ab-a7f0-33fc06d1657c` failed once with `ccef_invalid_package`. Its formal
`content` was non-empty and contained no duplicate local IDs, so the immediately preceding prompt
and channel fixes addressed both earlier failure signatures. The new strict diagnostics showed
that all 181 move nodes carried the redundant forbidden field `kind: "move"`. Offline removal of
only that field exposed another schema error, `initial_position={"kind":"startpos","startpos":{}}`.
More importantly, the non-thinking response had split one continuing score into 36 move sequences,
35 bound to the same anchor, so silently stripping fields would have accepted materially poorer
topology and was rejected as a repair strategy.

The prior `thinking_enabled=False` mitigation was therefore replaced. Incremental requests again
use thinking mode with max effort, but opt out of DeepSeek's provider-side `response_format` JSON
Output switch, whose official guide documents occasional empty final content. The existing
deterministic system instruction still supplies the complete caller-owned JSON Schema and demands
one raw JSON object; the existing strict JSON/CCEF decoder remains unchanged. The generic DeepSeek
adapter gained a default-on `json_output_enabled` constructor switch, so every non-incremental
caller retains its previous wire request. Private `reasoning_content` remains ignored and is never
promoted into application data. The previously added unique-ID audit remains in the incremental
prompt.

Focused verification only: two DeepSeek transport tests passed (normal thinking profile plus the
new thinking-without-response-format case), Ruff format/check passed for the four touched backend
files, and MyPy passed for the three production files. No full suite, database write, worker run,
provider call or retry was performed. The failed run and capture remain unchanged; the operator
will restart the API and submit the next request manually. No commit was created.

## Codex trusted evidence-selector boundary (C+D) (2026-08-24)

The newest browser append failed at strict CCEF decoding even though the provider returned a
complete, semantically useful result. Run `83e2dea7-d267-5b2b-8326-c7171246d87f` / Job
`490a2327-ca00-48b4-bb42-0383ff7d330e` contained 310 EvidenceRefs. Every one of their
`physical_page + fragment_sha256` selectors resolved to a fragment supplied in the trusted prompt,
but 304 provider bboxes used the wrong component order and 159 therefore violated the positive-area
box invariant. The prior pipeline attempted strict model validation before its local evidence
binder, so the authoritative fragment hashes never got a chance to repair provider-owned geometry.

The evidence boundary now uses the generic C+D design. The provider owns only the semantic
selector `(physical_page, fragment_sha256)`. Before full CCEF validation, local code walks only
defined EvidenceRef slots, discards provider bbox/text offsets unconditionally, resolves the exact
trusted OCR fragment, writes its canonical `[x0, y0, x1, y1]` normalized bbox and leaves offsets
null. Missing or unknown hashes and trusted-key collisions still reject the candidate. There is no
coordinate-order guessing, approximate-bbox lookup, axis swap, or book/page/move special case. The
incremental service uses the same boundary before continuation binding, and semantic prompt version
1.6 instructs providers to emit only the selector.

The saved failed response was processed offline through the new trusted binding, metadata and
continuation checks, chess normalization and deterministic document composition, with no provider
call or database write. It produced 3 items, 1 sequence, 210 valid nodes, 42 annotations and a
319–341 aggregate with 25 items; all 310 evidence references bound by exact fragment hash. This
proves the current response is reusable rather than semantically lost. The persisted document was
not advanced and the failed Job was not retried or mutated.

Focused verification only: four semantic candidate/prompt tests passed; Ruff format/check passed
for the five directly touched files; MyPy passed for the three production files. The broader worker
integration test was intentionally not rerun after it twice stalled in its existing aiosqlite
cleanup path; the real saved-response offline chain is the outcome-level verification for this
change. ADR 0018 now records the trust boundary. No full suite, network/provider call, database
write, retry or commit was performed.

## Codex retained-response topology repair (2026-08-24)

Incremental v5 now has a bounded repair path for complete CCEF 1.1 responses whose only structural
failure is the exact-order projection between a move sequence's arrays and `reading_flow`. The
original response is retained. A compact second request grants the provider authority only over
existing-node `parent_id`/`sibling_order`; it includes projection counts, forward-parent conflicts,
python-chess frontier failures, locally computed legal preceding-parent candidates and only the
trusted OCR fragments cited by the affected sequence. Local code then compacts sibling-order gaps,
reorders arrays to the unchanged reading flow and reruns CCEF, evidence, metadata, continuation,
python-chess and composition gates. Repair is attempted once and its failure is non-retryable.

The operator script `scripts/repair_incremental_capture.py` prepares, executes or replays this
protocol without SQL writes. It writes a paid repair response before applying any local gate, so a
bad repair is still diagnosable. Transport-invalid HTTP bodies use the existing retained-response
recorder. The normal online incremental worker uses the same protocol; the repair call uses direct
JSON/non-thinking mode because the local diagnostics have already reduced the task to a small
patch, avoiding another long reasoning-only response.

Real replay used failed run `3d997da3-f630-5698-82be-ae2353f25716` / Job
`21e91952-3767-49da-913b-4029adbcd80e` and its retained 83,208-byte response. The repair request
identified one affected sequence, 13 downstream chess failures, three forward-parent conflicts and
legal-parent hints that pointed the page-335 alternatives back to the page-334 `...c5` position.
One earlier thinking-mode tool attempt was interrupted before a response could be retained; a
second thinking-mode call returned an invalid provider envelope, but the offline runner had not yet
wired the transport-invalid recorder, so its exact rejected shape and usage are unavailable. After
switching the bounded repair to non-thinking JSON mode, the real response completed
with 50,260 input + 271 output = 50,531 tokens, versus 207,508 tokens for the original full
extraction. It selected the three correct parent changes but naturally left a sibling-order gap;
generic local compaction (not a book/page/move special case) resolved that mechanical consequence.

Replaying that exact saved DeepSeek response passed: 316/316 EvidenceRefs bound by trusted fragment
hash, all 218 segment move nodes normalized `valid`, and composition produced 25 aggregate items
covering physical pages 319–341. Debug outputs are gitignored under
`data/debug/incremental-repair-3d997da3-f630-5698-82be-ae2353f25716.*`. No database row, document
head or failed Job was changed; no full extraction retry occurred. Focused Ruff and MyPy checks for
the three implementation files passed. No full/unit/acceptance suite was run and no commit was
created.

## Codex Stage 8D-4 review ledger (2026-08-24)

Stage 8D-4 is complete in the worktree. ADR 0016 and PLANS now freeze a review session as the pair
of one target identity (standalone extraction run or incremental document) and the exact normalized
CCEF hash verified when the session is opened. A later incremental document head creates a separate
hash-bound session; it never moves an existing review baseline.

Migration `20260824_0013` adds `pdf_review_sessions` as the only mutable review head and immutable
`pdf_review_revisions` / `pdf_review_events`. Revision 1 points at the already verified normalized
CCEF CAS object (run artifact or document aggregate revision) and event 1 records the 0 -> 1
`created` transition. The schema is ready for 8D-5 expected-version commands, but 8D-4 deliberately
does not implement edit/acknowledge/approve/reject/reopen or frontend controls. The same migration
adds `SourceSpan.fragment_sha256`; page locators can now retain bbox plus optional paired text
offsets, while non-page locators cannot misuse the fragment hash.

Public operations are `POST /api/pdf-extractions/{target_id}/review/session` (create or replay the
session for the currently verified candidate) and `GET /api/pdf-review-sessions/{session_id}`
(ledger metadata). Responses include target/hash/status/version plus ordered revision/event facts,
but exclude CAS paths, CCEF contents, provider/raw response data and secrets. OpenAPI and generated
TypeScript were regenerated.

Focused verification only: the new ledger/migration/evidence tests plus the existing strict
SourceSpan schema test passed (4 total); the migration chain matched runtime metadata; direct MySQL
DDL compilation produced three InnoDB tables with maximum constraint-name length 47; focused Ruff
and MyPy passed; `make check-contracts` and frontend TypeScript typecheck passed. The first attempted
aiosqlite integration test stalled in the repository's known worker-thread cleanup/runtime issue,
so the accepted focused service oracle uses a deterministic fake session while the migration is
verified synchronously against SQLite. No full/Stage acceptance suite was run.

No production database migration or service restart occurred during this work. The concurrently
running incremental Job `abf97e58-eea2-42da-818b-66ad6d8d687a` was never touched; it independently
finished as `failed` with `ccef_invalid_package` at 2026-08-23 18:46:28 UTC. The new migration will
be applied automatically by the next `make dev-api`. No commit was created. Next delivery item is
8D-5 review commands.

## Codex generic retained-response repair (2026-08-24)

The topology-only admission gate has been superseded by a generic bounded repair protocol. A
complete JSON response is scanned into at most 32 structured diagnostics spanning Pydantic/CCEF
shape errors, duplicate/forward identities, sibling numbering, reading-flow projections,
annotation anchors, trusted evidence selectors and later pipeline failures. At most eight affected
items plus their cited trusted fragments and incremental context are sent in one repair request.
The provider returns a `chess-workbench/ccef-repair/2.0` JSON patch bound to the exact original
response hash, rather than regenerating the extraction.

The patch boundary allows `add`/`remove`/`replace` on existing package fields but forbids replacing
the whole package or resizing item/node/annotation/evidence collections. It limits operations,
bytes and source-text delta, requires the exact trusted metadata after repair, and rejects every
evidence selector not present in the prompt context. The incremental worker now offers this repair
for any parseable small validation failure, calls the provider at most once, then reruns its normal
trusted evidence, metadata, continuation, chess normalization and composition chain. Successful
artifacts retain the original response, repair response and repaired-content hash; repair failure
remains non-retryable and never advances the document head.

The newest retained pages-333–341 response now produces an actionable diagnostic at
`/items/0/nodes/204/sibling_order` for node `g15c_v727`, in addition to the bounded root contract
diagnostic; it is no longer rejected as `not_repairable`. Applying that exact one-field change to a
copy of the retained response passes strict CCEF 1.1 validation with 3 items and 218 move nodes. A
synthetic patch for the same invariant and a non-topology forbidden-field removal both pass the
generic boundary; destructive node removal and invented evidence are rejected. The three focused
repair tests pass; focused Ruff and MyPy pass for the repair module, incremental worker, operator
script and test. The API app imports successfully.

An attempted provider-free replay through the existing database-backed operator script was stopped
after the repository's known aiosqlite read/cleanup path made no progress; it reached only
`Loading failed extraction run...`, made no provider call and did not write SQL or mutate the failed
Job. The retained-response diagnostic itself and synthetic full contract application are verified;
the next browser-created failure will exercise the online provider call. No full/Stage suite ran,
no service was started and no commit was created.

## Codex generic repair correction after run 17f667bd (2026-08-24)

The next operator-created pages-333–341 append, run
`17f667bd-35fa-5d08-bddf-20775a4fa2f1` / Job
`426e4ca7-84e7-48a6-a95d-08aa7d9ff414`, exposed two defects in the new generic repair path. The
116,229-byte original response was complete JSON and had exactly five strict errors: duplicate NAG
values at five nodes. The repair prompt nevertheless sent all eight items and the full continuation
context because package-level Pydantic locations did not populate `item_index`. It also copied the
discriminated-union label `move_sequence` into patch paths, producing paths such as
`/items/1/move_sequence/nodes/3/nags`; those keys do not exist in the JSON document. The 625-byte
repair response therefore failed with `CCEF repair path does not exist`. It also left four duplicate
NAG arrays unchanged. The repair call consumed 125,426 tokens, more input than the original request,
so the old path reduced neither cost nor failure risk.

`general_repair.py` now normalizes Pydantic locations into real JSON Pointers before deriving item
and node identities. Non-topology prompts include only the diagnosed nodes/annotations and nearby
reading-flow entries; full sequences and trusted continuation context are reserved for topology or
continuation failures. A narrow deterministic pass runs before any paid repair and currently handles
only one semantics-free canonicalization: duplicate integer NAGs are removed in first-occurrence
order. It does not choose parents, alter wording/evidence or inspect book/page/move identities. The
online worker and offline retained-response tool both validate this local candidate through their
normal pipeline first and skip the repair provider if it succeeds. Provider-response audit chains
record the deterministic rule/path list and, when a model patch is still needed, the exact repair
base hash.

Outcome verification used the saved original response only, with no Job retry or provider call. It
now yields exactly five diagnostics at the real paths
`/items/{1,6,7}/nodes/{3,6,20,36,41}/nags`, five deterministic operations, a strict-valid CCEF 1.1
package with 8 items and 97 move nodes, and a successful `normalize_chess_moves_v1_1` pass. Four
focused generic-repair tests pass, including real-pointer/item/node attribution, prompt slicing and
NAG canonicalization; focused Ruff and MyPy are clean for the production modules. A database-backed
operator replay was stopped after 40 seconds at its first aiosqlite read (the known local async DB
stall); it made no provider call and no SQL mutation. The pure retained-file gate already proves the
exact failed payload is locally repairable. No full/Stage suite, new extraction, retry or commit was
performed.

## Codex repair-flow hardening after two further failures (2026-08-24)

Two retained failures exposed separate issues. Incremental run
`59ef4f98-6360-50f5-9f4a-7532a08686c9` (pages 342–345) contained 10 items and 98 move nodes; its
only content defect was an order mismatch between one sequence's node array and reading flow. Both
sides contained the same 33 unique node IDs, and reading-flow order remained parent-before-child.
The former model-repair prompt wrapped exact entries as `{flow_index, entry}` records; the model
copied those wrappers into 30 replacement operations, so local union validation rejected the paid
repair. Standalone v4 run `b3401df0-87de-5dd9-9182-1b18a56d0559` returned HTTP 200 with 81,547
characters of private reasoning but null/blank formal content. It had no parseable candidate for a
local patch and must not treat private reasoning as application data.

The deterministic repair pass now also aligns node or annotation arrays to an exact-cover reading
flow when identities are unique and the projected node array stays topological. It never edits
reading flow, parent IDs, evidence or text. Applying it to the retained pages-342–345 response
produced one audited `align_nodes_to_reading_flow` operation (15 positions moved) and a strict-valid
CCEF 1.1 package with the same 10 items and 98 nodes, with no provider call. Model-repair excerpts
now map real JSON Pointer strings directly to exact original values, omit continuation context
unless the diagnostic is a continuation-binding failure, and forbid replacing/adding/removing a
whole reading-flow entry. This removes the wrapper-copy failure mode and substantially bounds
ordinary topology repair prompts.

Standalone semantic v4 requests keep thinking enabled but now omit DeepSeek's provider-side JSON
Output switch, matching the already working incremental v5 transport profile. Null or blank final
content is still captured, maps to the existing `invalid_response` provider code with the explicit
message `DeepSeek returned no final content; retry manually`, and remains `retryable=false`; no
automatic retry was added.

Focused verification: 12 selected repair/transport tests passed; focused Ruff format/lint and MyPy
passed for the three production modules. The retained pages-342–345 response passed strict CCEF
validation and chess normalization after the deterministic repair; all 98 nodes normalized as
valid. A database-backed full offline replay was
stopped after its known aiosqlite read path stalled at `Loading failed extraction run...`; it made
no provider/network call and was interrupted without SQL writes. No full or Stage suite, browser
retry, service start or commit was performed.

## Codex shared CCEF 1.1 pre-validation canonicalization (2026-08-24)

The operator correctly identified that standalone semantic extraction and incremental extraction
should not own separate ordering rules. `canonicalize_ccef_response` is now the named shared
pre-validation boundary. It treats `reading_flow` as source reading order and may reorder the
parallel `nodes` or `annotations` arrays only when both projections contain exactly the same unique
IDs; node projection is additionally required to remain parent-before-child. It preserves IDs,
parents, sibling orders, reading flow, evidence and source text. The former
`apply_deterministic_ccef_repairs` name remains a compatibility wrapper for the offline tool/tests.

Both CCEF 1.1 standalone candidate assemblers (including semantic v4 trusted-evidence binding) and
the incremental v5 handler now call that boundary before their first strict CCEF validation. The
standalone provider artifact changes to the existing `ccef-repair-chain/2.1` audit shape only when
canonicalization actually occurs, retaining the exact original response plus deterministic
operation/path and repaired-content hash. An unchanged response retains the existing
`provider-response/1.1` artifact bytes and schema.

The saved standalone run `1b1de1ac-0ef6-5f08-85ce-03922f03e806` (pages 6–14) was replayed through
the real semantic candidate assembler using its committed OCR fragments, without provider or SQL
writes. The shared boundary moved three positions in `/items/5/nodes`; exact evidence binding,
strict CCEF 1.1 validation and consolidation then succeeded with 6 items and 208/208 valid move
nodes, with no conflicts. This proves the previously failed paid response is acceptable under the
new shared path. The latest incremental run `22879234-69a9-5d64-a31b-129dc3546169` had already
proved the same algorithm online for an annotation projection mismatch and advanced the document
to pages 319–345/version 5 without a model repair call.

Focused verification only: 23 tests passed across generic repair and CCEF 1.1 candidate assembly;
focused Ruff and MyPy passed for the three production modules. No full/Stage suite, new extraction,
provider call, Job mutation, service start or commit was performed.

## Codex Stage 8D-5 review commands and interactive editing (2026-08-24)

Stage 8D-5 is complete in the worktree. The public command boundary is
`POST /api/pdf-review-sessions/{session_id}/commands`; every request carries `expected_version` and
one discriminated `edit/acknowledge/approve/reject/reopen` command. Successful commands append a
new immutable review revision/event and advance the mutable session head exactly once. Edited CCEF
is written to the `review-revisions` CAS namespace; state-only revisions reuse the current verified
CAS object. `GET /api/pdf-extractions/{target_id}/review` now serves the latest hash-bound review
revision when one exists, while the baseline extraction artifact remains unchanged.

Chess edits are implemented in the pure `review/editing.py` boundary. Board-entered UCI lines
traverse an identical existing child or allocate new legal nodes, using priority zero when the
position was a leaf and the last sibling priority otherwise. The other commands explicitly delete
a subtree, promote one sibling priority, make an entire selected path the mainline, choose zero or
one NAG, and edit heading/prose/in-score annotation text. Structural edits rebuild parent-before-
child node order and the exact-cover CCEF 1.1 reading flow, then run the existing python-chess
normalizer and strict CCEF validation. Delete decisions record removed node/annotation counts; old
revisions remain recoverable.

The browser review page opens/replays a session only when the user starts editing. Clicking a score
move selects its after-position; board moves either enter an existing child or build a pending line
with the currently visible PDF page as evidence. The pending line has explicit save/undo controls.
Each move exposes Lichess-style `提升变招`, `设为主线`, `设置评价` and `从此处开始删除`; heading,
prose and sequence annotations have a text editor. Current warnings can be acknowledged
individually or together. Approval is disabled and rejected server-side while blockers or current
unacknowledged warnings remain; reject/reopen are explicit audited transitions.

Focused verification only: backend review editing/ledger selection passed 8 tests, including one
CAS/ledger command chain through edit -> acknowledge -> approve -> reopen -> reject. The review UI
passed 21 focused tests, including a real generated request for variation promotion and a board-
entered new branch. Focused Ruff/MyPy, frontend ESLint/TypeScript and generated contract drift were
checked; no full suite, Stage acceptance, service/worker start, provider call, extraction mutation
or commit was performed. The persistence test replaces `asyncio.to_thread` with a direct test
adapter to avoid the repository's known aiosqlite/thread shutdown delay; production still uses the
verified threaded filesystem boundary. Next delivery item is 8D-6 atomic publication into a draft
Course/Knowledge mapping.

## Codex Stage 8D-5 first-session FK ordering fix (2026-08-24)

The browser's `开始审核` failure was reproduced from the supplied API log. SQLite rejected the
initial `pdf_review_events` INSERT because the service added the new session, revision and event in
one flush while the models intentionally expose no ORM relationships; SQLAlchemy therefore had no
unit-of-work dependency edge requiring the referenced session/revision rows to be inserted first.
The same ordering risk existed for later command revisions.

`PdfReviewLedgerService` now flushes each foreign-key layer explicitly: session, then revision,
then event for creation; revision, then event for later commands. Transaction ownership remains at
the API boundary, so any failure still rolls the whole operation back. Focused ledger/editing tests
passed (8 tests), and Ruff format/lint plus single-file MyPy passed. A temporary local API with the
engine worker disabled then retried the exact failing target
`86294c50-bbe7-568f-b51f-deb44df88e28`: POST review/session returned HTTP 201 with an open version-1
session, one created revision and one created event. The temporary API was stopped afterwards. No
full suite or unrelated checks ran; no provider/extraction worker ran and no commit was created.

## Codex Stage 8D-5 compact score and context-menu UI (2026-08-27)

The review score was rebuilt around a compact Lichess-inspired presentation without changing the
CCEF contract, ledger commands or backend. The implementation consulted the official Lichess
`ui/analyse/src/treeView` sources for its paired mainline columns, recursive inline alternatives
and viewport-aware context-menu separation; no Lichess controller or source code was copied. The
project deliberately differs from Lichess's shallow-parentheses heuristic: every actual
alternative has visible branch rails, and nested alternatives draw all ancestor rails.

`reviewMoveLayout.ts` now projects a stable alternative lineage from the existing parent/sibling
topology. Adjacent rows with the exact same lineage are grouped into one dense variation line;
different sibling branches and nested branches cannot be merged accidentally. Mainline rows remain
one fullmove per white/black row. CCEF 1.1 annotations remain in authoritative reading-flow order
but render as plain, unboxed text lines at their branch depth.

`PdfReviewPage.tsx` removes permanent per-move validity tags, row evidence badges and ellipsis
menus. Invalid nodes use a red background, ambiguous nodes amber and unvalidated nodes neutral;
common NAGs use compact chess glyphs. Right-clicking any move or in-score annotation immediately
navigates the PDF pane to its first evidence page and opens a viewport-clamped menu listing all
source pages. In edit mode the move menu contains promote/make-mainline/set-NAG/delete, while the
annotation menu contains locate/edit. Single-click board navigation and all existing semantic
commands remain intact.

Focused verification only: `reviewMoveLayout.test.ts` and `PdfReviewPage.test.tsx` passed 28 tests.
The tests cover paired mainline rows, dense same-line variations, distinct/nested branch lineage,
visible branch rails, invalid/ambiguous styling, absence of permanent status/page badges, source
auto-navigation and both move/annotation context-menu actions. Focused Prettier and ESLint passed;
the frontend TypeScript build passed. The shell used Node 24 rather than the repository-requested
Node 22 and emitted pnpm's existing non-blocking engine warning. No backend, provider, extraction,
database, full-suite or Stage acceptance command ran, and no commit was created. Browser visual
inspection at the operator's real viewport remains the next useful check.

## Codex course learning workbench refactor (2026-08-27)

The operator accepted the compact review score and requested the same reading model for ordinary
courses before 8D-6 publication. `CourseEditor` is now a three-pane workbench: the left card toggles
between the chapter directory and a verified rendered PDF page, the center retains the existing
interactive board plus local engine/arrow panel, and the independently scrolling right card owns
the compact annotated score and editing controls. Courses without a cited, resolvable PDF page keep
the source toggle disabled rather than showing unrelated library material.

`courseMoveLayout.ts` deterministically derives the primary course line from occurrence
`sort_order`, pairs white/black mainline plies, and indexes every sibling alternative with its full
nested branch path. `CourseScore.tsx` renders paired mainline rows, dense variation lines and one
rail per alternative depth. Local occurrence notes are plain in-score annotations; their source
pages are absent from the permanent reading UI and available by right-click, which also switches
the left pane to the first cited page. Opening-explorer occurrences are projected through canonical
parent positions so equivalent module roots still appear as one merged score.

The PDF adapter only considers source spans actually cited by the current module. It matches their
source file/version to a PDF asset, prefers a covering incremental document and falls back to a
covering successful candidate run, then uses the existing verified review-page endpoint. No new
backend route, persistence model or CCEF dependency was added to the course UI.

Focused verification only: `courseMoveLayout.test.ts` plus `CourseEditor.test.tsx` passed 13 tests
before the final source-filter hardening; the cited-PDF test then passed independently. Focused
Prettier, ESLint and TypeScript checks passed. A real local render of course `test2` at 1800x1100
showed a stable three-pane layout with the board/engine retained and the unavailable source toggle
correctly disabled. The temporary API used port 28100 with the engine worker disabled and the Vite
server used 5174; both were stopped. The operator's pre-existing processes on 8000/5173 were not
touched. No provider, extraction job, database mutation, broad suite or commit ran. Next product
delivery remains 8D-6 atomic publication into a Course/Knowledge draft.

## Codex course workbench width adjustment (2026-08-27)

The desktop workbench columns now target 380px for the chapter/source pane, 500px for the board and
engine stack, and 520px for the annotated score. This makes the directory easier to scan, removes
unused width from the score and reduces the board enough for all four configured MultiPV rows to
fit beneath it at the operator's demonstrated desktop height. Existing responsive breakpoints and
all interaction behavior remain unchanged. `CourseEditor.test.tsx` passed 12 focused tests;
focused Prettier, TypeScript and diff checks passed. No broad suite or backend work ran.

## Codex engine-panel layout jitter fix (2026-08-27)

Opening the course engine changed the center pane from its short loading state to four MultiPV rows.
At the one-screen height boundary, `overflow-y: auto` could repeatedly add and remove its scrollbar;
that changed the responsive board width, which changed the pane height again and produced visible
layout oscillation. Desktop `.course-board-pane` now uses `scrollbar-gutter: stable both-edges`, so
the available board width and horizontal centering remain invariant across disabled, loading and
result states. The responsive document-flow layouts are unchanged. `CourseEditor.test.tsx` passed
12 focused tests; focused Prettier, TypeScript and diff checks passed. No broad suite ran.

## Codex Stage 8D-6 multi-fragment draft publication (2026-08-28)

Stage 8D-6 now publishes only an approved, exact review revision into one existing traditional
draft Course. One request can contain multiple explicitly selected move fragments. Each fragment
targets either a top-level chapter Module or an optional example/theory child Module; either level
may own its own root score. New chapter paths are created inside the same transaction, existing
paths are course/parent checked, occupied targets and duplicate targets in one plan are rejected,
and a fragment must be locally valid with one coherent external parent/start position.

The mapper creates the Course occurrence graph through ContentService, materializes complete page/
bbox/offset/hash evidence as SourceSpan rows, maps selected CCEF 1.1 anchored annotations to
approved KnowledgeNote blocks, and stores an immutable publication receipt keyed by review session,
revision, target Course, mapping version and canonical plan hash. Exact replay returns the prior
result. The HTTP boundary is
`POST /api/pdf-review-sessions/{session_id}/publications`; migration 0014 adds only the receipt
table. Generated OpenAPI and TypeScript contracts include the new request and response.

After approval the review page exposes an explicit publication mode. The operator selects a draft
book, drag-selects a contiguous visual move range, chooses or creates its chapter and optional
subsection, adds more independently targeted ranges, then submits the whole plan atomically. The
learning course directory now renders Module parent/child relationships as an expandable tree;
the chapter title remains separately clickable, so chapters with their own score and all legacy
one-level courses remain usable.

Focused verification only: the new temporary-SQLite publication test passed (one request publishing
two fragments into a chapter score and a chapter/example score, including one anchored note); the
existing migration/metadata comparison passed; the new drag-selection/publication UI test passed;
the new expandable-parent learning-directory test passed. Existing `PdfReviewPage` 22 tests and
`CourseEditor` 12 tests had passed immediately before adding those two focused regressions. Related
Ruff, MyPy, ESLint, Prettier, frontend TypeScript, contract drift and `git diff --check` checks are
clean. The SQLite tests had to run outside the tool sandbox because sandboxed aiosqlite stalled
before schema creation. No full Stage 8/whole-repository suite, real provider call, extraction job,
runtime database migration or commit was performed.

## Codex Stage 8D review/publication follow-up (2026-08-28)

The real `scan-test` 319–345 document was inspected without mutating it. Its review session
`046b2ec3-1f9c-5b8b-bb0a-d7731554e4a7` was not waiting on a worker: it was open at version 3 with
one blocking `unsupported_figure` issue for `figure_rogers` on page 322. The product had required
explicit rejection of non-chess figures but exposed no command capable of doing that. Review edits
now include audited `exclude_item` for non-move top-level items; the issue row exposes
`排除此内容`. Applying that operation purely to the current stored revision changed its inspection
from one blocker to zero without changing the immutable extraction artifact or database.

Publication mapping is now versioned as `review-course-publication/1.1`. For CCEF 1.1, annotations
are consumed in authoritative `reading_flow` order. An unanchored annotation whose preceding move
belongs to the selected fragment is published as a KnowledgeNote after that occurrence; leading
annotations are attached to the fragment root when the first sequence move is selected. The
existing approved 319–323 revision contains 95 such annotations after the 202 selected nodes, which
explains why its earlier 1.0 publication reported `note_count=0`. Existing 1.0 receipts remain
immutable; new publication requests use 1.1. The learning page now discovers PDF citations from
occurrence context as well as notes/narrative blocks, so previously published move evidence enables
the source pane without rewriting the course. Mainline and variation notes render after their
owning move, splitting a paired white/black row only when text must appear between those plies.

The UCI cleanup boundary now treats an already-closed subprocess transport as an expected cleanup
state. It does not send `quit` through a closed handler and suppresses only close/kill transport
errors, so an HTTP/client cancellation remains `CancelledError` rather than being replaced by the
reported RuntimeError.

Focused evidence only: review editing tests passed (6); the real stored `figure_rogers` dry-run
reduced blockers 1→0; publication test passed and covers a null-anchor reading-flow note plus
occurrence source citations; the closed-transport UCI regression passed; the focused review UI,
course PDF-source and note-order tests each passed. Targeted Ruff/MyPy, ESLint/TypeScript,
contract regeneration/drift and `git diff --check` passed. No full suite, worker/provider call,
runtime database mutation, service restart or commit was performed.

## Codex SQLite write coordination and Job recovery correction (2026-08-28)

The 00:49 PDF incident was reproduced from the real database without mutating it. Job
`e8bae957-35a1-4cb6-9734-16384f8eccd2` owns run
`73f3e23c-f672-57a9-b3f9-1b295b9c91e0`; its persisted range is 15--19 inclusive (five pages, not
four). Rendering/OCR committed immediately, its final lease expired at 00:51 local time, and the
complete provider/raw/normalized CCEF artifacts committed at 00:57, but an SQLite lock failure in
the worker supervisor left the Job in `running`. `ERROR.md` is two renderings of that same failed
`retrying` invalidation write; Ctrl+C exposed the failure but did not cause the original lock.

ADR 0019 is now authoritative. File SQLite uses WAL, `synchronous=NORMAL`, a five-second busy
timeout and one pooled connection for the authoritative local process. `Database.run_write`
serializes short database-only writes and retries only completely rolled-back SQLite busy errors.
Worker claim/heartbeat/success/failure/cancellation transitions and extraction artifact
registration use that boundary. Cancellation is still polled every 100 ms, while lease heartbeat
writes occur every ten seconds. Any supervisor failure or lease loss cancels and consumes the
handler task, so provider/engine work cannot continue detached from its durable Job.

The PDF handler now verifies an already committed three-slot candidate (CAS binding, canonical
bytes, package/source/page/provenance and provider-response binding) before configuring or calling
a provider. A complete set reconstructs the versioned Job result and summary locally; a partial or
inconsistent set fails closed. On a SQLite backup of the real database, the stuck payload restored
five pages, five content items and 138 move nodes with a provider fake that would fail on any call;
the observed provider call count was exactly zero. The real database and CAS were not changed.
After the next API restart the expired lease can be claimed again and this Job should finish from
its artifacts. A separate Job `892f62b3-9a2a-48ba-9854-a8a3b2c4095d` remains queued and may perform
its own provider request afterward; it was deliberately not cancelled or modified.

Focused relevant verification passed 87 tests across database, worker/engine, real Stockfish, PDF
execution/recovery and PDF API paths. The final worker lifecycle file passed 15 tests. Ruff format,
Ruff lint, strict MyPy on the four changed production modules and `git diff --check` are clean. A
broader no-coverage backend run was intentionally performed for this cross-cutting infrastructure
change: 1349 passed, 4 skipped and 6 unrelated pre-existing Stage 8 oracle failures remained. They
are one stale candidate-error-code assertion, two tests with hard-coded pre-0012 migration counts,
and three review API tests that still mock `PdfReviewReadService` after the route was previously
switched to `PdfReviewLedgerService`; none exercises SQLite coordination or Job recovery. No real
provider call, runtime migration, service start, runtime database write or commit was performed.

## Codex extraction-task cancellation and archival (2026-08-28)

The Sources task menu now performs a real recoverable delete through
`DELETE /api/pdf-extractions/{run_id}`. The endpoint runs one coordinated database write: queued
Jobs become `cancelled`, running Jobs receive `cancel_requested_at`, and terminal Jobs keep their
terminal state; every case receives `archived_at` and disappears from extraction discovery. The
worker's existing 100 ms cancellation monitor cancels and awaits a running provider handler, while
immutable `ExtractionRun` and artifact receipts remain readable directly for audit. Incremental
document views also omit archived append attempts. Migration `20260828_0015` adds only the nullable
Job archival marker; no runtime database was migrated by Codex.

The book drawer exposes `取消并删除`, `停止并删除`, or `删除任务` according to persisted Job state.
Incremental-document menus can remove their latest attempt while preserving the logical document
and committed segments. The operation requires confirmation, refreshes both run and document
lists, and uses a 204-capable HTTP helper. The dropdown triggers now have explicit click behavior
and accessible names.

Focused verification: the archive API lifecycle test passed outside the tool sandbox (the same
aiosqlite test stalled inside it); it proves queued/running/failed transitions, hidden discovery,
and retained direct audit access. SQLite migration/metadata and MySQL upgrade/downgrade DDL checks
passed, including the now-current 15-revision count. OpenAPI/TypeScript regeneration and drift
check passed. The focused Sources deletion UI test, frontend lint and typecheck passed; the wider
legacy `WorkbenchPages` file still contains unrelated stale Sources mocks and was not treated as a
task gate. No provider call, live task cancellation, runtime database mutation or commit occurred.
## 2026-08-28 — Course learning score controls and section lifecycle

- Added authoritative course-score commands at
  `POST /api/occurrences/{occurrence_id}/commands`: promote one variation,
  make a path mainline, set/clear NAG, and archive a move subtree. Sibling
  priority updates and subtree archival are transactional and use optimistic
  versions.
- Added `POST /api/course-modules/{module_id}/archive-tree`. It archives a
  level-1/level-2 module subtree, its authored blocks/notes/occurrences, and
  any live opening-explorer reference cards that point at the removed source.
  Explorer reads therefore omit invalidated references instead of resolving
  an archived source and throwing.
- Course UI now has move right-click actions (`提升变招`, `设为主线`,
  `招法评注`, `从此处开始删除`), mainline start/previous/next/end navigation,
  a `记录走棋` switch, and board flip. Recording defaults on for compatibility;
  while off, legal board moves stay as an unpersisted analysis line.
- Both directory levels expose a gear menu with rename and subtree delete.
  Move/note right-click continues to jump the PDF pane to its first available
  cited page; page provenance is kept in the menu rather than always visible.
- Regenerated OpenAPI and TypeScript contracts. Focused verification only:
  `backend/tests/test_course_learning_commands.py` **2 passed** (real SQLite
  API; all four score commands plus nested-module deletion/reference
  invalidation), `CourseEditor.test.tsx` **13 passed**, frontend typecheck,
  focused Ruff/mypy, `make check-contracts`, and `git diff --check` all clean.
  No full suite or Stage acceptance was run.

## 2026-08-28 — Fixed score footer and same-parent directory sorting

- The course content card now has two explicit regions: `课程内容滚动区` owns
  the long annotated score/editor content, while `棋谱导航与棋盘设置` is a
  non-scrolling card footer. Start/previous/next/end, move recording and board
  flip therefore remain visible without scrolling to the end of a long game.
- Chapter rows expose a small drag handle. A drop is accepted only when source
  and target have the same `parent_id`; top-level chapters can reorder among
  themselves and children can reorder inside their current parent, but a child
  cannot be moved into another chapter. The UI updates optimistically and then
  persists contiguous sibling `sort_order` values through the existing module
  PATCH endpoint with expected versions.
- Focused verification only: `CourseEditor.test.tsx` **14 passed**, including
  controls outside the scroll region, an accepted same-parent reorder and a
  rejected cross-parent drop with no PATCH; focused ESLint and frontend
  TypeScript checks passed. `git diff --check` is clean. No backend change,
  schema generation, full suite, runtime database write, service restart or
  commit was performed.

## 2026-08-30 — Shared local chess-diagram evidence

- ADR 0020 makes diagram recognition an optional local evidence adapter inside the existing PDF
  pipeline. PDFium exposes bounded embedded-image candidates; a replaceable ONNX recognizer uses
  generic grid/border geometry plus 64-square classification; a local resolver accepts an
  operational FEN only when a nearby numbered SAN move uniquely validates side-to-move and move
  number through python-chess. No book title, page, move, position or expected-count special case
  exists in production code.
- Recognized diagrams become ordinary `origin=diagram` `SourceEvidenceFragment` values inserted by
  page position into the same text/OCR stream. Standalone and incremental extraction therefore
  retain one button/HTTP boundary, artifact kinds, CAS ownership, prompt/provider call, CCEF
  normalization, repair, review and publication path. Missing models, no detections and local
  recognition errors leave ordinary text extraction available. Invalid/oversized embedded image
  objects are skipped rather than failing an otherwise renderable page.
- Prompt 1.8 copies only a non-null locally supplied FEN, distinguishes a new score start from an
  in-score diagram checkpoint, and forbids inventing a position from an unresolved diagram. The
  semantic extraction fingerprint is v14, so new behavior cannot overwrite old immutable runs.
- The local model installer pins the MIT fenshot 0.1.4 ONNX model by SHA-256. The installed model at
  `data/models/chess-diagram/chess-tiles-v2.onnx` matched
  `883f6a8e639e6d6b6399b3fda0508ad772e3c6f9cefa2e678a13f27b9fa6248d`. ONNX Runtime telemetry is
  disabled before import by default, preventing the observed `:memory:.ses` repository artifact.
- Real local, provider-free probe of *Endgame Strategy* physical pages 19--22 found exactly one
  diagram on each page and resolved all four without ambiguity: page 19 move 36 white, page 20 move
  37 white, page 21 move 53 white, page 22 move 55 black. All four piece placements and exact FENs
  were produced by the generic pipeline; unresolved count was zero.
- Focused verification only: diagram/PDFium/prompt/config selection **90 passed**, the added
  ordinary-page preservation regression **2 passed**, focused Ruff and strict MyPy passed, and
  `git diff --check` is clean. No full suite, database migration/write, service start, commit or
  provider call was performed.
- The operator then requested the real extraction through the browser. Run
  `f6edec0b-2c86-5a39-a812-4eb6aa086fe1` reached DeepSeek and preserved a 94,816-byte CCEF 1.1 JSON
  response, but strict validation rejected all 167 evidence references: the response used
  `physical_page` where `EvidenceRef.page` is required. The cause was an internal prompt/schema
  contradiction: prompt 1.7 explicitly asked the model to select `physical_page` although the
  supplied schema names the field `page`; diagram recognition and extracted chess content were not
  the failure.
- Prompt 1.8 now says `EvidenceRef.page = fragment.physical_page` and explicitly forbids
  `physical_page` inside EvidenceRef. The shared standalone/incremental pre-validation canonicalizer
  also renames this exact alias only in contract-owned evidence slots. An absent canonical field or
  an equal redundant alias is safe to normalize; conflicting `page`/`physical_page` values remain
  untouched and fail strict validation. The repair never traverses source envelopes or extensions
  and records each operation in the repair-chain artifact.
- The saved response was replayed locally through the production canonicalizer without mutation or
  a provider call: 167 alias operations yielded a strict-valid package with 12 items and zero
  diagnostics. A prior full candidate replay of the same response produced 102 move nodes, zero
  invalid/ambiguous moves, zero warnings/errors/unresolved items and no conflicts. Focused repair,
  candidate and prompt tests passed (**36 passed**); focused Ruff and strict MyPy passed, and the
  prompt/fingerprint constant test passed. The selected HTTP enqueue integration test did not
  complete in the current tool environment and was interrupted without an assertion failure; it
  was not replaced by a broad suite. The old failed run was not modified or retried; new requests
  use prompt 1.8/fingerprint v14.

## 2026-08-30 — Course subsection engine precomputation

- The course engine panel now exposes `分析本小节` beside its settings button. The selected
  Module's occurrence FENs are collected from the existing editor payload, deduplicated exactly and
  terminal positions are skipped. The panel processes them sequentially through the existing
  `POST /api/engine/analyses` boundary, preventing a burst of parallel Stockfish subprocesses.
- A compact line progress indicator reports completed/total positions. Individual failures do not
  discard successful earlier work; completion reports the failed count and the operator may run it
  again. The batch controller and progress now belong to the course workbench rather than the
  replaceable Module panel: switching Module keeps the original task running and the newly rendered
  panel identifies the source Module by title while showing its live progress. Leaving the entire
  course page aborts unfinished work, while every already completed analysis remains durable.
- No new persistence or queue model was introduced. `EngineAnalysis` already stores successful
  results under the ADR 0009 cache identity: complete six-field FEN, source, engine name/version and
  all engine parameters. Consequently revisiting the same position with the same profile uses the
  existing cache and avoids Stockfish computation; changing analysis settings intentionally creates
  another cache identity.
- Focused verification only: one browser oracle proved two unique subsection positions are
  requested once each and reaches `2 / 2` plus the saved state; a second delayed-response oracle
  switched from `第一章` to `第二章` mid-analysis, proved the first task remained visible/running and
  then completed `2 / 2`. The complete CourseEditor file previously passed **15 tests**; the final
  correction ran only these **2** owning tests. Focused Prettier, ESLint and TypeScript checks
  passed. No backend schema, contract generation, broad suite, service start, runtime database
  write or commit was performed.

## 2026-08-30 — Fast persisted engine cache hits

- The observed approximately one-second delay was not Stockfish search: `process_analysis_job`
  launched a fresh UCI process through `probe()` before it could construct the version-bound cache
  key. A focused real fake-engine timing reproduced **1019.82 ms** for the first identity probe and
  **0.08 ms** for the second cached lookup.
- `UciEngine.probe_cached()` now shares an in-process identity across capabilities, synchronous
  analysis, background analysis and engine-game creation. Its key includes resolved path, device,
  inode, byte size, nanosecond mtime and nanosecond ctime. Replacing/upgrading the executable changes
  that key and forces a new UCI probe, preserving ADR 0009's engine-version cache isolation. Missing
  executables still use the existing explicit error path. Concurrent first callers may perform a
  redundant probe but can never receive an identity for a different file.
- Course position debounce was reduced from 220 ms to 80 ms. Superseded requests still use the
  existing AbortController cleanup, so rapid score navigation does not leave detached computation.
  The first engine use after an API restart may still pay one identity probe; all later cache hits in
  that process avoid it, and opening capabilities or running subsection precomputation warms it.
- Focused verification: the identity reuse/file-change regression passed (**1 test**); focused Ruff,
  strict MyPy, Prettier, ESLint, TypeScript and `git diff --check` passed. The separately selected
  pre-existing async database cache test hung in the current tool environment after the identity
  test passed and was interrupted without an assertion failure; no broad suite or runtime database
  mutation was used.

## 2026-08-30 — Subsection analysis excludes persisted cache hits

- `POST /api/engine/analyses/cache-lookup` accepts a bounded unique list of legal canonical FENs and
  one engine parameter profile. One query reads candidate `EngineAnalysis` rows; a row counts only
  when its complete parameters match and it belongs either to Syzygy v1 or to the currently probed
  Stockfish name/version. The response preserves request order in disjoint `cached_fens` and
  `missing_fens` lists. Unknown/old-engine/different-profile rows remain missing.
- The course batch now has an explicit cache-checking phase. Only `missing_fens` enter its sequential
  analysis loop and progress denominator; cached positions are reported as skipped. An all-cached
  subsection displays that fact and sends zero `/engine/analyses` requests. Lookup failure fails
  closed and starts no analysis rather than silently recomputing everything.
- OpenAPI and generated TypeScript were regenerated. Focused verification passed: **2** backend
  identity/cache-selection tests and **2** browser subsection tests; the browser oracle supplied one
  cached and one missing FEN, observed `1 / 1`, and proved only the missing FEN reached analysis.
  Focused Ruff/MyPy/Prettier/ESLint/TypeScript and contract-drift checks passed. No broad suite,
  service start, runtime database mutation or commit was performed.

## 2026-08-31 — Evaluation-weighted course engine arrows

- The course board no longer assigns recommendation-arrow strength from the MultiPV array index.
  It converts white-perspective centipawn or mate scores to the same bounded logistic
  winning-chance scale used by Lichess, reverses it when Black is to move, and compares every line
  with the best line.
- The best move is a saturated blue at 0.86 opacity. Alternatives continuously desaturate toward
  grey and fade from 0.64 to 0.26 as their winning-chance loss approaches 0.2; alternatives at or
  beyond that loss are omitted. The existing arrow-count control remains an upper bound, and no
  board dependency or custom SVG layer was introduced because react-chessboard accepts per-arrow
  color but not per-arrow width.
- Focused verification only: the owning CourseEditor browser test passed (**1 test**) and now proves
  three close evaluations produce three distinct, monotonically weaker RGBA colors. Focused
  Prettier, ESLint and TypeScript checks are recorded with this change; no broad suite or commit was
  performed.

## 2026-08-31 — MultiPV positions with fewer legal moves

- The reported position `2kr1b1r/ppp2ppp/8/3P3q/2P1p1n1/4Bn1P/PP3PP1/RN1Q1RK1 w - - 1 13`
  is in check and has exactly three legal moves (`Kh1`, `Qxf3`, `gxf3`). Stockfish correctly
  returned three lines for a requested MultiPV of four; the prior backend check incorrectly treated
  the requested count as mandatory.
- `UciEngine.analyze()` now requires `min(requested MultiPV, legal root move count)` lines. It still
  rejects truncated output when further legal root candidates exist, so this does not relax general
  malformed-output detection. The course panel retains the configured number of display slots and
  renders unavailable lines as blank rows with no evaluation, move text or recommendation arrow.
- Focused verification only: the exact three-legal-move UCI regression passed (**1 test**) and the
  owning CourseEditor browser regression passed (**1 test**) with three blank slots for its
  one-line fixture. Focused Ruff, MyPy, Prettier, ESLint, TypeScript and `git diff --check` passed.
  No broad suite, service start, database mutation or commit was performed.

## 2026-08-31 — Re-recording a soft-deleted course move

- The Game 13 failure was traced to archived occurrence
  `b49294d0-cc72-41c1-983a-168112c0fd60`: it is `h2h3` below the active `8...e6` occurrence and
  occupies sibling order 1 after deletion. With active `Nc3` at order 0, the browser correctly
  requested order 1 for a newly recorded `h3`, but `create_move_occurrence()` returned the archived
  row as a successful create. The refreshed editor excludes archived rows, so the browser's
  missing-selection fallback jumped to the subsection root.
- Move creation now resolves the complete active/archived sibling set. An active requested slot is
  idempotent only for the same move/context; an archived occupant is relocated to the next archive
  slot when necessary. A matching archived move/context is explicitly restored at the requested
  active order. Its old descendants, notes and invalidated references remain archived. This also
  handles a different new move colliding with an archived sort slot rather than relying on an
  `h3`-specific path.
- After POST, the course browser now verifies that the refreshed subsection actually contains the
  returned occurrence ID before selecting it. A bad/stale response produces a visible save error
  and preserves the current board instead of silently selecting the root.
- Focused verification: the real temporary-SQLite archive/collision/restore lifecycle and the
  existing reorder/annotate/delete lifecycle passed (**2 backend tests**); normal browser move
  persistence and the missing-refreshed-node safeguard passed (**2 frontend tests**). Focused Ruff,
  MyPy, Prettier, ESLint, TypeScript and `git diff --check` passed. The database tests required the
  established sandbox-external runner because file-backed SQLite initialization stalled inside the
  tool sandbox. No runtime database row was changed, no broad suite was run and no commit was made.

## 2026-09-01 — UCI delayed-ready cancellation race

- The reported uvloop callback `InvalidStateError` was reproduced deterministically by delaying the
  fake engine's `readyok` response and cancelling analysis during that handshake. The old wrapper
  cancelled `protocol.analysis()` directly; python-chess then received `readyok` and attempted to
  complete its already-cancelled command result future.
- Analysis startup is now shielded from caller cancellation. Cleanup closes the engine before it
  drains an abandoned startup command and, if startup completed during shutdown, also retrieves the
  inner `AnalysisResult` termination. Play commands likewise remain pending until subprocess close
  and are drained afterward instead of being cancelled while their UCI transport is live.
- The exact delayed-ready regression failed before the production change and passes under uvloop
  afterward without loop exception-handler events or a surviving process. Three adjacent timeout,
  in-search cancellation and play-cancellation regressions also pass (**4 focused tests** total).
  Focused Ruff and strict MyPy passed, and `git diff --check` is clean. No broad suite, service start,
  runtime database write or commit was performed.

## 2026-09-02 — Independent diagram-started incremental segment

- The latest *Endgame Strategy* append run covered physical pages 23--27 and failed after one main
  provider call with `incremental response has no continuation binding`. Local diagram evidence was
  present: six diagrams were detected, five had operational FENs, and the provider correctly used
  the page 23 and page 26 FENs to start two new independent scores. The remaining page 25 analysis
  diagram was conservatively unresolved. The failure was not diagram recognition.
- Pages 19--22 end with the heading and metadata for Game 3 but contain move sequences only for
  Games 1 and 2. The next segment therefore correctly supplied Game 3 as a new FEN-started sequence,
  rather than falsely binding it to an anchor in either prior game. ADR 0018 already specifies that
  unbound sequences are appended as new content, but the service binder contradicted it by requiring
  a positive binding count for every segment.
- `_bind_continuations` no longer imposes that global count. Every binding that is present still
  requires the exact predecessor hash and a supplied anchor; a segment with no bindings is allowed
  to proceed as independent content. One synthetic regression covers a prior sequence plus an
  unbound diagram-started next score (**1 focused test passed**).
- The exact saved 23--27 response was replayed offline without a provider call or SQL write. It now
  normalizes to seven items, two sequences and 177 valid move nodes, then composes into a 19-item,
  four-sequence aggregate spanning pages 19--27. Focused Ruff and strict MyPy passed and
  `git diff --check` is clean. The historical failed run remains immutable and was not retried or
  committed; a new browser request is still required to advance the document head.

## 2026-09-02 — Course-level learning-page actions

- Added settings buttons to both the learning catalog card and the opened course title with
  `重命名课程` and `删除课程` actions, matching the existing subsection interaction. Rename PATCHes
  the course with its expected version and updates the visible title from the returned authoritative
  value without a redundant refetch.
- Delete uses the existing recoverable `archived: true` course update rather than hard deletion,
  preserving modules, knowledge and shared position rows, then returns to the learning catalog.
- Focused verification covers both entry points. No backend or public-contract change was necessary
  because course rename/archive already existed.

## 2026-09-02 — Review resolution for unusable position anchors

- The open *Endgame Strategy* document review was inspected read-only. Its sole remaining blocker
  is `position_anchor_no_match` on sequence annotation `ann-g2-analysis-diagram` from physical page
  22: the annotation's FEN does not occur in the extracted score. The prose and move tree themselves
  remain readable; excluding the earlier figure item could not resolve this nested annotation.
- Added the auditable `detach_position_anchor` review edit for unmatched or ambiguous position
  anchors on top-level prose or sequence annotations. It accepts only a currently reported blocking
  issue, preserves text, evidence and reading-flow position, changes the anchor to null in a new
  review revision, and never mutates the immutable extraction candidate.
- The issue row now offers `保留文字并取消局面关联` while an open review is being edited. A dry-run
  against the exact saved Endgame review revision changed inspection from one issue/one blocker to
  zero/zero without writing SQL or CAS. One focused backend regression and one focused browser
  regression passed; contracts were regenerated and checked.

## 2026-09-02 — Lichess-style binary variation parentheses

- Course and PDF-review scores now follow Lichess's inline-tree heuristic: when a position has
  exactly two continuations, its sole secondary line is short and its next six plies do not branch,
  that line is rendered in parentheses. Three-way forks, nearby nested forks and long side lines
  retain explicit branch rails.
- The presentation decision is shared by both score projections; move identity, topology, order,
  board navigation, annotations and right-click actions are unchanged. Parenthetical lines expose
  `data-variation-presentation="parenthetical"` and no rail elements.
- Focused verification passed: nine layout/browser tests covering a short binary branch, a
  three-way fork, a nested-nearby fork, the learning score and the review score. Focused ESLint and
  TypeScript checks also passed. No broad suite, backend test, service start or commit was run.

## 2026-09-03 — Parenthetical variation placement correction

- Corrected the first pass against Lichess's actual recursive render order. Course alternatives
  leaving the main score always retain a branch rail. Within an already explicit variation, one
  short secondary continuation is rendered as an inline parenthesis immediately after the move
  where the fork occurs and before that variation's primary continuation resumes.
- `CourseScore` now renders nested variations while walking each parent variation move instead of
  appending every nested variation after the full parent line. Move selection, notes, right-click
  actions and occurrence topology are unchanged. The PDF-review projection also no longer marks
  depth-one alternatives as parenthetical.
- Focused verification passed: nine selected layout/browser tests, including DOM order
  `branching move → parenthesized alternative → primary continuation`; focused ESLint, TypeScript
  and `git diff --check` passed. No broad suite, backend test, service start or commit was run.
