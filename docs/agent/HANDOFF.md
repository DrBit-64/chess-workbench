# Agent handoff

## Goal

Start Stage 8 with prerequisite 8P: freeze a model-provider-neutral and consumer-neutral AI
recognition contract before implementing PDF storage, OCR, cloud calls or ChessWorkbench publishing.
The user selected DeepSeek V4 Flash as the first/default provider but requires the recognition
output to be reusable by other websites.

## Working state

- Branch: `main`; accepted committed baseline: `209e35b feat(codex): finish stage 6`.
- Worktree was clean before the current documentation design changes.
- Stage 6 is accepted. Stage 5/6E and Stage 7 remain deferred.
- ADR 0010 defines the accepted CCEF v1 architecture; `docs/architecture/ccef-v1.md` freezes its
  exact field-level contract. It clarifies ADR 0006: the portable extraction package is mapped to
  internal Blocks only by a downstream ChessWorkbench ConsumerAdapter.
- 8P-1 CCEF v1 portable contract is accepted after Codex final review: 43 focused tests and all
  configured static gates pass; runtime UTC handling and the checked-in Schema pattern agree.
- `PLANS.md` contains the only active implementation packet:
  `DS-STAGE8-PROVIDER-PORT-01` (8P-2 provider Protocol plus deterministic scripted fake).

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

## Active DeepSeek V4-Flash instruction

Use DeepSeek V4-Flash with thinking enabled at `high` effort for development. Implement only
`DS-STAGE8-PROVIDER-PORT-01` from `PLANS.md` and obey its exact permitted file list. This is a
medium-risk provider interface and requires Codex review before the real DeepSeek adapter.

Do not implement provider HTTP calls despite the provider choice. This packet has no model default,
API key, network, PDF, OCR, CCEF decoding, SQL, job, route, configuration, dependency or migration
work.

## Required completion report

Report:

1. exact files changed;
2. behavior and validators implemented;
3. exact focused test count and every acceptance command result;
4. confirmation that the fake accepts caller-owned arbitrary JSON Schemas without importing CCEF;
5. assumptions and any interface ambiguity;
6. `git diff --stat` and `git diff --check` result;
7. status `pending Codex review` and confirmation that 8P-3 was not started.

Do not commit, rebase, reset, install dependencies, weaken checks or expand the permitted boundary.

## Next route after review

After Codex accepts 8P-2, issue a separate packet for the real DeepSeek adapter using mocked HTTP.
Chess validation and consumer proof remain separate later packets. Stage 8A SQL/public API work
cannot be assigned to V4-Flash under current `AGENTS.md` because database schema, public interfaces
and state-machine changes are explicit escalation boundaries.

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
