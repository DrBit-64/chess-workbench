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
