# Current plan

## Goal

Begin Stage 8 through the portable protocol prerequisite **8P**. The AI recognition core must be
independent in both directions:

- model providers are replaceable; DeepSeek V4 Flash is the first/default implementation;
- recognition output is the versioned CCEF JSON contract, not ChessWorkbench SQL/domain objects;
- downstream sites implement ConsumerAdapters without changing provider or extraction code.

ADR 0010 is the authoritative architecture decision. Stage 6 is accepted at commit `209e35b`;
Stage 5/6E and Stage 7 remain deferred.

## Delivery order

1. [x] **8P-1 portable contract:** strict Pydantic CCEF v1 models, deterministic JSON Schema and
   malformed/reference/tree-order fixtures.
2. [x] **8P-2 provider port:** consumer-neutral structured-generation protocol and deterministic
   fake provider; no HTTP or SQL.
3. [ ] **8P-3 DeepSeek adapter:** V4 Flash non-thinking transport behind the provider port, with
   recorded/mock HTTP success, empty JSON, timeout, malformed payload and usage tests; no live API
   calls in PR tests.
4. [ ] **8P-4 validation:** package/reference validation plus python-chess move-tree normalization;
   illegal and ambiguous candidates remain reviewable and never become `valid`.
5. [ ] **8P-5 consumer proof:** a standalone sample consumer that imports only the published JSON
   Schema/package, plus a ChessWorkbench mapping plan. No SQL writes yet.
6. [ ] Codex feature-boundary review of 8P, then proceed to 8A immutable sources/page-range jobs.

Only independently verifiable V4-Flash packets may be active. Do not combine the steps above into
one cross-module implementation.

## Completed packet: DS-STAGE8-PROVIDER-PORT-01

### Objective

Implement only the provider-neutral in-process structured-generation port and a deterministic
scripted fake. This packet defines how later DeepSeek/Qwen/OpenAI/local adapters receive prompts
and a caller-owned JSON Schema; it performs no HTTP call and knows nothing about CCEF fields.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/provider.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (export the new public port types)
- `backend/tests/test_extraction_provider.py` (new)
- `docs/agent/HANDOFF.md` (completion evidence only)

Do not edit `contracts.py`, the CCEF Schema artifact, dependencies, configuration, jobs, SQL,
routes, services, existing tests or any other file.

### Exact public interface

Use strict Pydantic v2 models (`extra="forbid"`, strict input, finite JSON numbers) for these
provider-neutral value objects:

1. `StructuredMessage`
   - `role: Literal["system", "user", "assistant"]`
   - `content: str`, non-empty after a whitespace-only check, maximum 2,000,000 characters;
     preserve accepted content verbatim rather than silently trimming the prompt.
2. `StructuredGenerationRequest`
   - `messages: list[StructuredMessage]`, non-empty, order authoritative, at least one `user`;
   - `response_schema_name: str` matching `^[A-Za-z][A-Za-z0-9_-]{0,63}$`;
   - `response_schema: dict[str, JsonValue]`; `{}` is valid and the port must not inspect or
     specialize the Schema;
   - `max_output_tokens: int >= 1`, required so every future live request has a caller-set bound.
3. `TokenUsage`
   - optional non-negative strict integers `input_tokens`, `output_tokens`, `total_tokens`;
   - do not assume `total_tokens == input_tokens + output_tokens` because providers may account for
     cached/reasoning tokens differently.
4. `StructuredGenerationResponse`
   - `content: str` containing the raw assistant content, preserved verbatim but rejected when
     empty/whitespace-only;
   - trimmed non-empty `provider: str` and `model: str`;
   - optional trimmed non-empty `finish_reason: str`;
   - `usage: TokenUsage`, defaulting to an empty usage object.

The response deliberately carries raw text rather than a parsed CCEF package. JSON syntax/schema
decoding belongs to a later decoder; empty/whitespace provider content cannot form a successful
response. Provider-private response bodies and credentials must not appear in these models.

Define:

- `ProviderErrorCode` as the literal union `authentication | rate_limited | timeout | unavailable
  | invalid_request | invalid_response | unknown`;
- `StructuredGenerationProviderError(RuntimeError)` constructed as
  `(code: ProviderErrorCode, message: str, retryable: bool)`, with those public fields and
  `str(error) == message`; `message` must be safe and non-empty and the error must not carry raw
  response bodies;
- a runtime-checkable async `StructuredGenerationProvider` Protocol with exactly
  `generate(request) -> StructuredGenerationResponse`;
- `ScriptedStructuredGenerationProvider`, initialized with an ordered finite sequence of response
  or provider-error outcomes. Each awaited call records a deep snapshot of the request, consumes
  exactly one outcome, returns a deep response copy or raises the scripted error. Expose calls as
  an immutable tuple and a non-negative `remaining` count. Exhaustion raises an `AssertionError`
  with a clear message. It performs no sleeps, I/O, parsing or schema-specific behavior.

### Preserved invariants

- The caller supplies the JSON Schema; provider code never imports or hardcodes CCEF.
- No PDF/OCR, HTTP client, endpoint, model default, API key, environment variable, retry loop,
  database, job or ConsumerAdapter behavior in this packet.
- Async cancellation is not wrapped or converted by the port/fake.
- The fake is deterministic and sequential; no concurrency guarantee is introduced.
- No new dependency and no quality-gate reduction.

### Required focused tests

Cover at least:

- valid request/message/response/usage objects and strict rejection of unknown fields, booleans as
  integers, empty text, missing user message, invalid schema name and non-finite nested Schema data;
- arbitrary non-CCEF Schema `{}` and another small unrelated Schema passing through unchanged;
- Protocol runtime conformance;
- scripted FIFO success, request snapshot isolation, response copy isolation, error then success,
  exact call/remaining accounting and deterministic exhaustion;
- provider error fields/string form and retryable/non-retryable examples;
- import purity proving the module does not import HTTP libraries, Sanic, SQLAlchemy, store,
  services, jobs or CCEF contract models.

### Acceptance commands

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_provider.py
make backend-format backend-lint backend-typecheck
git diff --check
git diff --stat
```

Do not run cumulative Stage 8 or whole-repository acceptance.

### Escalation and review

Risk tier: **medium**, because this freezes the provider adapter interface. Stop without guessing if
the exact types above cannot support the fake without a new dependency or if an interface change is
needed. At completion update HANDOFF with files, exact test count/commands, assumptions and status
`pending Codex review`. Do not proceed to the DeepSeek HTTP adapter and do not commit.

### Codex review status (2026-08-11)

**Changes requested; 8P-2 is not accepted yet.** The declared 64 focused tests and configured
static gates pass, but independent runtime counterexamples found three enforcement gaps:

- `StructuredGenerationProviderError("not_a_code", "x", "yes")` is accepted despite the public
  literal-code and strict-boolean contract;
- `ScriptedStructuredGenerationProvider([123])` is accepted and `generate()` returns that integer
  despite its declared response type;
- `provider.calls` is a tuple, but its request objects are the fake's mutable internal snapshots,
  so mutating `provider.calls[0]` changes later `provider.calls` observations.

### V4-Flash correction packet: DS-STAGE8-PROVIDER-PORT-01-R1

Keep the original objective, public names, preserved invariants and permitted edit boundary. Make
only these corrections in `provider.py` and focused tests:

1. Enforce `StructuredGenerationProviderError` constructor inputs at runtime:
   - `code` must be a string and one of the seven `ProviderErrorCode` literals;
   - `message` must be a string and non-empty after the whitespace-only check;
   - `retryable` must be an actual `bool`, not `0`, `1`, strings or other truthy values.
   Raise a clear `TypeError` or `ValueError` before constructing an invalid error. Preserve the
   exact public constructor order, fields, `str(error)` behavior and deepcopy support.
2. Validate every scripted outcome during fake construction. An outcome that is neither
   `StructuredGenerationResponse` nor `StructuredGenerationProviderError` must raise a clear
   `TypeError` identifying its index; it must never reach or be returned by `generate()`.
3. Keep internal request snapshots isolated from callers of the `calls` property. Continue to
   expose a tuple, but return deep copies (or an equivalently strong read-only representation) so
   mutating a previously returned request/message/schema cannot change subsequent observations.
   Preserve original-request isolation and exhaustion-call accounting.
4. Add regressions for invalid error code/message types and non-bool retryability, invalid scripted
   outcomes at different positions, and mutation through a returned `calls` tuple. Retain Protocol
   conformance, FIFO, response isolation, error-then-success and all original tests.

Do not change the request/response fields, add dependencies, start HTTP work or enter 8P-3. Run the
same focused acceptance commands and report `pending Codex re-review`; do not commit.

### Final Codex review status (2026-08-11)

**Accepted.** The three R1 runtime counterexamples are rejected, internal call snapshots remain
isolated, and the scripted fake preserves FIFO/error/exhaustion behavior. Codex made one final
public-contract consistency correction: `response_schema` is now required while an explicitly
provided empty Schema `{}` remains valid, matching the invariant that the caller supplies the
Schema. The focused contract/provider suite passes 70/70 and configured backend format, lint and
type gates are clean. 8P-2 is complete; 8P-3 has not started and needs its own packet.

## Completed packet: DS-STAGE8-PORTABLE-CONTRACT-01

### Final Codex review status (2026-08-11)

**Accepted.** R2 passes 43 focused tests, configured backend format/lint/type gates, independent
runtime/Schema UTC adversarial checks and canonical Schema byte comparison. 8P-1 is complete; the
active work is now `DS-STAGE8-PROVIDER-PORT-01` above.

### Codex review status (2026-08-11)

**Changes requested; 8P-1 is not accepted yet.** The declared 30 focused tests, configured Ruff
lint and repository MyPy gate pass, and the checked-in Schema has the expected dialect, ID and
closed model objects. Independent adversarial validation found four contract-boundary failures:

1. a one-node sequence whose node names itself as `parent_id` is accepted, because the current
   node ID is inserted into the seen set before the parent-before-child check;
2. `confidence` accepts JSON string `"0.5"` and JSON boolean `true`, although the generated Schema
   allows only a JSON number or null;
3. `created_at` accepts JSON number `0` and numeric string `"0"`, although the generated Schema
   declares a date-time string and the normative contract requires a timezone-aware UTC datetime;
4. `JsonValue` extensions accept nested `NaN`/positive or negative infinity, after which JSON
   serialization is lossy or non-standard.

The permissive `strict=False` applied to the bbox container also accepts a Python tuple. This does
not occur in parsed JSON, but contradicts the packet's strict-model requirement and is unnecessary:
Pydantic strict floats already accept integer JSON numbers while rejecting strings and booleans.

### V4-Flash correction packet: DS-STAGE8-PORTABLE-CONTRACT-01-R1

Keep the original objective, architecture, invariants and permitted edit boundary. Make only these
corrections:

1. Check a non-null `parent_id` against IDs of nodes that appeared **before** adding the current
   node ID. Add a minimal single-node self-parent regression test as well as retaining the existing
   dangling/forward-parent tests.
2. Remove lax conversion from bbox/confidence while continuing to accept integer-valued JSON
   numbers such as `0` and `1`. Add tests proving confidence accepts `0`, `0.5`, `1` and rejects
   `"0.5"` and `true`; bbox accepts a JSON list containing integer/float numbers and rejects a
   tuple, numeric strings and booleans.
3. Preserve the required `model_dump(mode="json")` round trip for UUID/date-time strings without
   allowing unrelated lax inputs. `package_id` may accept only a UUID instance or JSON string, not
   bytes. `created_at` may accept only a datetime instance or an actual ISO/RFC3339-style date-time
   string, not integers, booleans, date-only strings or numeric strings; it must still reject naive
   and non-UTC values.
4. Set or implement recursive finite-number validation so `NaN`, `Infinity` and `-Infinity` are
   rejected even when nested inside package, item or move-node `extensions`. Ordinary JSON scalar,
   array and object extension values must continue to work. Prefer the smallest Pydantic-native
   mechanism and do not add a dependency.
5. Regenerate the canonical JSON Schema only if the corrected model changes it. Keep the
   byte-for-byte drift test.

Add focused regressions for every value above. Do not weaken strictness, change a public field,
add chess legality, provider/HTTP/SQL code, or touch files outside the original boundary. Run the
same acceptance commands. In the completion report include the new exact test count and status
`pending Codex re-review`; do not mark 8P-1 complete and do not proceed to 8P-2.

### Codex R1 re-review status (2026-08-11)

The four R1 blockers are independently verified as fixed, and all 37 focused tests plus the
configured format/lint/type gates pass. **One public-contract consistency correction remains, so
8P-1 is not accepted yet.** The manual `created_at` parser currently:

- accepts leading/trailing whitespace even though a JSON Schema `date-time` string does not;
- accepts RFC3339 `-00:00`, whose meaning is an unknown local offset rather than known UTC;
- rejects otherwise valid lowercase RFC3339 `t`/`z` spellings;
- while the generated Schema exposes only `format: date-time`, so Schema-only consumers can accept
  non-UTC offsets that the normative contract and Python model reject.

### V4-Flash correction packet: DS-STAGE8-PORTABLE-CONTRACT-01-R2

Keep every original/R1 invariant and the same permitted edit boundary. Correct only the
`Provenance.created_at` JSON representation and its focused tests/schema artifact:

1. Accept a datetime instance whose offset is zero, or an RFC3339 string with no surrounding
   whitespace and an explicit UTC designator: `Z`, `z` or `+00:00`. Accept both `T` and `t` as the
   date/time separator and preserve optional fractional seconds.
2. Reject surrounding whitespace, missing timezone, date-only/numeric strings, `-00:00`, and every
   non-zero positive or negative offset.
3. Use one maintained regex/pattern source (or an equivalently drift-proof design) for runtime
   validation and add that UTC restriction to the generated `created_at` JSON Schema property;
   keep `format: date-time`. Regenerate the checked-in canonical Schema artifact.
4. Add regressions for uppercase/lowercase UTC spellings, surrounding whitespace, `-00:00` and a
   non-zero offset. Assert the generated Schema carries the UTC pattern as well as `format`.

Do not change other fields or validators, add dependencies, or enter 8P-2. Run the original focused
acceptance commands and report `pending Codex final re-review`; do not commit.

### Objective

Implement only the provider- and consumer-neutral CCEF v1 data contract described by ADR 0010 and
the normative field specification `docs/architecture/ccef-v1.md`.
This packet freezes the portable output shape before any database, HTTP route, PDF or model work.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/__init__.py` (new)
- `backend/src/chess_workbench/extraction/contracts.py` (new)
- `backend/tests/test_extraction_contract.py` (new)
- `contracts/chess-content-extraction-v1.schema.json` (new generated artifact)
- `docs/agent/HANDOFF.md` (completion evidence only)

No other file may be changed. In particular, do not edit dependencies, configuration, Makefile,
OpenAPI, SQLAlchemy models, migrations, services, routes, existing domain schemas or existing tests.

### Required behavior

1. Use Pydantic v2 strict models with `extra="forbid"` at every object boundary.
2. Implement `ExtractionPackage` with the exact ADR 0010 version literal, UUID package ID, opaque
   source reference, ordered item discriminated union, diagnostics, provenance and explicit
   namespaced extensions.
3. Implement strict `EvidenceRef`: one-based page, normalized positive-area bbox, optional valid
   half-open text offsets and optional lowercase SHA-256.
4. Implement `heading`, `prose`, `move_sequence`, `figure` and `unresolved` items. Every item has a
   package-local unique ID and non-empty evidence. `prose` supports no anchor, a move-node anchor,
   or a full-FEN position anchor.
5. Implement flat move nodes with unique local IDs, parent-before-child topology and contiguous,
   unique zero-based `sibling_order` per parent. Root siblings use the same rule. Do not validate
   chess legality in this packet.
6. Reject duplicate item/node IDs, dangling prose anchors, dangling node parents, forward parents,
   duplicate/non-contiguous sibling orders, evidence outside the declared page range, unsupported
   schema versions and all unknown fields.
7. Use `pydantic.JsonValue` for extension values. Extension keys must be reverse-domain namespaced;
   core behavior must not depend on extensions.
8. Generate a deterministic Draft 2020-12 JSON Schema artifact. A test must compare the generated
   schema with the checked-in artifact byte-for-byte after canonical JSON formatting.
9. The package must not import or mention Course, Module, Occurrence, KnowledgeNote, SQLAlchemy,
   Sanic, store IDs or any provider request/response class.

### Preserved invariants

- CCEF is a candidate/evidence format; it has no approval or formal-publish state.
- Model confidence never establishes chess legality.
- List order is authoritative content order; do not add a second conflicting item-order field.
- CCEF stores portable evidence coordinates and text, not internal SourceSpan UUIDs.
- No network calls, API keys, real model calls, filesystem source ingestion or database writes.
- No new dependency and no quality-gate reduction.

### Required focused tests

The test module must cover at least:

- one full valid package containing all five item kinds and both anchor kinds;
- JSON round-trip equality and deterministic JSON Schema drift;
- every rejection named in Required behavior item 6;
- invalid bbox, page zero, reversed/equal offsets, malformed hash and invalid extension key;
- proof that the extraction package can be imported without importing
  `chess_workbench.store`, `sqlalchemy` or `sanic`.

### Acceptance commands

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py
make backend-format backend-lint backend-typecheck
git diff --check
git diff --stat
```

Do not run cumulative Stage 8/whole-repository acceptance for this first iterative packet.

### Escalation and review

Risk tier: **medium**, because this freezes a new public interchange contract. Codex final review is
mandatory before 8P-2. V4-Flash must stop without guessing if ADR 0010 cannot be represented by the
named files, if Pydantic JSON Schema output is nondeterministic, or if any requirement would need a
dependency/API/database/schema change outside this contract module.

At completion update `docs/agent/HANDOFF.md` with exact files, test counts, commands, assumptions and
remaining risks. Do not commit.

## Deferred gates

- No real DeepSeek call until the mock/recorded adapter and per-job cost limit exist.
- No AI/OCR candidate can write official Knowledge without Stage 8D human approval.
- Database migrations, public HTTP APIs, authentication/security and job state-machine changes are
  not V4-Flash tasks under current `AGENTS.md`; Codex must own them or the user must explicitly
  change the collaboration rules before those Stage 8 units begin.
