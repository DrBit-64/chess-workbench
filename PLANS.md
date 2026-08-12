# Current plan

## Goal

Implement Stage **8C** on top of accepted Stage 8B: deterministic whole-range prompt input,
provider execution, strict/trusted CCEF candidate normalization and immutable candidate artifacts.
ADR 0014 is authoritative. Stage 5/6E and Stage 7 remain deferred.

## Delivery order

1. [x] **8P + 8A accepted:** portable CCEF boundary, immutable PDF/CAS ownership, page-range jobs,
   HTTP/Sources workflow and cumulative `acceptance-stage-8a` evidence are green.
2. [x] **8B architecture:** ADR 0013 freezes rendering/OCR ports, normalized evidence, resource
   limits, artifact/transaction ownership and tool licensing.
3. [x] **8B-1 evidence ports:** strict evidence values, renderer/OCR request/result ports, stable
   errors and scripted OCR fake.
4. [x] **8B-2 PDFium renderer:** deterministic PNG, embedded text, limits and synthetic fixtures.
5. [x] **8B-3 Paddle adapter:** recorded PaddleOCR JSON normalization and controlled local runner.
6. [x] **8B-4 handler/artifacts:** CAS registration, idempotent handler, retry/cancel/conflict tests.
7. [x] **8B-5 API/UI/acceptance:** verified committed-evidence summary, Sources display and a
   deliberately focused Stage 8B gate.

Only independently verifiable V4-Flash packets may be active. Do not combine the steps above into
one cross-module implementation.

## Stage 8C delivery order

1. [x] **8C architecture:** ADR 0014 freezes pipeline v2, whole-range text input, trusted metadata,
   artifact/transaction ownership, retry policy and the text-only DeepSeek boundary.
2. [x] **8C-1 prompt input:** strict evidence pages and deterministic CCEF request builder.
3. [ ] **8C-2 trusted candidates:** binder, canonical raw/normalized codec and conflict summary.
4. [ ] **8C-3 execution:** v2 handler, configuration, retry policy and atomic candidate artifacts.
5. [ ] **8C-4 API/UI/acceptance:** typed summary, Sources display and focused gate.

Do not start 8D review/publishing or run the repository-wide cumulative gate during 8C.

## Accepted packet: DS-STAGE8C-PROMPT-BUILDER-01 (Codex completion)

The V4-Flash worker was stopped after about two minutes because it remained on one repeated
reading/reasoning cycle at roughly 126,000 tokens and had created no implementation file. It did
not report balance, credit or quota exhaustion, so the user's quota-stop condition did not fire.
Codex implemented the already-frozen pure module and independently verified it. Do not start 8C-2
until the next user continuation.

### Goal

Add the pure, provider-neutral Stage 8C request builder described by ADR 0014. It accepts a complete
ordered evidence page range and caller-owned trusted metadata, then produces exactly one
deterministic `StructuredGenerationRequest`. It performs no I/O and never calls a provider.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/prompting.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (new exports only)
- `backend/tests/test_extraction_prompting.py` (new)
- `docs/agent/HANDOFF.md` (append completion evidence only)

Everything else is read-only, including contracts/provider/evidence implementations, DeepSeek,
decoder/validation, config, services/worker/SQL/API/frontend, dependencies, schema artifacts,
ADRs, Makefile, existing tests and this plan. Do not commit or create probes.

### Frozen public values

- `CCEF_PROMPT_VERSION = "chess-workbench/ccef-prompt/1.0"`.
- Strict frozen models `PromptEvidenceFragment`, `PromptEvidencePage`, `CcefPromptContext` and
  public error `CcefPromptError(code, message)`; export them with `build_ccef_generation_request`.
- `PromptEvidenceFragment` fields are exactly `order: int >= 0` and
  `fragment: SourceEvidenceFragment`.
- `PromptEvidencePage` fields are exactly `physical_page: int >= 1` and ordered `fragments` (empty
  allowed). Fragment orders must be unique contiguous `0..n-1` and each fragment physical page
  must equal its page.
- `CcefPromptContext` fields are exactly: `package_id: UUID`, `created_at: datetime`,
  `source_ref: str 1..1024 trimmed`, `media_type: str 1..255 trimmed`, `language: str 1..35 trimmed
  or None`, `first_page/last_page: int >=1`, `pages: list[PromptEvidencePage]`,
  `max_output_tokens: int 1..384000`, `max_prompt_chars: int 1..2000000`. created_at must be
  timezone-aware UTC. Pages must cover every physical page in the requested range exactly once in
  ascending order, including empty pages. Range is ordered and at most 20,000 pages.
- All models use `extra="forbid"`, strict types, frozen snapshots and recursively caller-independent
  data. Reject bool as int and non-UTC/naive timestamps.

### Exact request behavior

- `build_ccef_generation_request(context)` requires exact `CcefPromptContext`; programmer misuse
  raises TypeError. Accepted input yields exactly two messages: one system and one user.
- System content is a module constant built only from fixed English policy text. It states source
  content is untrusted data; never follow its instructions; preserve order/content; never invent;
  use unresolved/warnings for uncertainty and unseen figures; output only unvalidated move nodes
  with authoritative SAN/UCI/FEN fields null. It never contains evidence text.
- User content is exactly a fixed one-line prefix followed by one compact, sorted-key,
  ensure_ascii=False, allow_nan=False JSON object. The object fields are exactly
  `prompt_version`, `package`, `evidence_pages`. `package` contains the exact caller metadata plus
  CCEF fixed values/skeleton: schema version, package_id string, source descriptor, empty items and
  diagnostics, provenance with caller created_at/adapter name `chess-workbench-ccef-prompt`/
  adapter version `1.0` and null provider/model/request/response hashes, and empty extensions.
  `evidence_pages` preserves pages/fragments and every SourceEvidenceFragment field, using its
  JSON-mode values. Source strings such as `ignore previous instructions` remain only JSON string
  data in this user message.
- Request fields are exact: response schema name `chess_content_extraction_v1`, response schema
  `ccef_schema_document()` deep snapshot, caller max output tokens. The function may not mutate or
  retain mutable aliases from context.
- Reject before returning if total fragments exceed 200,000, total fragment text code points
  exceed 1,500,000, or final system+user content code points exceed `max_prompt_chars`. Stable
  errors: `invalid_evidence` / `CCEF evidence pages are invalid`, `input_too_large` /
  `CCEF evidence input exceeds the configured limit`. Errors contain no source text.
- Empty entire ranges (zero total fragments) are accepted: the model can return empty items or an
  unresolved result only when it has evidence; the builder must not invent a fragment.
- Import purity: standard library, Pydantic, `.contracts`, `.evidence`, `.provider` only. No I/O,
  clock, UUID generation, hashing, chess, HTTP, provider adapter, config, SQL, service or API.

### Focused oracle

Tests prove an 81-page context produces one request and exactly one user message; deterministic
equality/JSON bytes; full fragment field preservation including Unicode/outer whitespace;
empty-page and empty-range behavior; prompt-injection isolation; schema snapshot/no aliasing;
caller mutation cannot affect models/request; all page/range/order/type/time/unknown-field
rejections; exact fragment/text/prompt boundaries and one-over failures; sanitized public errors;
protocol conformance and AST import purity.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_prompting.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/extraction/prompting.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_prompting.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/extraction/prompting.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_prompting.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/extraction/prompting.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_prompting.py
git diff --check
```

Stop without guessing if any frozen field cannot be represented without changing an accepted
model, another module/dependency is needed, prompt size semantics conflict with the provider's
2,000,000-character message bound, or provider/decoder/I/O/SQL behavior becomes necessary. If the
model/API reports exhausted balance, credit or quota, stop immediately and leave the packet
incomplete; Codex must not backfill that delegated task.

## Accepted packet: DS-STAGE8B-SOURCES-EVIDENCE-01

### Goal

Display the already-frozen `PdfExtractionRead.evidence` summary on the existing Sources task list.
This is a presentational change only: the backend contract, artifact rules and lifecycle are
read-only. One completed run must show real page/fragment/warning totals and committed manifest
hashes; no client-side progress or count may be inferred.

### Permitted edit boundary

- `frontend/src/app/SourcesPage.tsx`
- `frontend/src/app/WorkbenchPages.test.tsx`
- `docs/agent/HANDOFF.md` (append completion evidence only)

Everything else is read-only, including generated API types, backend/OpenAPI, `PLANS.md`, Makefile,
dependencies, other frontend components/tests and all Stage 8C code. Do not commit or create probe
files.

### Exact behavior and preserved invariants

- Preserve upload, extraction creation, filters, SWR polling, source cards, status/error/conflict
  display and every existing Chinese label unless this packet explicitly adds text.
- When `run.evidence` is non-null, render one readable summary under that run with exact visible
  text for `已提交证据：{page_count} 页 · {fragment_count} 个文本片段 · {warning_count} 个警告`.
- On the next line render `Manifest 已提交` and both safely shortened identifiers:
  `渲染 {first 12 chars}…` and `OCR {first 12 chars}…`. Never show a path, full opaque payload,
  raw Job result or derive values from the requested page range.
- When Job status is `succeeded` but `evidence` is null, render warning text
  `证据索引尚未完整提交`; do not claim evidence or manifest completion.
- For queued/running/failed/cancelled jobs with null evidence, add no evidence-completion text.
- Add focused tests proving the committed summary and shortened hashes, the incomplete-success
  warning, absence of a false completion claim on queued/failed rows, and preservation of existing
  status/filter/error behavior. Use API-shaped fixtures; do not mock console or timers.

### Exact acceptance commands

```bash
pnpm --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx --coverage=false
pnpm --dir frontend exec prettier --check src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
pnpm --dir frontend exec eslint src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
pnpm --dir frontend exec tsc --noEmit
git diff --check
```

Stop and report without guessing if the generated `PdfExtraction` type does not expose the frozen
evidence fields, another production component must change, existing tests contradict the labels,
or any API/lifecycle/backend/Stage 8C change appears necessary. If the model/API reports exhausted
balance, credit or quota, stop immediately and leave this packet incomplete for Codex to report;
Codex must not backfill that delegated task.

## Completed packet: DS-STAGE8B-VERIFIED-CAS-READ-01 plus Codex 8B-4B handler

8B-4 was split into verified source reading, deterministic artifact codec/registration and the Job
handler. DeepCode did not report quota/credit/balance exhaustion; it was stopped after roughly one
minute because it had consumed nearly 100,000 tokens while repeatedly reading context and had made
no implementation edit. The user-requested balance-stop condition therefore did not trigger.
Codex completed the architecture-sensitive CAS/transaction/worker work and independently reviewed
the focused result.

Accepted behavior: bounded source CAS reread; deterministic page evidence/render/OCR manifests;
embedded-text-first and one OCR call per fallback page; 200,000-fragment run cap; all blobs before
one run-row-locked registration transaction; exact replay and immutable conflict; retry and cancel
with zero partial artifact rows; compact committed Job result; API worker registration; optional
server-owned Paddle runner path. Migration 0011 permits legitimate CAS reuse by removing the two
artifact uniqueness constraints that incorrectly rejected identical page bytes.

### Goal and permitted boundary

Add one reusable, bounded, sanitized reader for a server-owned CAS blob. Edit only:

- `backend/src/chess_workbench/services/source_storage.py`
- `backend/tests/test_source_storage.py`
- `docs/agent/HANDOFF.md` (append evidence only)

Everything else, including this plan, artifact models, extraction modules, SQL, worker/config/API,
dependencies, Makefile and existing tests, is read-only. Do not create temporary probe files and
do not commit.

### Exact behavior

- Export sync function
  `read_verified_content_addressed_bytes(storage_root: Path, *, relative_path: str,
  expected_sha256: str, expected_size: int, max_bytes: int) -> bytes` from this module only.
- Programmer misuse is rejected before filesystem access: exact `Path` storage root; exact string
  relative path; lowercase 64-hex digest; exact positive integer expected size/max bytes (bools
  invalid); expected size may not exceed max bytes. Raise TypeError/ValueError.
- Accept only a nonempty canonical POSIX relative path: no leading slash, empty/dot/dot-dot
  segment, backslash, NUL/control character or trailing slash. Resolve the configured root and
  candidate strictly; the resolved regular file must remain under the resolved root. Reject a
  symlink at the final path. Never follow an escape outside the root.
- Before reading, require stat size to equal `expected_size` and be at most `max_bytes`. Read in
  bounded chunks while hashing, never retain more than `max_bytes`, detect concurrent size change,
  EOF mismatch or extra bytes, and require exact lowercase SHA-256 equality. Return exact bytes.
- Any path escape, missing/nonregular/symlink file, permission/I/O error, size/hash mismatch or
  concurrent mutation maps to exactly
  `ServiceError("source_storage_unavailable", 503, "source storage is unavailable")`, created
  outside its exception handler with no cause/context, path, digest or OS text.
- Preserve `store_content_addressed_bytes` behavior byte-for-byte. Imports remain standard library
  plus existing `ServiceError`; no SQL/HTTP/PDF/render/OCR/worker imports.

### Focused oracle

Tests prove exact round trip from the existing writer; nested valid path; every lexical escape;
absolute/backslash/control input; missing/directory/final-symlink/outside-symlink; corrupt size,
hash and over-limit; injected stat/open/read failures; bounded read (no unrestricted
`Path.read_bytes`); sanitized error context and no secret/path leakage; programmer type/range
errors occur before filesystem access; existing writer tests remain green.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_source_storage.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/services/source_storage.py backend/tests/test_source_storage.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/services/source_storage.py backend/tests/test_source_storage.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/services/source_storage.py backend/tests/test_source_storage.py
git diff --check
```

Stop and report evidence without guessing if canonical relative-path rules conflict with existing
stored paths, another module/dependency is needed, or any artifact/handler behavior becomes
necessary. Do not start 8B-4B.

## Accepted 8B-4B implementation boundary

- `services/pdf_extraction.py` owns payload/source validation, page selection, evidence
  normalization, canonical JSON/CAS writes, atomic registration and the handler result.
- `source_storage.py` owns bounded contained reads and exact size/SHA-256 verification.
- `ExtractionArtifact` indexes may share CAS paths/hashes; registration serializes logical slots
  under an `ExtractionRun` row lock. Migration `20260811_0011` upgrades existing databases.
- `api/app.py` registers the PDF handler whenever the existing worker switch is enabled; a
  server-owned optional `paddle_ocr_runner_path` configures scanned-page OCR.
- Focused tests cover deterministic replay, same-PNG CAS reuse, embedded/OCR/empty pages, source
  corruption, artifact conflict, retry-to-success, running cancellation, model/migration drift and
  existing Job/lifecycle behavior. No book PDF, network, Paddle model or full-stage gate is used.

## Completed packet: DS-STAGE8B-PADDLE-NORMALIZER-01 (8B-3A/8B-3B)

Stage 8B-3 is split at the security boundary. V4-Flash may implement only the pure recorded-JSON
normalizer below. Codex owns the controlled subprocess runner, cancellation/resource handling,
public error mapping, final diff review and focused acceptance. Do not combine this packet with
8B-4 or infer any SQL/worker/API behavior.

The V4-Flash worker was stopped after roughly one minute because it had consumed about 110,000
tokens while repeatedly reading existing tests and had not created an implementation file. Codex
then implemented and reviewed both halves directly. The accepted result passes 39/39 adapter tests
and 100/100 adapter+evidence tests, with focused Ruff and MyPy clean.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/paddleocr.py` (new; pure normalizer only)
- `backend/src/chess_workbench/extraction/__init__.py` (exports named below only)
- `backend/tests/test_paddleocr_adapter.py` (new; normalizer tests only)
- `docs/agent/HANDOFF.md` (append evidence only)

Everything else is read-only, including `evidence.py`, ADRs, dependencies/lock, config,
services/worker/SQL/API/frontend, Makefile, existing tests and this plan. Do not commit and do not
create probes or temporary files.

### Frozen runner/result protocol

- Export constant `PADDLE_OCR_RUNNER_PROTOCOL = "chess-workbench/paddleocr-runner/1"`.
- Export pure function
  `normalize_paddle_ocr_response(payload: bytes, request: OcrRequest) -> OcrPageResult`.
- Programmer misuse is rejected before parsing: `payload` must be nonempty exact `bytes` and
  `request` exact `OcrRequest`; raise `TypeError`/`ValueError`, not `PdfEvidenceError`.
- The UTF-8 JSON root is exactly this object, with unknown fields rejected:
  `protocol`, `physical_page`, `width`, `height`, `engine_version`, `rec_texts`, `rec_scores`,
  `rec_polys`. The protocol is the constant above; page and dimensions must exactly equal the
  request; `engine_version` is a trimmed nonempty string of at most 100 code points.
- The three recorded arrays have equal length from 0 through 20,000. Text is an exact JSON string
  of at most 100,000 code points: preserve it verbatim and reject empty/whitespace-only values.
  Confidence is a finite JSON number in 0..1; reject bools, strings, NaN and Infinity.
- Each `rec_polys` item is exactly four `[x,y]` points. Coordinates are exact JSON integers (bools
  and floats invalid), `0 <= x <= request.width`, `0 <= y <= request.height`. Normalize a polygon
  to its axis-aligned `PixelBox(min x, min y, max x, max y)` and reject zero-area polygons.
- Return contiguous `TextFragment.order` values in recorded-array order with confidence present,
  exact engine name `paddleocr`, the response engine version and request page/dimensions.
- Any decode/UTF-8/JSON/schema/protocol/mismatch/content failure is sanitized to the same
  non-retryable `PdfEvidenceError("ocr_invalid_output", "OCR runner returned invalid output",
  False)`, raised without cause/context and without including payload/text/parser details.
- Module imports are standard library + Pydantic + `.evidence` only. It performs no I/O and does
  not import PaddlePaddle, subprocess, HTTP, SQL, filesystem, config, provider or consumer code.

### Focused normalizer oracle

Use in-memory recorded JSON only. Prove valid empty and multi-fragment outputs; ordering; polygon
to bbox normalization; text preservation including Unicode/outer whitespace; integer confidence;
all mismatch/unknown-field/length/type/finite/range/area/count/text limits; sanitized identical
errors with no exception context; programmer misuse; Protocol constant/export identity and AST
import purity. Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_paddleocr_adapter.py -k normalizer
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/extraction/paddleocr.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_paddleocr_adapter.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/extraction/paddleocr.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_paddleocr_adapter.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/extraction/paddleocr.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_paddleocr_adapter.py
git diff --check
```

Stop if another module/dependency is needed, the frozen JSON subset is insufficient, or any
subprocess/runner behavior would need implementation. Report pending Codex review and do not start
8B-3B/8B-4.

## Accepted Codex-owned completion: Stage 8B-3B controlled local runner

Codex added `PaddleOcrJsonAdapter` to the same module. The constructor
snapshots a nonempty bounded argv and finite positive timeout/output limits; `recognize()` encodes
one versioned request containing base64 PNG, page/dimensions/language/profile, starts argv only via
`asyncio.create_subprocess_exec` with no shell, bounds stdout/stderr while streaming, enforces the
whole-operation timeout, kills/reaps on timeout/cancellation/overflow and re-raises cancellation.
Stable public errors are `ocr_unavailable` (spawn failure, retryable), `ocr_timeout` (retryable),
`ocr_runner_failed` (nonzero exit, retryable), `ocr_output_too_large` (non-retryable) and the
normalizer's `ocr_invalid_output` (non-retryable). No stderr, path, bytes or parser text reaches a
public error. Focused tests use deterministic local subprocess helpers only; no network,
PaddlePaddle, model download, disk fixture, SQL, worker, API or 8B-4 behavior.

## Completed packet: DS-STAGE8B-PDFIUM-RENDERER-01 (8B-2A)

The delegated worker was terminated after creating an out-of-bound root probe file. Codex took
over and implemented the renderer directly. The accepted result uses locked pypdfium2 5.12.1 and
Pillow 12.3.0, closes every PDFium resource explicitly, and passes 77/77 renderer+evidence tests
plus focused Ruff/MyPy and lock consistency. The worker-created `.tmp_pdfium_probe.py` remains
untracked pending explicit deletion permission; it is not imported or used by the product/tests.

### Goal

Implement the ADR 0013 in-memory PDFium renderer behind the accepted `PdfPageRenderer` port,
including deterministic PNG output, bounded page dimensions and embedded-text rectangles. The
dependency versions are already Codex-owned and locked (`pypdfium2==5.12.1`, Pillow 12.3.x).

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/pdfium.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (exports from the new module only)
- `backend/tests/test_pdfium_renderer.py` (new)
- `docs/agent/HANDOFF.md` (append evidence only)

`extraction/evidence.py`, pyproject/lock, every existing test, SQL/services/worker/config, API,
frontend, ADRs, Makefile and this plan are read-only. Do not commit.

### Exact renderer behavior

- Export final class `PdfiumPageRenderer` with no constructor arguments and exact sync method
  `render_page(pdf_bytes: bytes, physical_page: int, profile: RenderProfile) -> RenderedPage`.
  It must satisfy `isinstance(renderer, PdfPageRenderer)`.
- Reject programmer misuse before opening PDF: `pdf_bytes` must be nonempty exact `bytes`,
  `physical_page` exact int >=1 (bool invalid), `profile` exact `RenderProfile`; raise TypeError or
  ValueError, not `PdfEvidenceError`.
- Open only in-memory bytes with `pypdfium2.PdfDocument`; convert 1-based physical page to one
  zero-based index. Out of range raises non-retryable `PdfEvidenceError("page_out_of_range",
  "PDF physical page is outside the selected document", False)`. Invalid/unopenable bytes raise
  `("invalid_pdf", "PDF document could not be opened for rendering", False)`.
- Compute exact rendered width/height with `ceil(page.get_width()*dpi/72)` and height likewise
  before bitmap allocation. Enforce both `profile.max_side_px` and `profile.max_pixels`; failure is
  non-retryable code `render_limit_exceeded`, message `PDF page exceeds the rendering limits`.
- Render rotation 0, no forms/annotations, opaque white background, forced BGR bitmap with reverse
  byte order so Pillow sees RGB. Convert/copy to RGB and encode one PNG into `BytesIO` using
  `format="PNG"`, `compress_level=9`, `optimize=False`, with no caller/file metadata. Reject output
  over `profile.max_png_bytes` with the same render-limit error. Return exact renderer name
  `pdfium` and version `str(pypdfium2.version.PDFIUM_INFO)`.
- Embedded text: obtain one PDFium text page and call `count_rects()` once. For each rect in PDFium
  order, get `(left,bottom,right,top)`, extract `get_text_bounded` for that rect, skip empty or
  whitespace-only text, convert the PDF bottom-left box to top-left pixel coordinates using the
  same scale, floor left/top and ceil right/bottom, clamp to page bounds, skip degenerate boxes,
  and append contiguous `TextFragment(order=0.., confidence=None)` preserving returned text
  exactly. Stop with `render_limit_exceeded` before exceeding 20,000 accepted fragments or 100,000
  code points in one fragment. Do not concatenate, trim or invent confidence.
- Close document/page/textpage/bitmap objects on success and all ordinary failures. Do not catch
  `KeyboardInterrupt`, `SystemExit` or `GeneratorExit`; explicitly let `MemoryError` propagate.
  Map ordinary PDFium/Pillow extraction/render failures after open to non-retryable
  `PdfEvidenceError("render_failed", "PDF page could not be rendered", False)` without cause,
  context, bytes, absolute path or underlying exception text.
- The module imports stdlib, Pillow, pypdfium2 and `.evidence` only. No filesystem path, SQL,
  HTTP, subprocess, environment, clock, randomness, OCR/provider or consumer imports.

### Focused tests

Build deterministic PDFs only in memory with installed `pypdf`: blank one/three-page PDFs and a
small Type1 Helvetica content stream for embedded text. Prove exact dimensions at 72/150 DPI,
physical page selection, PNG signature/RGB/white blank pixel, byte-for-byte repeat rendering,
version/name, text preservation/order/bounds/null confidence, selected-page-only access, custom
side/pixel/PNG limits, invalid/empty/type/range input, sanitized failure mapping, unknown profile
rejection inherited from evidence, cleanup on injected ordinary errors, MemoryError and
KeyboardInterrupt propagation, Protocol conformance and AST import purity. Never read
`data/books`, disk fixtures or network; never call OCR.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdfium_renderer.py backend/tests/test_extraction_evidence.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/extraction/pdfium.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_pdfium_renderer.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/extraction/pdfium.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_pdfium_renderer.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/extraction/pdfium.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_pdfium_renderer.py
git diff --check
```

Stop if pypdfium2 5.12.1 behavior contradicts these exact rules or another dependency/module is
needed. If green, append evidence to HANDOFF, report pending Codex review, do not start OCR/8B-3
and do not commit.

## Completed packet: DS-STAGE8B-EVIDENCE-PORTS-01 (8B-1)

Codex accepted the delegated evidence module after full review and added a missing shared
40,000,000-pixel guard to both OCR request and result. The final focused gate is 61/61 with Ruff,
MyPy and diff clean.

### Goal

Implement the strict, side-effect-free evidence values and renderer/OCR ports already frozen by
ADR 0013, including a deterministic scripted OCR fake. This packet does not render a PDF, invoke
PaddleOCR, read files, write artifacts or register a Job handler.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/evidence.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (exports from the new module only)
- `backend/tests/test_extraction_evidence.py` (new)
- `docs/agent/HANDOFF.md` (append evidence only)

Do not touch contracts/decoder/provider/validation, SQL/models/migrations, services/worker/config,
dependencies/lock, routes/OpenAPI, frontend, ADRs, Makefile, existing tests or this plan. Do not
commit.

### Exact values and ports

Use the module's own frozen strict Pydantic base (`extra="forbid"`, strict, frozen) without
importing CCEF contracts.

- `EvidenceOrigin = Literal["embedded_text", "ocr"]`.
- `NormalizedBox`: object fields finite strict floats `x0,y0,x1,y1` in `0..1`; require
  `x0 < x1` and `y0 < y1`.
- `PixelBox`: object fields strict nonnegative ints `x0,y0,x1,y1`; bool is invalid; require
  `x0 < x1` and `y0 < y1`. Bounds against page dimensions belong to the containing result.
- `TextFragment`: `order` strict int `0..19999`, `text` nonempty/whitespace-preserving string of at
  most 100,000 code points (whitespace-only invalid), `box: PixelBox`, `confidence` optional finite
  strict float `0..1`. OCR fragments require confidence; embedded fragments require null.
- `RenderProfile`: defaults `dpi=150`, `max_side_px=10000`, `max_pixels=40000000`,
  `max_png_bytes=67108864`, `embedded_text_min_chars=32`; strict bounded positive ints, dpi
  `72..600`, and reject bool.
- `RenderedPage`: physical page >=1, positive width/height, dpi 72..600, nonempty immutable
  `png_bytes` up to 64 MiB, ordered `embedded_fragments`, `renderer_name`/`renderer_version`
  trimmed nonempty max 100. Enforce contiguous unique fragment orders from zero, each pixel box
  inside width/height, total fragments <=20,000 and `width*height <= 40,000,000`. Preserve bytes
  and text exactly.
- `OcrRequest`: the same physical page/width/height/png constraints plus trimmed language max 64
  and frozen `profile: dict[str, JsonValue]` default empty. Recursively reject non-finite values
  and deep-copy the caller's profile.
- `OcrPageResult`: matching physical page and positive dimensions, ordered OCR-only fragments,
  engine name/version limits, the same order/count/box bounds, and no I/O behavior.
- `SourceEvidenceFragment`: physical page, normalized box, preserved text, origin, confidence rule,
  engine name/version and lowercase 64-hex `fragment_sha256`. A model-level validator recomputes
  SHA-256 from compact sorted-key UTF-8 JSON array
  `[physical_page,[x0,y0,x1,y1],text,origin,engine_name,engine_version]` using the model's JSON
  numeric values and rejects a mismatch. Export a pure `source_fragment_sha256(...)` helper using
  the same canonicalization.
- Runtime-checkable sync `PdfPageRenderer` Protocol with exactly `render_page(pdf_bytes: bytes,
  physical_page: int, profile: RenderProfile) -> RenderedPage` and runtime-checkable async
  `OcrAdapter` Protocol with exactly `recognize(request: OcrRequest) -> OcrPageResult`.
- `PdfEvidenceError(RuntimeError)`: public `code`, `message`, `retryable`; `str(error)==message`;
  deep-copy safe; no raw content/path/provider body field.
- `ScriptedOcrAdapter`: accepts a nonempty finite iterable of `OcrPageResult | PdfEvidenceError`,
  consumes FIFO, deep-snapshots every request, returns/raises deep copies, exposes immutable tuple
  `calls` and nonnegative `remaining`, and raises AssertionError when exhausted. No sleep/I/O.

Reject unknown fields and Python coercions at every boundary. JSON arrays/objects may round-trip
normally. Keep imports pure: stdlib + Pydantic only; no chess, HTTP, SQL, Sanic, filesystem,
subprocess, provider/consumer or other extraction-module import.

### Focused oracle

Tests prove all positive/negative constraints, nested unknown-field rejection, strict bool/string
rejection, NaN/Infinity recursion, order/bounds/count limits, exact text/bytes preservation,
hash stability/mismatch, deep immutability/copy isolation, Protocol runtime checks, FIFO success/
error/exhaustion and import purity. Do not use snapshots, filesystem, network, clock or randomness.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_evidence.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/extraction/evidence.py \
  backend/src/chess_workbench/extraction/__init__.py \
  backend/tests/test_extraction_evidence.py
git diff --check
```

Stop if the exact contract needs another module/dependency or conflicts with Pydantic JSON
round-trip behavior. If green, append evidence to HANDOFF, report pending Codex review, do not
start 8B-2 and do not commit.

## Completed packet: DS-STAGE8A-ACCEPTANCE-WIRING-01 (8A-4B)

Codex accepted the delegated Make/test wiring (13/13 focused tests) and then ran the cumulative
closeout. After deterministic import/type cleanup, Stage 8P passed 294/294, Stage 8A backend
passed 232/232, real MySQL and migration round trips passed, generated contracts were current,
and frontend format/lint/typecheck plus WorkbenchPages 12/12 passed. The stable repository CI
entry remains `acceptance-stage-6`.

### Goal

Add the already-designed cumulative Make acceptance entry points for the accepted portable 8P
boundary and the completed 8A PDF/Sources slice. This is mechanical verification wiring only: it
must not change production behavior, advance the stable CI entry point or weaken any older gate.

### Permitted edit boundary

- `Makefile`
- `backend/tests/test_acceptance_wiring.py`
- `docs/agent/HANDOFF.md` (append evidence only)

Do not edit production code, dependencies/locks, generated contracts, migrations, frontend,
other tests, ADRs or this plan. Do not commit.

### Exact target design

- Add both names to `.PHONY`.
- `acceptance-stage-8p` has exactly `acceptance-stage-6a` as prerequisite. Its recipe runs one
  no-coverage pytest invocation over exactly these accepted portable-boundary suites, in this
  order: `test_extraction_contract.py`, `test_extraction_provider.py`,
  `test_extraction_deepseek.py`, `test_extraction_decoder.py`,
  `test_extraction_validation.py`, `test_ccef_consumer_proof.py`. It also asserts non-empty ADR
  0010, the CCEF architecture document and the checked-in v1 JSON Schema.
- `acceptance-stage-8a` has exactly `acceptance-stage-8p bootstrap-frontend` as prerequisites. Its
  recipe calls `$(MAKE) backend-static`, then one no-coverage pytest invocation over exactly these
  8A suites, in this order: `test_source_storage.py`, `test_pdf_prepare.py`,
  `test_pdf_inspection.py`, `test_stage8_models.py`, `test_pdf_persistence.py`,
  `test_pdf_schemas.py`, `test_pdf_api.py`, `test_stage6_jobs.py`. It then calls
  `$(MAKE) backend-migration-check`, asserts non-empty ADR 0012, calls
  `$(MAKE) check-contracts`, calls `$(MAKE) frontend-format frontend-lint frontend-typecheck`,
  and runs only `src/app/WorkbenchPages.test.tsx` with Vitest and `--coverage=false`.
- Keep `acceptance: acceptance-stage-6` unchanged. Stage 8A is an AI-import milestone, not yet the
  repository-wide stable CI stage.

### Wiring tests

Extend `test_acceptance_wiring.py` with deterministic text-level assertions proving exact
prerequisites, every required suite/command/document above, absence of portable tests from the 8A
recipe (they are inherited), and the unchanged stable `acceptance-stage-6` entry. Do not execute
Make recursively from pytest and do not loosen existing assertions.

### Focused oracle

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_acceptance_wiring.py
uv run --project backend --locked ruff format --check backend/tests/test_acceptance_wiring.py
uv run --project backend --locked ruff check backend/tests/test_acceptance_wiring.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_acceptance_wiring.py
git diff --check
```

Stop if existing Make structure contradicts the exact target design or any edit outside the
boundary is needed. If green, append evidence to HANDOFF, report pending Codex review and do not
start 8B or commit.

## Completed packet: DS-STAGE8A-SOURCES-PDF-UI-01 (8A-4A)

The delegated worker was stopped after repeated research loops. Codex completed and reviewed the
bounded implementation directly. The Sources page preserves manual sources and adds real PDF
upload, physical-page extraction creation, status/conflict filters and active-job polling without
fake progress. The focused frontend gate is accepted: 12/12 page tests plus Prettier, ESLint and
TypeScript all pass; no deprecated Ant Design List remains.

### Goal

Extend the existing Sources page with the already-designed Stage 8A PDF upload, physical-page
range and real Job-state workflow. Preserve all existing manual-source behavior. This is a bounded
frontend integration against generated, accepted API types; it must not invent extraction progress
or call OCR/AI directly.

### Permitted edit boundary

- `frontend/src/app/SourcesPage.tsx`
- `frontend/src/app/WorkbenchPages.test.tsx`
- `docs/agent/HANDOFF.md` (append evidence only)

The following Codex-owned files are read-only inputs: `frontend/src/logic/api/client.ts` already
exports `requestFormData`; `frontend/src/logic/api/types.ts` already exports `PdfAsset*` and
`PdfExtraction*`; `frontend/src/types/api.generated.ts` is generated and must not be hand-edited.
Do not touch backend/OpenAPI, styles, other components/tests, package/dependency files or Makefile.

### Exact user workflow

- Keep the current Sources title, search/kind filters, manual-source cards and “添加手工来源” modal
  behavior unchanged. Add a prominent card before the existing source grid titled `AI 棋书识别`.
- Fetch `/api/pdf-assets` and `/api/pdf-extractions` with SWR in addition to the existing sources.
  The two new responses are `{items: [...]}`. Poll extractions every 2 seconds only while at least
  one visible item is queued or running; do not show a fabricated percentage/ETA.
- Upload form: accessible fields `PDF 文件`, `标题（可选）`, `作者（可选）`, `版本（可选）` and
  button `上传 PDF`. Require one `.pdf`/`application/pdf` file client-side. Build `FormData` with
  `file`; include one `metadata` JSON string only when any trimmed metadata is non-empty. Call
  `requestFormData<PdfAssetEnvelope>("/api/pdf-assets", formData)`. On success refresh asset data,
  select the returned asset, reset the file/metadata controls and display a success message that
  distinguishes new upload from content replay. On error display the safe `ApiError.message`.
- Extraction form: asset select `选择 PDF` shows title plus physical page count; numeric inputs
  `起始物理页` and `结束物理页`, minimum 1 and maximum selected asset page_count; button
  `创建识别任务`. Selecting an asset defaults the range to `1..page_count`; users can enter
  `319..399`. Prevent/label missing asset, non-integer, reverse or out-of-bounds ranges before POST.
  POST exact JSON `{pdf_asset_id, first_page, last_page}` to `/api/pdf-extractions`, then refresh
  run data and show new-vs-replayed success feedback.
- Extraction list has accessible filters `任务状态` (all + five Job statuses) and `冲突状态`
  (all/无冲突/有冲突). Build query strings only for non-all filters, using lowercase `true/false`.
  Each row identifies PDF title (fall back to asset UUID), inclusive physical range, a Chinese
  status label for queued/running/succeeded/failed/cancelled, and conflict state. Show the safe
  `last_error_message` only when present. Empty assets/runs use explicit Ant Design Empty states.
  Include a short note that the page displays only real backend Job state and does not estimate
  progress.
- Keep layout responsive and readable with existing utility classes/Ant Design. Do not add a new
  dependency, custom CSS, direct disk/provider access, cancellation, review/publish controls or
  fake extraction results.

### Focused tests

Extend the existing page tests so fetch mocks distinguish all three GET resources. Preserve the
manual source assertions. Add deterministic tests proving: initial PDF asset/run rendering;
upload sends FormData with file + trimmed nonempty metadata and refreshes; choosing an asset and
entering 319/399 sends the exact JSON extraction request; status/conflict filter changes request
the expected URL; queued/failed/conflict/empty states and the no-estimated-progress note render.
Do not use snapshots or mock `console`.

Run exactly:

```bash
pnpm --dir frontend exec prettier --check \
  src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
pnpm --dir frontend exec eslint \
  src/app/SourcesPage.tsx src/app/WorkbenchPages.test.tsx
pnpm --dir frontend exec tsc --noEmit
pnpm --dir frontend exec vitest run src/app/WorkbenchPages.test.tsx
git diff --check
```

Stop and report if generated types/client behavior contradicts the packet or existing page tests
require changes outside the boundary. If green, append evidence to HANDOFF, report pending Codex
review, do not begin acceptance/8B and do not commit.

## Completed packet: DS-STAGE8A-PDF-API-TESTS-01 (8A-3C)

Codex accepted the black-box packet after reading the complete test module and independently
rerunning its gate: 25 passed (11 API + 14 worker). Codex also generated and drift-checked OpenAPI
and TypeScript contracts. Focused Ruff/MyPy and `git diff --check` are clean.

### Goal

Add deterministic black-box HTTP tests for the Codex-owned and now-frozen Stage 8A PDF routes,
including upload replay, asset discovery, extraction idempotency/filtering and the registered-kind
worker invariant. Production code is read-only for this packet: report any mismatch rather than
changing it.

### Permitted edit boundary

- `backend/tests/test_pdf_api.py` (new)
- `docs/agent/HANDOFF.md` (append evidence only)

Do not edit any production module, existing test, schema, model/migration, config, route/app,
service, worker/jobs code, dependency/lock, Makefile, generated contract, frontend, ADR or PLANS.

### Frozen HTTP behavior to prove

- Build an isolated app with temporary SQLite/storage, `engine_worker_enabled=False`, a small
  explicit `pdf_max_bytes`, and `Base.metadata.create_all`. Generate only tiny deterministic PDFs
  in memory with the installed `pypdf`; never read `data/books` or call network/provider code.
- `POST /api/pdf-assets` accepts exactly one multipart `file` and optional strict JSON `metadata`.
  A valid PDF returns 201, `Idempotency-Replayed: false`, a canonical Location and an envelope
  with page count/source IDs/first metadata but no path. The CAS blob exists under the accepted
  hash layout. Same bytes with different filename/metadata returns 200, replay true, the same IDs
  and original metadata; exactly one PdfAsset/Source/Version/File/blob exists.
- `GET /api/pdf-assets/{id}` returns the same read model; `GET /api/pdf-assets` discovers persisted
  assets in newest-first order and exposes no path. Missing UUID resources return stable 404.
- `POST /api/pdf-extractions` returns 202 for a new valid physical range and 200 for exact replay;
  Location/replay headers and nested Job fields are exact (`pdf_extraction`, queued, attempt 0,
  finite profile). Explicit same key + different page/profile returns 409 with no new run/job;
  missing asset and out-of-range/reverse pages return 404/422 with no new run/job.
- GET-one and list return the same run/job state. `status=queued` and `has_conflicts=false` include
  it; other valid statuses and `has_conflicts=true` exclude it. Unknown/duplicate status,
  non-lowercase/duplicate/invalid conflict booleans return 422. Do not invent progress.
- An engine `SqlWorker` with its default registered handler returns false when only the queued
  `pdf_extraction` job exists; the PDF job remains queued with attempt_count 0 and no error.
- Transport/validation rejection covers non-multipart media, missing/duplicate file, unknown part,
  duplicate/invalid/unknown metadata, fake PDF, declared non-PDF MIME and a payload over configured
  `pdf_max_bytes`. Each uses the stable public code/status and creates no authoritative SQL rows;
  invalid input must not expose bytes, absolute paths or parser text.
- The application request cap is at least `pdf_max_bytes + 1 MiB`; down-configuring PDF size must
  not reduce Sanic's larger default cap. No Course/Knowledge row is created by upload/enqueue.

Use fixed UUID/timestamp expectations only where the implementation makes them deterministic; do
not use random UUIDs, sleep, real subprocesses or private-helper assertions. Close every Database.

### Focused oracle

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_api.py backend/tests/test_stage6_jobs.py
uv run --project backend --locked ruff format --check backend/tests/test_pdf_api.py
uv run --project backend --locked ruff check backend/tests/test_pdf_api.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_pdf_api.py
git diff --check
```

Stop at the first production mismatch and report the response/row evidence. Do not weaken any
oracle or broaden the edit boundary. If green, append evidence to HANDOFF, report pending Codex
review, do not start 8A-4 and do not commit.

## Completed packet: DS-STAGE8A-PDF-API-SCHEMAS-01 (8A-3A)

Codex accepted the delegated contracts after full actual-diff review and independent execution of
the exact gate (46 passed). Codex removed the worker's narrow `__all__` compatibility hazard while
preserving explicit identity-equal Job re-exports, then added the architecture-required
`PdfAssetList` contract for reload-safe asset discovery. Focused Ruff/MyPy are clean.

### Goal

Implement the exact HTTP data contracts already frozen below, while extracting the existing
generic `JobRead` contract out of the engine-specific schema module without changing its generated
shape. This packet contains no route, SQL query, transaction, worker or frontend behavior.

### Permitted edit boundary

- `backend/src/chess_workbench/schemas/jobs.py` (new)
- `backend/src/chess_workbench/schemas/engine.py` (only remove Job types and import/re-export them)
- `backend/src/chess_workbench/schemas/pdf.py` (new)
- `backend/tests/test_pdf_schemas.py` (new)
- `docs/agent/HANDOFF.md` (append evidence only)

No other file may be edited. In particular do not touch services, models/migrations, routes/app,
worker/jobs implementation, contracts generator/output, config, dependencies, Makefile, frontend,
ADRs or existing tests.

### Exact contracts

`schemas/jobs.py` owns, unchanged from `schemas.engine`, `JobStatusValue` and `JobRead`. Import and
re-export both names from `schemas.engine` so all existing imports and JSON Schema remain compatible.

`schemas/pdf.py` exposes:

- `PdfAssetUploadMetadata(StrictContract)`: optional `title`, `author`, `edition`, each using the
  existing `Title` contract and defaulting to None.
- `PdfExtractionCreate(StrictContract)`: `pdf_asset_id: EntityId`, `first_page` and `last_page`
  integers >=1, `profile: dict[str, JsonValue]` default empty. Reject `last_page < first_page`.
  Recursively reject non-finite floats in profile. Preserve a deep caller-independent snapshot;
  normal JSON null/bool/int/finite float/string/list/object values are allowed.
- `PdfAssetRead(StrictContract)`: `id`, `content_sha256`, positive `byte_size`, `page_count` in
  1..20,000, `source_id`, `source_version_id`, `source_file_id`, `filename: Title`, `title: Title`,
  optional `author`/`edition`, and `created_at: UtcDateTime`. Do not expose relative/absolute path.
- `PdfAssetEnvelope(StrictContract)`: `replayed: bool`, `asset: PdfAssetRead`.
- `PdfExtractionRead(StrictContract)`: `id`, `pdf_asset_id`, page range, non-empty
  `pipeline_version`, `profile`, nested generic `job: JobRead`, `has_conflicts: bool = False`, and
  `created_at`. Apply the same page-order and finite-profile validation as create.
- `PdfExtractionEnvelope(StrictContract)`: `replayed: bool`, `extraction: PdfExtractionRead`.
- `PdfExtractionList(StrictContract)`: `items: list[PdfExtractionRead]`.

All object boundaries inherit `extra="forbid"` and frozen behavior. Do not add client-provided
hash/path/job status/idempotency fields. JSON UUID strings and RFC3339 UTC strings must round-trip
through normal `model_validate_json`; Python-mode instances follow existing contract conventions.

### Focused oracle

Prove exact field sets/defaults, unknown-field rejection at every nested boundary, Title/page/size
constraints, reverse-range rejection, recursive NaN/Infinity rejection, deep profile isolation,
asset path absence, UTC/UUID JSON round trip, nested Job status validation, immutable models and
OpenAPI 3.0 conversion with no dangling `$ref`/`$defs`. Also prove the old
`from schemas.engine import JobRead, JobStatusValue` path is identity-equal to `schemas.jobs` and
its canonical model JSON Schema is unchanged in shape.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_schemas.py backend/tests/test_stage6_engine.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/src/chess_workbench/schemas/jobs.py backend/src/chess_workbench/schemas/engine.py \
  backend/src/chess_workbench/schemas/pdf.py backend/tests/test_pdf_schemas.py
git diff --check
```

### Invariants and escalation

- Existing engine consumers must see the same JobRead class and schema, not a duplicate class.
- Do not introduce SQLAlchemy/Sanic/service/provider imports into schemas.
- Stop if the exact contract requires a route/service/model change or existing Stage 6 tests expose
  incompatible behavior. Report `pending Codex review`; do not begin worker/routes/8A-4 or commit.

## Completed packet: DS-STAGE8A-PDF-PERSISTENCE-TESTS-01 (8A-2C2 tests)

Codex accepted the delegated black-box suite after reviewing all cases, replacing its two random
UUIDs with fixed UUIDs and adding one real bytes → inspection → CAS → SQL replay test. The final
focused result is 57 passed (50 persistence/integration plus 7 model tests); strict configured
MyPy, Ruff and `git diff --check` are clean. The packet's original mypy command omitted the backend
config and was corrected to use `--config-file backend/pyproject.toml`.

### Goal

Add deterministic black-box service tests for the Codex-owned transactional implementation in
`services/pdf_persistence.py`. The implementation and its public behavior are frozen; this packet
may only add the focused test module and report evidence. If a behavior fails, report it to Codex
instead of changing production code or weakening the oracle.

### Permitted edit boundary

- `backend/tests/test_pdf_persistence.py` (new)
- `docs/agent/HANDOFF.md` (append completion/escalation evidence only)

No other file may be edited, including `services/pdf_persistence.py`, models, migrations, jobs,
content, schemas, routes, config, frontend, Makefile, dependencies, ADRs or existing tests.

### Frozen service contract to prove

- `register_asset(prepared)` creates exactly one linked `Source(kind="book") → SourceVersion →
  SourceFile → PdfAsset`, copies prepared title/author/edition/file/hash/size/page metadata, and
  returns `replayed=False`. Sequential registration of the same content hash returns the original
  asset with `replayed=True`, creates no rows and does not overwrite the first display metadata.
- The caller owns the transaction. Raising from fault phases `source`, `source_version`,
  `source_file` or `pdf_asset` and letting the outer transaction exit leaves zero rows in all four
  tables. A normal caller rollback also leaves zero rows.
- `enqueue_extraction` requires an existing asset and a physical page range satisfying
  `1 <= first_page <= last_page <= page_count`; rejection creates no run, Job or invalidation.
- The canonical logical fingerprint includes asset content hash, pages, fixed pipeline version
  and a recursively finite JSON profile. Object key order does not matter and the Job payload owns
  a deep JSON snapshot. Non-dict/type-invalid/non-finite profiles are rejected without SQL writes.
- Without an Idempotency-Key, the logical fingerprint is the effective key: exact replay returns
  the same run/job. Different page ranges create different runs/jobs.
- A valid explicit key is 1..128 visible ASCII and is stored only as SHA-256. Same key/same request
  replays; same key/different request returns `409 idempotency_conflict` with zero new rows;
  different explicit keys for the same logical request create distinct runs/jobs sharing the
  logical fingerprint.
- A newly queued job has kind `pdf_extraction`, status `queued`, and an exact payload containing
  schema version, deterministic run/asset IDs, page range, `pdf-extraction:v1` and profile. Job and
  run are in one transaction; faults at `job` or `extraction_run` roll back run, Job and its
  invalidation event while retaining the previously committed asset.
- Programmer type misuse for prepared/UUID/page integers/idempotency/profile raises TypeError;
  ServiceError code/status/message/details match the implementation's frozen strings. Do not
  assert private helper functions.

Use a temporary SQLite `Database` and `Base.metadata.create_all`; construct small immutable
`PreparedPdfAsset` values directly. Do not read `data/books`, touch a real CAS, use sleep/randomness,
or call HTTP/network. Keep cases table-driven where that remains readable.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_persistence.py backend/tests/test_stage8_models.py
uv run --project backend --locked ruff format --check backend/tests/test_pdf_persistence.py
uv run --project backend --locked ruff check backend/tests/test_pdf_persistence.py
uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  backend/tests/test_pdf_persistence.py
git diff --check
```

### Escalation and completion

Stop at the first production mismatch and report the exact failing test and evidence; do not edit
production code. Preserve unrelated worktree changes. If green, append exact counts/commands to
HANDOFF, report `pending Codex review`, do not start 8A-3 and do not commit.

## Completed packet: DS-STAGE8A-PDF-PREPARE-01 (8A-2C1)

Codex accepted this packet after actual-diff review and independent execution of its exact focused
oracle: 121 tests passed; Ruff, MyPy and `git diff --check` are clean.

### Goal

Implement only the pure pre-transaction PDF upload preparation boundary: validate one PDF and its
display metadata, persist the validated bytes through the accepted generic CAS, and return an
immutable prepared value for the later SQL service. No SQL session, ORM model, Job, HTTP request,
worker or public API contract is part of this packet.

### Permitted edit boundary

- `backend/src/chess_workbench/services/pdf.py` (new)
- `backend/tests/test_pdf_prepare.py` (new)
- `docs/agent/HANDOFF.md` (append completion evidence only)

No other file may be edited. In particular do not touch PDF inspection, generic CAS, PGN,
dependencies/lock, schemas, models/migrations, content/jobs services, routes, config, frontend,
Makefile, ADRs or existing tests.

### Exact public behavior

Expose from `services/pdf.py`:

```python
@dataclass(frozen=True, slots=True)
class PreparedPdfAsset:
    filename: str
    content_sha256: str
    size_bytes: int
    page_count: int
    relative_path: str
    title: str
    author: str | None
    edition: str | None
    storage_reused: bool

def prepare_pdf_asset(
    raw_bytes: bytes,
    *,
    filename: str,
    declared_media_type: str | None,
    title: str | None,
    author: str | None,
    edition: str | None,
    storage_root: Path,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
) -> PreparedPdfAsset: ...
```

Behavior is frozen:

1. Call `inspect_pdf` before any filesystem operation, passing all five inspection inputs exactly.
2. Validate display metadata only after successful inspection and before CAS. Each non-None value
   must be an actual `str` (not coercible), must equal its `.strip()` value, and have 1..200 Unicode
   code points. Programmer type misuse raises `TypeError`; bad whitespace/length raises a stable
   `ServiceError("validation_error", 422, "PDF metadata is invalid", {"field": <name>})` with no
   raw value. Missing title defaults exactly to the validated filename without its final `.pdf`
   suffix, preserving spelling/case. Author and edition remain optional.
3. Map `PdfInspectionError` without leaking parser messages/bytes/paths: `payload_too_large` →
   `ServiceError("payload_too_large", 413, "PDF payload exceeds the configured limit",
   {"limit_bytes": max_bytes})`; `unsupported_media_type` → status 415/code same/message
   `"PDF media type is not supported"`; all other reasons → status 422/code `validation_error`/
   message `"PDF upload is invalid"`. Include only `{"reason": error.reason}` for the latter two.
   Construct the public error after leaving the `except` block so cause and context are both None.
4. Store only after inspection and metadata validation using the accepted primitive with exact
   namespace `sources/pdf`, suffix `.pdf`, and the original bytes. Do not reimplement hashing or
   file writes. Let the generic sanitized `source_storage_unavailable` pass through unchanged.
5. Return inspection filename/size/page count, CAS hash/path/reused flag and normalized metadata.
   Do not retain raw bytes, a parser object, absolute path or mutable mapping in the result.
6. Any `KeyboardInterrupt`, `SystemExit` or other non-`Exception` BaseException from inspection,
   metadata access or CAS must propagate unchanged.

### Required focused tests

Use deterministic in-memory PDFs only; never read `data/books`. Prove:

- successful one-page preparation and exact `sources/pdf/<prefix>/<hash>.pdf` content/mode 0600;
- identical bytes replay the same path/hash with `storage_reused=True` and no second blob;
- title fallback, valid explicit metadata and every field's strict type/trim/empty/over-200 cases;
- all seven inspection reasons map to the frozen ServiceError code/status/message/details and do
  not create the storage root; mapped errors have `__cause__ is None` and `__context__ is None`;
- CAS failure is passed through unchanged and no prepared result is returned;
- validation happens before CAS (spy/monkeypatch) and BaseException propagation.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_prepare.py backend/tests/test_pdf_inspection.py \
  backend/tests/test_source_storage.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
uv run --project backend --locked mypy \
  backend/src/chess_workbench/services/pdf.py backend/tests/test_pdf_prepare.py
git diff --check
```

### Preserved invariants and escalation

- This is transaction-external preparation: no authoritative SQL row or Job is created here.
- Filename and metadata never influence a disk path; only the CAS digest does.
- Do not catch BaseException, expose parser/OS details, add a new error code or alter existing
  inspection/CAS behavior.
- Stop if the frozen behavior requires editing any file outside the boundary. Report
  `pending Codex review`; do not begin the transactional service, API, worker or frontend and do
  not commit.

## Completed packet: DS-STAGE8A-PDF-MODELS-01 (8A-2B)

Codex accepted this packet after reviewing the actual diff, correcting the real-MySQL head/table
expectations in `backend/tests/test_mysql_compat.py`, and independently obtaining 18 passed plus
4 environment-skipped MySQL tests. Focused Ruff, MyPy and `git diff --check` are clean.

### Goal

Implement the already-frozen Stage 8A persistence shape and one additive Alembic revision for
immutable PDF assets, extraction request receipts and derived artifact indexes. This packet has no
service transaction, HTTP schema/route, worker behavior, file I/O or PDF parsing.

### Permitted edit boundary

- `backend/src/chess_workbench/store/models/extraction.py` (new)
- `backend/src/chess_workbench/store/models/__init__.py` (imports/exports only)
- `backend/migrations/env.py` (model registration only)
- `backend/migrations/versions/20260811_0010_stage8_pdf_extraction.py` (new)
- `backend/tests/test_stage8_models.py` (new)
- `backend/tests/test_models.py` (only revision-count/import assertions needed for the new tables)
- `docs/agent/HANDOFF.md` (append completion evidence only)

No other file may be edited. Do not touch dependencies/lock, PDF inspection, CAS/PGN, schemas,
services, jobs/worker, routes, config, frontend, Makefile, ADRs or existing migrations.

### Exact ORM shape

Use `UUIDPrimaryKeyMixin + UTCCreatedAtMixin + Base` for all three immutable models. Use MySQL
InnoDB, RESTRICT foreign keys, `Uuid(as_uuid=True)`, current UTC mixins and local helpers equivalent
to the existing `_ascii_string` / `_case_sensitive_string` so hash comparison is ASCII binary and
relative paths are utf8mb4 binary on MySQL. Do not import another module's private helper.

`PdfAsset`, table `pdf_assets`:

- `content_sha256: String(64)`, `byte_size: Integer`, `page_count: Integer`;
- `source_id → sources.id`, `source_version_id → source_versions.id`,
  `source_file_id → source_files.id`, all non-null RESTRICT;
- checks: hash length 64; byte size >0; page count 1..20,000;
- separate unique constraints on content hash, source_id, source_version_id and source_file_id.

`ExtractionRun`, table `extraction_runs`:

- `pdf_asset_id → pdf_assets.id`, `job_id → jobs.id`, non-null RESTRICT;
- `first_page`, `last_page` integer; `pipeline_version: String(32)`;
- `logical_fingerprint` and `effective_key_hash`: ASCII-binary String(64);
- checks: first page >=1; last page >= first page; non-empty pipeline version; both hashes length 64;
- unique effective_key_hash and unique job_id. **Do not make logical_fingerprint unique**; add
  index `ix_extraction_runs_fingerprint` on it and index
  `ix_extraction_runs_asset_created` on `(pdf_asset_id, created_at)`.

`ExtractionArtifact`, table `extraction_artifacts`:

- `run_id → extraction_runs.id`, non-null RESTRICT;
- `kind: String(32)` limited exactly to `rendered_page`, `render_manifest`, `ocr_fragment`,
  `ocr_manifest`, `provider_response`, `raw_ccef`, `normalized_ccef`;
- nullable `page_number: Integer`; `relative_path: case-sensitive String(512)`;
  `media_type: String(255)`; `byte_size: Integer`; `content_sha256: ASCII String(64)`;
- checks: nullable page number is >=1 when present; relative path/media type non-empty; byte size
  >0; hash length 64;
- unique relative_path; unique `(run_id, kind, content_sha256)`; index
  `ix_extraction_artifacts_run_kind_page` on `(run_id, kind, page_number)`.

Relationships may be added only between these records and their direct Source/Job parents; no
cascade/delete-orphan and no mutable lifecycle/version/archive fields.

Export all three names from `store.models`; register all three in Alembic env. The revision ID is
exactly `20260811_0010`, down revision `20260810_0009`; upgrade order is asset → run → artifact and
downgrade is exact reverse with `op.drop_table` only (no explicit ordinary-index drops).

### Required focused tests

`test_stage8_models.py` plus the existing migration test must prove:

- exact table/column sets and absence of status/version/updated_at/archived_at;
- UUID + aware UTC creation round-trip for a valid linked Source/Version/File/Job/asset/run/artifact;
- every check/unique constraint above rejects a minimal invalid row on SQLite;
- two runs may share `logical_fingerprint` when effective keys/jobs differ;
- every new FK is RESTRICT; MySQL DDL contains InnoDB, ascii/utf8mb4 binary collations and
  DATETIME(6); all constraint names stay <=64 characters;
- migrations upgrade from base to head with no metadata drift and downgrade to zero tables;
- offline MySQL downgrade contains no `DROP INDEX` before table removal.

Update the existing exact revision count from 9 to 10. Do not weaken any other existing assertion.

Run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_stage8_models.py backend/tests/test_models.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/store/models/extraction.py \
  backend/src/chess_workbench/store/models/__init__.py backend/migrations/env.py \
  backend/migrations/versions/20260811_0010_stage8_pdf_extraction.py \
  backend/tests/test_stage8_models.py backend/tests/test_models.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/store/models/extraction.py \
  backend/src/chess_workbench/store/models/__init__.py backend/migrations/env.py \
  backend/migrations/versions/20260811_0010_stage8_pdf_extraction.py \
  backend/tests/test_stage8_models.py backend/tests/test_models.py
uv run --project backend --locked mypy \
  backend/src/chess_workbench/store/models/extraction.py \
  backend/src/chess_workbench/store/models/__init__.py backend/migrations/env.py \
  backend/migrations/versions/20260811_0010_stage8_pdf_extraction.py \
  backend/tests/test_stage8_models.py backend/tests/test_models.py
git diff --check
```

### Preserved invariants and escalation

- Job is the only operational status; no status/progress/result JSON column on ExtractionRun.
- These records are immutable receipts/indexes: no update/archive/version mixins or delete cascade.
- Source/Version/File ownership and CCEF IDs remain unchanged; no package/provider data is stored.
- Stop rather than changing the model if SQLite/MySQL portable constraints disagree, Alembic
  autogenerate reports unexplained drift, a required constraint name exceeds 64, or a correct fix
  needs any file outside the boundary. Report `pending Codex review`; do not start 8A-2C or commit.

## Completed packet: DS-STAGE8A-PDF-INSPECTION-01 (8A-2A)

### Goal

Implement a pure, bounded PDF inspection boundary using BSD-3-Clause `pypdf`. It validates upload
bytes/filename/declared MIME, rejects encrypted or unusable documents and returns only immutable
physical-page metadata. It performs no storage, SQL, HTTP, OCR, rendering or source creation.

### Codex-frozen dependency and license

Add production dependency `pypdf>=6.14.2,<7`. Resolve the existing lock without changing any other
declared dependency. PyPI identifies pypdf as BSD-3-Clause and Python 3.13 compatible. Do not add
PyMuPDF, pypdfium2, OCR packages, optional crypto extras or a tool-manifest entry in this packet.

### Permitted edit boundary

- `backend/pyproject.toml` (one dependency line only)
- `backend/uv.lock` (resolver output for pypdf only; preserve accumulated 8P entries)
- `backend/src/chess_workbench/logic/pdf.py` (new)
- `backend/tests/test_pdf_inspection.py` (new)
- `docs/agent/HANDOFF.md` (append completion evidence only)

No other file may be edited. In particular do not touch CAS/PGN, configuration, schemas, models,
migrations, services, routes, frontend, Makefile, ADRs, existing tests or the user's `data/books`.

### Exact public behavior

Expose only:

```python
MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_PDF_PAGES = 20_000

@dataclass(frozen=True, slots=True)
class PdfInspection:
    filename: str
    size_bytes: int
    page_count: int
    media_type: Literal["application/pdf"] = "application/pdf"

class PdfInspectionError(ValueError):
    reason: Literal[
        "empty_pdf", "payload_too_large", "invalid_filename",
        "unsupported_media_type", "invalid_pdf", "encrypted_pdf",
        "page_limit_exceeded"
    ]

def inspect_pdf(
    raw_bytes: bytes,
    *,
    filename: str,
    declared_media_type: str | None,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PDF_PAGES,
) -> PdfInspection: ...
```

Validation order and semantics are fixed:

1. Require `raw_bytes` to be actual `bytes`; `filename` actual `str`; declared media type either
   `None` or actual `str`; max values actual positive ints (not bool). Programmer type/limit misuse
   raises `TypeError`/`ValueError`, not `PdfInspectionError`.
2. Reject empty bytes, then `len(raw_bytes) > max_bytes` with the respective stable reason.
3. Preserve filename verbatim but require 1..200 Unicode code points, no C0/C1 control character,
   NUL, `/` or `\\`, a non-empty/non-dot/non-whitespace basename before a case-insensitive `.pdf`
   suffix, and no leading/trailing whitespace. Failure reason is `invalid_filename`. Filename never
   becomes a path in this module.
4. Normalize declared MIME only with ASCII whitespace trim and lowercase. Accept `None`, empty, or
   exactly `application/pdf`; reject parameters and every other value as
   `unsupported_media_type`. MIME does not prove content.
5. Require a `%PDF-<major>.<minor>` header within the first 1024 bytes, with major 1 or 2 and one
   decimal minor digit. Otherwise `invalid_pdf` before parser construction.
6. Parse `BytesIO(raw_bytes)` with `pypdf.PdfReader(strict=False,
   root_object_recovery_limit=10_000)`. Reject `reader.is_encrypted` before reading pages. Obtain
   `len(reader.pages)`; zero pages is `invalid_pdf`; greater than `max_pages` is
   `page_limit_exceeded`.
7. Contain expected parser/data failures including `PdfReadError`, `RecursionError`, `ValueError`,
   `TypeError`, `KeyError`, `IndexError` and `OSError` as `PdfInspectionError("invalid_pdf")` with a
   fixed message and no chained exception. `MemoryError`, `KeyboardInterrupt`, `SystemExit` and
   other `BaseException` propagate. No raw bytes, parser text or absolute path appears in any
   public error.
8. Success returns the exact input filename, byte length, physical page count and canonical MIME;
   it never extracts text, metadata, attachments, JavaScript, printed page labels or writes files.

Give every `PdfInspectionError.reason` a fixed English message. `str(error)` is that message;
construct public errors outside active parser exception handlers so both `__cause__` and
`__context__` are `None`.

### Required focused tests

Generate all fixtures in memory with `pypdf.PdfWriter`; do not read user books or check in binary
fixtures. Prove:

- 1-page and 3-page PDFs return exact immutable metadata; uppercase `.PDF` and empty/None MIME work;
- an encrypted writer result is rejected before page access;
- zero-page writer, empty bytes, fake `%PDF` bytes, missing/bad signature, oversize, page-limit,
  wrong/parameterized MIME and filename traversal/control/length/whitespace families get exact
  reasons;
- the signature may begin after a short binary comment but not after byte 1024;
- monkeypatched parser/data failures are sanitized with no cause/context or attacker text;
- parser is never constructed for preflight failures; input bytes remain identical;
- injected `KeyboardInterrupt` and `MemoryError` propagate.

Run exactly:

```bash
uv lock --project backend
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_pdf_inspection.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py
uv run --project backend --locked mypy \
  backend/src/chess_workbench/logic/pdf.py backend/tests/test_pdf_inspection.py
git diff --check
```

### Preserved invariants and escalation

- No PDF output enters CCEF or ChessWorkbench models; this is inspection only.
- No warnings/test/coverage/type floor may be weakened; do not silence parser warnings globally.
- Do not infer behavior from the five user books or add a live/network test.
- Stop if pypdf 6.14.2 cannot resolve on Python 3.13, its actual API contradicts the frozen call,
  or a correct implementation needs any path outside the boundary. Report `pending Codex review`,
  do not start 8A-2B and do not commit.

### Codex review

**Accepted.** Codex reviewed the real parser call, validation order, filename/MIME/signature gates,
encryption-before-pages behavior, fixed public errors, BaseException propagation and lock delta.
`pypdf==6.15.0` is the resolved BSD-3-Clause implementation within the frozen `<7` range; only its
own package was added beyond the accumulated 8P lock state. Independent focused verification is
63 tests passed plus clean configured Ruff format/check, MyPy and `git diff --check`.

The worker initially paused because the new wheel was not cached; Codex performed the locked sync
and resumed the same private process. No user book, storage, SQL, API, OCR/rendering, full acceptance
or commit was involved. 8A-2B is now the active bounded model/migration packet above.

## Completed packet: DS-STAGE8A-CAS-01 (8A-1)

### Goal

Extract the already-proven atomic bytes CAS from the PGN service into a small reusable source
storage module. This packet changes no API, database, path layout, error contract or payload limit.

### Permitted edit boundary

- `backend/src/chess_workbench/services/source_storage.py` (new)
- `backend/src/chess_workbench/services/pgn.py`
- `backend/tests/test_source_storage.py` (new)
- `docs/agent/HANDOFF.md` (append completion evidence only)

No other file may be edited. In particular do not touch schemas, SQL models/migrations, routes,
configuration, dependencies/lockfiles, frontend, Makefile, ADRs or existing tests.

### Exact behavior

1. Add a frozen result value containing `relative_path`, lowercase `sha256`, `size_bytes` and
   `reused`.
2. Add one synchronous `store_content_addressed_bytes(storage_root, *, namespace, suffix,
   raw_bytes)` function. `namespace` and `suffix` are controlled caller inputs but must be strictly
   validated before filesystem access: namespace is one or more lowercase ASCII segments matching
   `[a-z0-9][a-z0-9_-]*` separated only by `/`; suffix is `.` plus 1..16 lowercase ASCII
   alphanumeric characters. Reject absolute paths, empty/dot/dot-dot segments, backslashes,
   whitespace and non-ASCII with `ValueError`.
3. The returned relative path is exactly
   `<namespace>/<sha256[:2]>/<sha256><suffix>`. The function computes the digest itself; callers
   cannot supply a path or expected digest.
4. Preserve the PGN write guarantees: create parent directories; if destination exists, verify its
   byte size and SHA-256 and return `reused=True`; otherwise use a temp file in the destination
   directory, write/flush/fsync, chmod 0600, verify size/hash, atomically replace, always clean the
   temp path, and return `reused=False`.
5. Filesystem `OSError` (including an existing corrupt blob) becomes the existing sanitized
   `ServiceError(code="source_storage_unavailable", status=503)`. The generic message is
   `"source storage is unavailable"`; no absolute path or OS message is exposed.
6. Refactor `prepare_pgn_import` to call the new function with namespace `sources/pgn` and suffix
   `.pgn`. Keep `PreparedPgnImport.relative_path`, all hashes, PGN API responses, errors and the
   exact `sources/pgn/<prefix>/<hash>.pgn` layout unchanged. Remove the private duplicate helper and
   now-unused imports only.

### Required focused tests

`backend/tests/test_source_storage.py` must deterministically prove:

- a new blob has correct bytes/path/hash/size, mode 0600 and `reused=False`;
- the same bytes replay returns the same result except `reused=True` and does not change contents;
- each invalid namespace/suffix family raises before creating any storage-root content;
- a pre-existing corrupt destination raises sanitized `ServiceError` and is not overwritten;
- an injected write/replace failure leaves no `.*.tmp` file and exposes no absolute path/OS text.

Then run exactly:

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_source_storage.py backend/tests/test_pgn_api.py
uv run --project backend --locked ruff format --check \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
uv run --project backend --locked ruff check \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
uv run --project backend --locked mypy \
  backend/src/chess_workbench/services/source_storage.py \
  backend/src/chess_workbench/services/pgn.py backend/tests/test_source_storage.py
git diff --check
```

### Preserved invariants and escalation

- No raw bytes, absolute path or `OSError` text crosses the public service error.
- Existing corrupt blobs are evidence of storage failure and must never be overwritten.
- Do not weaken or rewrite existing PGN tests.
- Do not introduce a class hierarchy, async I/O, streaming, a new dependency or PDF-specific code.
- Stop and report evidence if platform behavior prevents deterministic permission/failure tests, an
  existing PGN test fails for a non-CAS reason, or any required behavior needs a file outside the
  permitted boundary. Report `pending Codex review`; do not begin 8A-2 and do not commit.

### Codex review

**Accepted after Codex correction.** The worker stayed within its permitted boundary and the CAS
layout/PGN behavior are preserved. Review found that `raise ... from None` suppresses traceback
display but leaves the original `OSError` reachable through `__context__`; Codex moved public-error
construction outside the exception handler and added direct `__context__ is None` assertions.
Codex also closes a file descriptor when `os.fdopen` itself fails and hashes existing/temporary
files in 1 MiB chunks so a future large PDF replay does not allocate a second full-file buffer.

Independent focused acceptance: 39 CAS/PGN API tests pass; configured Ruff format/check and MyPy
over the three packet files are clean; `git diff --check` is clean. No full repository acceptance,
PDF work, database/API change or commit was performed. 8A-2 is next and requires a separate packet.

## Final 8P feature-boundary review (2026-08-11)

**Accepted after Codex-owned cross-layer corrections.** The provider-neutral request/response
port, DeepSeek transport, CCEF decoder, deterministic chess normalization and standalone consumer
now compose without reversing the ADR 0010 dependency direction.

Corrections found only at the combined boundary:

1. package-root imports are lazy for the HTTP adapter and python-chess normalizer, so importing
   `chess_workbench.extraction.contracts` loads neither `httpx` nor `chess`;
2. the generated Schema closes every namespaced extension map and requires every discriminator,
   matching the runtime contract rather than accepting inputs Pydantic rejects;
3. provider finish reasons are normalized to `stop | length`; current official DeepSeek
   `content_filter`/`tool_calls`/unknown/null results are rejected, while
   `insufficient_system_resource` is retryable `unavailable`;
4. the decoder contains content-driven recursion failure as sanitized `invalid_json`;
5. the standalone consumer rejects non-standard NaN/Infinity JSON, handles omitted default
   `items`, remains offline-only and preserves its byte-stable public sample projection.

Official DeepSeek request/response facts were rechecked against the current
[Chat Completions documentation](https://api-docs.deepseek.com/api/create-chat-completion) and
[model documentation](https://api-docs.deepseek.com/quick_start/pricing). No live API call was
made.

Focused acceptance: 294 tests across contract/provider/DeepSeek/decoder/chess validation/consumer,
configured Ruff format and lint, MyPy, isolated consumer/golden comparison and `git diff --check`.
No backend/frontend/full-repository acceptance was run. 8A remains unstarted and requires its own
Codex architecture plan.

## Completed packet: DS-STAGE8-CONSUMER-PROOF-01 (8P-5)

### Objective

Prove the output boundary is genuinely consumer-neutral by shipping one standalone example reader
that validates the published CCEF JSON Schema and consumes a checked-in normalized package without
importing ChessWorkbench, Pydantic, python-chess, provider code or database code. Also write the
Codex-frozen one-way mapping plan from CCEF candidates into the existing ChessWorkbench
Source/Block/Occurrence/KnowledgeNote model, including every known lossless-mapping blocker. This
packet performs no actual ChessWorkbench mapping and no persistence.

### Codex-frozen dependency

Codex has added `jsonschema>=4.23,<5` to the backend development group and resolved
`jsonschema==4.26.0` plus its transitive packages in `backend/uv.lock`. These files are outside the
worker boundary and must not be edited. The dependency is used only by the standalone example and
tests; production extraction code gains no import or runtime dependency on it.

### Permitted edit boundary

- `examples/ccef_consumer/consumer.py` (new)
- `contracts/examples/chess-content-extraction-v1.sample.json` (new)
- `contracts/examples/chess-content-extraction-v1.reader.json` (new golden projection)
- `backend/tests/test_ccef_consumer_proof.py` (new)
- `docs/architecture/ccef-chess-workbench-mapping.md` (new, exact plan below)
- `docs/agent/HANDOFF.md` (completion evidence only)

Do not edit backend extraction modules, `__init__.py`, the published Schema, dependency/lock files,
Makefile, configuration, SQL models, migrations, repositories, services, routes, frontend,
existing tests or any other file.

### Standalone consumer interface and isolation

`consumer.py` is an example, not a new stable ChessWorkbench API. It may import only Python's
standard library and these names from the external `jsonschema` package:
`Draft202012Validator`, `FormatChecker`, `SchemaError`, `ValidationError`. It must contain no
`chess_workbench`, Pydantic, python-chess/chess, provider, HTTP, SQL or environment/config import.

Expose:

```python
def load_validated_package(schema_path: Path, package_path: Path) -> dict[str, Any]: ...
def project_reader_document(package: dict[str, Any]) -> dict[str, Any]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

CLI:

```text
python consumer.py --schema PATH --package PATH
```

On success, write the deterministic reader projection as UTF-8 JSON to stdout using
`ensure_ascii=False`, `sort_keys=True`, `indent=2`, followed by exactly one newline; write nothing
to stderr and return 0. `python -I` from the repository root must work, proving the repository and
backend source are not import paths.

Load both files with UTF-8 and standard `json.load`. Require both top levels to be objects. Require
Schema `$schema == "https://json-schema.org/draft/2020-12/schema"` and
`$id == "urn:chess-content-extraction:schema:1.0"`; call
`Draft202012Validator.check_schema(schema)`, then validate the package with
`Draft202012Validator(schema, format_checker=FormatChecker())`. Do not fetch remote references.
After Schema validation, defensively require
`package["schema_version"] == "chess-content-extraction/1.0"`.

For malformed JSON, wrong top-level type, wrong Schema identity/dialect, invalid Schema, invalid
package or unsupported version: catch only the expected JSON/I/O/schema/validation/value errors,
write exactly `CCEF consumer rejected the input\n` to stderr, nothing to stdout, and return 2.
`KeyboardInterrupt`, `SystemExit`, `MemoryError` and other `BaseException` values propagate. Do not
repair, coerce, strip Markdown fences or print validation input/absolute paths.

### Exact reader projection

Return a fresh object; do not mutate the package. Top level:

```json
{
  "consumer_format": "example-ccef-reader/1",
  "schema_version": "chess-content-extraction/1.0",
  "package_id": "<string>",
  "source": "<deep copy of package.source>",
  "provenance": "<deep copy of package.provenance>",
  "entries": [],
  "diagnostics": "<deep copy of package.diagnostics or []>",
  "review_queue": []
}
```

`entries` follows package item order exactly. Every entry preserves common fields using these
names: `type` (the CCEF `kind`), `source_id` (`id`), `evidence`, `confidence`, `warnings`,
`extensions`. Defaults absent from externally-authored JSON are projected as `confidence: null`,
`warnings: []`, `extensions: {}`. Kind-specific fields:

- heading: `level`, `text`;
- prose: `text`, `text_format` (default `plain`), `anchor` (default null);
- move_sequence: `title` (default null), `initial_position`, and ordered `nodes`. Each node maps
  `source_id`, `parent_source_id`, `order`, `move_text`, `move_number`, `side_to_move`,
  `san`, `uci`, `status`, `fen_before`, `fen_after`, `nags`, `evidence`, `confidence`, `warnings`,
  `extensions`, with CCEF defaults for omitted optional/default fields;
- figure: `figure_type`, `caption`, `alt_text`, `position_fen_candidate`, applying null defaults;
- unresolved: `unresolved_type`, `reason_code`, `raw_text`, `details`, applying null defaults.

No CCEF item is dropped. Schema validation makes unknown kind unreachable; nevertheless the
projection function must raise `ValueError` for an unknown kind if called directly.

Build `review_queue` in deterministic encounter order, with one object per reason-bearing
location:

```json
{"item_id":"...","node_id":null,"reasons":["..."]}
```

- For every item with warnings, add item warning codes in their original order.
- For each move node whose status is not `valid` or whose warnings are non-empty, add one node
  entry. Reasons are `move_<status>` first when status is not valid, followed by warning codes;
  remove duplicates while preserving first occurrence.
- For each unresolved item, ensure its `reason_code` appears in that item's queue entry; merge it
  with item-warning reasons rather than adding a second entry.
- After items, add every package diagnostic with severity `warning` or `error` as a queue entry
  using its nullable `item_id`/`node_id` and reason `diagnostic_<code>`. Info diagnostics do not
  enter the queue. Do not merge diagnostics with earlier entries.

### Public sample and golden projection

The sample package must be synthetic/non-copyrighted, Schema-valid, Pydantic-valid and already
locally normalized. Use fixed IDs/timestamps and source page range 319..399 with opaque
`source_ref="sample://opening-book/chapter-8"`. It must include in reading order all five item
kinds, both prose anchor kinds plus one narrative prose item, at least one source-ordered legal
move sequence with a variation, one retained invalid move node with a validator warning, one
chessboard figure, one unresolved item, item warnings, info/warning diagnostics, evidence with
page/bbox/offset/hash variants, confidence, NAG and namespaced extensions. Use short invented text;
do not copy book prose. All `valid` nodes must contain correct canonical SAN/UCI/six-field FEN.

The checked-in reader JSON is the exact stdout golden projection of that sample. It must contain
all item IDs in source order and review entries for the retained invalid node, unresolved item,
item warning and warning diagnostic. Re-running the consumer must be byte-for-byte stable.

### Codex-frozen ChessWorkbench mapping plan

Write `docs/architecture/ccef-chess-workbench-mapping.md` as a design-only plan, clearly stating
that no adapter/API/SQL write exists yet. It must contain all of these decisions:

1. **Preconditions and ownership:** input is the immutable raw CCEF plus the separately stored
   locally normalized CCEF; only a human-approved revision may enter a later ConsumerAdapter.
   `package_id` and `source_ref` are never reused as SQL IDs; `source_ref` is resolved by the Stage
   8 caller, not parsed as a path/URL/UUID. Mapping is one-way and never mutates either package.
2. **Evidence:** deduplicate each full `EvidenceRef` tuple. Page/bbox can map to `PageSpan`; current
   `SourceSpan` cannot losslessly represent simultaneous page+text offsets or
   `fragment_sha256`, so the immutable candidate/receipt must retain the original evidence and
   publication must not claim those fields were transferred. This is an explicit Stage 8A/8D
   persistence-design blocker, not permission to discard them.
3. **Ordered items:** CCEF item order becomes block order only after review. `heading` maps to
   `section_header`; headings over the current 200-character internal limit block publication
   until edited—never truncate. Unanchored prose maps to `narrative`; plain text needs a defined
   literal-to-Markdown escaping step before implementation, while Markdown remains sanitized by
   the existing renderer.
4. **Moves:** a `move_sequence` creates one `move_sequence` block and one root occurrence from its
   initial position. Process nodes in topology order; `parent_id` resolves only inside that
   sequence; `sibling_order` maps to occurrence `sort_order`; persisted moves use `uci_candidate`
   and are revalidated by the existing python-chess service. Compare persisted full FEN with CCEF
   `fen_after`; mismatch aborts the whole publish transaction. A sequence cannot publish while an
   included node is not `valid`; excluding/fixing a branch must be an explicit audited human edit.
5. **NAG mismatch:** CCEF permits an ordered list but `CourseOccurrence` stores one NAG. Zero or one
   maps losslessly; multiple NAGs block publication until the internal model is extended or the
   reviewer explicitly chooses one. Never silently take the first.
6. **Anchored prose:** a `move_node` anchor maps to a course-scoped draft `KnowledgeNote` targeting
   that node's occurrence plus a `knowledge_note` block. A position anchor maps automatically only
   when exactly one occurrence in the candidate module has the same validated full position;
   zero or multiple matches require human selection. Unanchored prose never becomes a
   KnowledgeNote.
7. **Figures/unresolved:** a chessboard figure is extraction/review evidence and is not copied into
   the final Block stream after its position is resolved. Non-chess figures have no current lossless
   Block target and block publication unless explicitly rejected or a later media block is added.
   Every unresolved item and every error diagnostic blocks publication; neither may be dropped.
8. **Atomicity/idempotency:** later publication creates SourceSpan/occurrences/notes/blocks in one
   transaction with a durable receipt keyed by consumer-owned source/version plus canonical CCEF
   hash and mapping version. Replay returns the prior result; any validation/conflict/write error
   produces zero formal partial writes. Exact receipt/schema design belongs to 8A/8D.
9. **Stage boundary/checklist:** explicitly assign immutable source/raw CCEF/receipt storage to 8A,
   OCR fragments to 8B, provider execution and candidate validation to 8C, and review plus atomic
   mapping to 8D. List the four current blockers: evidence offset/hash fidelity, multiple NAGs,
   position-anchor occurrence selection, and non-chess figures/heading length/plain-text escaping.

The plan may cite ADRs and current classes, but must not invent API routes, tables, migrations or
claim the adapter is implemented.

### Preserved invariants

- The example consumes only the published Schema/package boundary and owns its separate reader
  projection; it does not import or expose ChessWorkbench domain concepts.
- Schema validation proves portable shape, while ADR 0010/ccef-v1 and the producer remain
  authoritative for cross-reference/tree/chess invariants that JSON Schema does not encode.
- Unknown/unresolved/invalid content remains visible and reviewable; no silent loss or automatic
  formal publication.
- No production extraction change, provider/network call, PDF/OCR, SQL, API, job, UI, actual
  ConsumerAdapter, quality-gate reduction or commit.

### Required focused tests

Cover at least:

1. checked-in Schema passes `Draft202012Validator.check_schema`; sample passes Schema plus
   `ExtractionPackage.model_validate`, and `normalize_chess_moves(sample)` is value-identical;
2. `python -I` CLI succeeds with no stderr and its stdout is byte-identical to the golden file;
3. projection keeps all item IDs/kinds/order, both anchor shapes, tree parent/order, canonical move
   fields, evidence/defaults/extensions and leaves its input unchanged;
4. exact review-queue ordering, merge/dedup behavior, invalid/unresolved/item-warning and
   warning/error diagnostic handling; info diagnostics excluded;
5. invalid JSON, list/scalar top levels, wrong Schema dialect/ID, invalid Schema, unknown package
   field, unsupported version and bad UUID/date-time format return 2 with only the fixed stderr;
6. direct unknown-kind call raises `ValueError`; expected loader errors are contained while one
   injected `KeyboardInterrupt`/`MemoryError` path propagates;
7. AST/subprocess import proof that the example has only the allowed imports and that
   `chess_workbench`, Pydantic, chess, httpx, Sanic, SQLAlchemy/store/services/jobs/config are absent
   from `sys.modules` after the isolated success run;
8. mapping document contains every required target, blocker, atomicity/idempotency rule and the
   explicit `no implementation/no SQL write` boundary.

### Acceptance commands

```bash
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_validation.py backend/tests/test_ccef_consumer_proof.py
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff format --config backend/pyproject.toml --check \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked ruff check --config backend/pyproject.toml \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked mypy --config-file backend/pyproject.toml \
  examples/ccef_consumer/consumer.py backend/tests/test_ccef_consumer_proof.py
git diff --check
git diff --stat
```

Do not run cumulative Stage 8, backend coverage, frontend or whole-repository acceptance during
this packet.

### Escalation and review

Risk tier: **medium** after Codex froze the external projection and internal mapping plan. Stop
without guessing if Draft 2020-12 validation cannot run offline, the sample cannot satisfy both
the Schema and Pydantic/runtime contract, an exact mapping rule conflicts with current models, a
dependency/interface change is needed, or any file outside the permitted boundary must be edited.
Report `pending Codex review`; do not start the final 8P boundary review/8A and do not commit.

### Final Codex review (2026-08-11)

**Accepted after one Codex-owned security correction.** Independent review found that the first
implementation claimed offline-only validation without rejecting non-fragment JSON Schema
references. The consumer now recursively rejects external `$ref`, `$dynamicRef` and
`$recursiveRef` values before constructing the validator. A regression test replaces validator
construction with a sentinel and proves all three forms are rejected first.

Independent focused verification:

```text
pytest contract + decoder + validation + consumer proof → 173 passed
  (43 contract + 61 decoder + 39 validation + 30 consumer proof)
python -I consumer output vs checked-in golden          → byte-identical
configured Ruff format/check and MyPy                   → clean
git diff --check                                        → clean
```

The standalone consumer remains independent of ChessWorkbench and production extraction code;
the sample is synthetic, all rejected content remains reviewable, and the mapping document is
design-only. No SQL/API/job/UI work, live provider call, full acceptance run or commit was made.
The next unit is the Codex feature-boundary review of all 8P deliverables; 8A has not started.

## Completed packet: DS-STAGE8-CHESS-NORMALIZER-01 (8P-4B)

### Objective

Implement the deterministic, provider- and consumer-neutral python-chess pass over CCEF
`move_sequence` items. It reconstructs every source-ordered branch from its declared initial
position, writes authoritative SAN/UCI/before/after FEN only for uniquely legal and context-
consistent nodes, and keeps illegal, ambiguous or disconnected nodes in place with stable review
warnings. It is a pure transformation: no package input mutation and no I/O.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/validation.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (export only)
- `backend/tests/test_extraction_validation.py` (new)
- `docs/agent/HANDOFF.md` (completion evidence only)

Do not edit `contracts.py`, `decoder.py`, `provider.py`, `deepseek.py`, the checked-in JSON Schema,
dependencies, configuration, SQL, jobs, services, routes, migrations, existing tests or any other
file.

### Exact public interface

Add and export exactly:

```python
def normalize_chess_moves(package: ExtractionPackage) -> ExtractionPackage: ...
```

The function accepts any already-valid CCEF package, deep-copies it, deterministically recomputes
every move node from `move_text`, returns a new `ExtractionPackage`, and never mutates the input.
It performs no filesystem, environment, network, clock, randomness or database access and raises
no content-validation exception for bad chess: bad chess remains reviewable in the returned CCEF.

### Initial-position and branch reconstruction policy

- `StartPosition` starts from the standard initial position.
- `FenPosition` is standard chess only. Construct `chess.Board(fen, chess960=False)` and require
  `board.is_valid()`. Reject promoted-piece `~` notation and castling fields other than the
  standard ordered `K?Q?k?q?` form or `-`; do not accept Shredder-FEN castling letters.
- Full canonical FEN output is `board.fen(en_passant="fen")` with six fields. Do not reuse the
  graph's four-field identity or reset clocks.
- The contract already guarantees parent-before-child ordering. A root node uses a copy of the
  initial board; a child uses its parent's successfully normalized after-board. Root siblings are
  independent alternatives. If no unique parent board exists, the node is retained as `invalid`
  with an unresolved-parent warning; do not guess through the gap.

Before evaluating each node, clear its previous `san_candidate`, `uci_candidate`, `fen_before` and
`fen_after` and recompute status; never trust prior provider/consumer normalization fields.

### Move-token policy

Treat `move_text` as the preserved source token but derive one conservative parse token:

1. remove at most one leading decimal move-number prefix in `N.` or `N...` form, allowing spaces
   after it (examples `1.e4`, `1...e5`);
2. repeatedly remove trailing symbolic annotations `!`, `?`, `!!`, `??`, `!?`, `?!` and numeric
   NAG tokens `$0` through `$255`, allowing whitespace between suffixes;
3. strip only whitespace exposed by those removals; reject an empty result;
4. parse with `board.parse_san`. This intentionally accepts python-chess's standard SAN and legal
   coordinate-notation extension, then rewrites it to canonical SAN/UCI. Reject null moves even if
   python-chess parses a null token. Do not remove comments, variations or arbitrary prose.

Catch `chess.AmbiguousMoveError` separately from other invalid/illegal SAN failures. Do not inspect
or expose python-chess exception text.

### Exact node outcomes and warnings

Preserve node IDs, parent/order, raw `move_text`, NAGs, confidence, evidence, extensions and all
unrelated existing warnings. These five warning codes/messages are owned by this validator;
remove any prior warning with one of these codes before recomputing so the function is idempotent,
then append at most one current validator warning using a deep copy of the node evidence:

| Outcome | status | authoritative fields | warning code | exact message |
|---|---|---|---|---|
| sequence initial FEN invalid (root) | `invalid` | all null | `ccef_chess_invalid_initial_position` | `The sequence initial position is not a legal standard-chess FEN.` |
| parent has no unique after-board | `invalid` | all null | `ccef_chess_unresolved_parent` | `The parent move could not be resolved to one position.` |
| parse raises `AmbiguousMoveError` | `ambiguous` | all null | `ccef_chess_ambiguous_move` | `The move text is ambiguous in the reconstructed position.` |
| empty/invalid/illegal/null move | `invalid` | all null | `ccef_chess_invalid_move` | `The move text is not legal in the reconstructed position.` |
| optional `side_to_move` or `move_number` contradicts the reconstructed board | `invalid` | all null | `ccef_chess_context_mismatch` | `The move context conflicts with the reconstructed position.` |
| unique legal move and optional context agrees | `valid` | all four canonical values | none | none |

For an invalid initial position, every root gets `ccef_chess_invalid_initial_position`; descendants
get `ccef_chess_unresolved_parent`. Any `invalid`/`ambiguous` node has no after-board, so all its
descendants are unresolved. Optional context must agree with `w`/`b` from `board.turn` and the
current `board.fullmove_number`; omitted context never blocks validity.

For a valid node, compute SAN before push, lowercase standard UCI from `move.uci()`, `fen_before`
from the reconstructed board and `fen_after` after push. Revalidate the transformed object through
`ExtractionPackage` before returning. All non-move items, item-level fields, package order,
diagnostics, source, provenance and extensions remain value-equal.

### Preserved invariants

- python-chess is the sole chess-rules authority; AI confidence and prior candidate fields never
  make a node valid.
- Illegal, ambiguous, context-conflicting and disconnected source content is retained for human
  review; nothing is silently deleted or promoted.
- The output remains CCEF v1 and contains no Course/Knowledge/SQL/approval/provider-private data.
- No PDF/OCR, HTTP/provider, retry, ConsumerAdapter, job, route, persistence or UI work; no live
  call, new dependency, Schema/quality-gate change or commit.

### Required focused tests

Cover at least:

1. standard-start mainline plus root/child variations reconstruct independently with exact
   canonical SAN, lowercase UCI and before/after FEN; input package is byte/value unchanged;
2. legal custom FEN, castling, promotion, en-passant and python-chess's legal coordinate notation;
3. source-token normalization for `1.e4`, `1...e5`, symbolic suffixes and `$0`/`$255`, while
   comments, arbitrary prose, out-of-range `$256`, empty-after-cleanup and null-move tokens fail;
4. syntactically invalid and position-illegal moves are retained `invalid`; construct a position
   where SAN is genuinely ambiguous and assert `ambiguous`; verify no authoritative fields remain;
5. invalid six-field FEN, structurally illegal board, `~` notation and Shredder-FEN castling are
   retained through root/descendant warnings exactly as specified;
6. side/fullmove context matches and mismatches, including black to move; mismatch blocks the
   whole descendant path;
7. a prior forged `valid` node with wrong normalization is recomputed rather than trusted;
   repeat normalization is value-idempotent and validator warnings do not duplicate, while
   unrelated warnings/evidence/extensions remain value-equal;
8. a package with no move sequence is returned as an equal but distinct deep copy;
9. import-boundary proof: `validation.py` imports only standard library, python-chess and
   `contracts`; no provider/deepseek/httpx, Sanic, SQLAlchemy, store, services, jobs, settings or
   domain-schema imports.

### Acceptance commands

```bash
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_decoder.py \
  backend/tests/test_extraction_validation.py
make backend-format backend-lint backend-typecheck
git diff --check
git diff --stat
```

Do not run cumulative Stage 8, backend coverage or whole-repository acceptance during this packet.

### Escalation and review

Risk tier: **medium** because Codex has frozen every state transition and warning. Stop without
guessing if python-chess behavior contradicts an oracle, the accepted CCEF model cannot represent
an outcome, a dependency/interface change is needed, or any file outside the permitted boundary
must be edited. Report `pending Codex review`; do not start 8P-5 and do not commit.

### Final Codex review status (2026-08-11)

**Accepted; 8P-4 complete.** Codex reviewed the actual state propagation, token cleanup, standard-
FEN checks, warning replacement and deep-copy behavior. An independent adversarial package proved
that a genuinely ambiguous SAN remains `ambiguous`, its child becomes unresolved, the input stays
unchanged and a second normalization is value-idempotent. The exact focused suite passes 143/143
(43 contract + 61 decoder + 39 validation), and backend format/lint/type gates plus
`git diff --check` are clean. No live/paid request or commit was made. 8P-5 has not started and
requires a separate Codex-designed packet.

## Completed packet: DS-STAGE8-CCEF-DECODER-01 (8P-4A)

### Objective

Implement the provider-neutral security boundary that turns one
`StructuredGenerationResponse.content` string into a strict `ExtractionPackage`. This packet owns
JSON syntax, duplicate-key rejection, structural/reference validation through the accepted CCEF
models, truncated-output rejection and the rule that untrusted model output cannot claim a
deterministic chess-validation result. It does not yet parse chess moves; 8P-4B will do that in a
separate packet after Codex review.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/decoder.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (exports only)
- `backend/tests/test_extraction_decoder.py` (new)
- `docs/agent/HANDOFF.md` (completion evidence only)

Do not edit `contracts.py`, `provider.py`, `deepseek.py`, the checked-in JSON Schema, dependencies,
configuration, SQL, jobs, services, routes, migrations, existing tests or any other file.

### Exact public interface

Export these names from `chess_workbench.extraction`:

```python
CcefDecodeErrorCode = Literal[
    "truncated", "invalid_json", "invalid_package", "untrusted_validation"
]

class CcefDecodeError(ValueError):
    code: CcefDecodeErrorCode
    message: str

    def __init__(self, code: CcefDecodeErrorCode, message: str) -> None: ...
    def __str__(self) -> str: ...

def decode_extraction_response(
    response: StructuredGenerationResponse,
) -> ExtractionPackage: ...
```

`CcefDecodeError` accepts only one of the four declared codes and a non-empty actual string
message. Its string form is exactly `message`. It must retain no raw response content or nested
parser/Pydantic exception in public attributes, `args`, `__cause__` or `__context__`.

### Exact decoding policy

1. If `response.finish_reason == "length"`, reject before reading `content` with code `truncated`
   and fixed message `Structured generation was truncated`.
2. Parse exactly one JSON value with the standard library. Reject malformed JSON, non-standard
   constants (`NaN`, `Infinity`, `-Infinity`), duplicate object member names at any nesting depth,
   and a non-object top level with code `invalid_json` and fixed message
   `Structured generation content is not valid JSON`.
3. Before Pydantic validation, inspect every object in top-level `items` whose discriminator is
   `kind="move_sequence"`. Every object in its `nodes` list may omit `validation_status` or set it
   to exactly `"unvalidated"`; `san_candidate`, `uci_candidate`, `fen_before` and `fen_after` may
   be absent or JSON null only. Any non-`unvalidated` status or non-null authoritative field is
   rejected with code `untrusted_validation` and fixed message
   `Provider output may contain only unvalidated move nodes`. Malformed `items`/`nodes` shapes are
   left to ordinary CCEF validation, not guessed or repaired.
4. Validate the object through `ExtractionPackage.model_validate`. Unknown fields, unsupported
   versions, invalid scalar types, page/reference/tree violations and all other CCEF failures map
   to code `invalid_package` and fixed message
   `Structured generation content is not a valid CCEF package`.
5. Return the validated package without mutating `response`; defaults are those already frozen by
   CCEF v1. Do not silently strip Markdown fences, extract a JSON substring, coerce types, repair
   references or rewrite any content.

Parser/Pydantic exceptions may be handled internally, but the public `CcefDecodeError` must be
raised only after leaving the sensitive exception handler so Python exception chaining cannot
retain copyrighted/raw provider content or validation input values.

### Preserved invariants

- The generic provider port and DeepSeek adapter remain CCEF-free and unchanged.
- `contracts.py` and the checked-in Schema remain the only structural/reference contract source.
- Provider output can create only `unvalidated` nodes. Only 8P-4B's local python-chess validator
  may create `valid`, `invalid`, `ambiguous` or authoritative SAN/UCI/FEN fields.
- No chess parsing, PDF/OCR, HTTP, retry, SQL, filesystem ingestion, ConsumerAdapter, job or route
  work; no live/paid call, dependency change, quality-gate reduction or commit.

### Required focused tests

Construct `StructuredGenerationResponse` objects directly; make no network call. Cover at least:

1. a canonical valid package JSON decodes with CCEF defaults and leaves the response unchanged;
2. `finish_reason="length"` wins even when content happens to be valid JSON;
3. malformed JSON, scalar/list top levels, Markdown fences, trailing commentary, every
   non-standard numeric constant and duplicate keys at root/nested levels are `invalid_json`;
4. unknown fields, unsupported version, wrong strict scalar type, dangling reference,
   non-topological/self-parent node and sibling-order gap are `invalid_package`;
5. omitted/explicit `unvalidated` plus absent/null authoritative fields are accepted;
   `valid`, `invalid`, `ambiguous`, unknown status, and each non-null authoritative field are
   `untrusted_validation` even if an otherwise complete `valid` node would satisfy CCEF;
6. all four error codes/messages and constructor validation; raw marker text is absent from
   `str`, `repr`, `args`, attributes, `__cause__` and `__context__`;
7. import-boundary proof: decoder imports only standard library, Pydantic, `contracts` and
   `provider`; it imports no httpx/vendor adapter, Sanic, SQLAlchemy, store, services, jobs,
   settings or domain schema modules.

### Acceptance commands

```bash
UV_CACHE_DIR=.cache/uv UV_PYTHON_INSTALL_DIR=.cache/python \
  uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_contract.py backend/tests/test_extraction_provider.py \
  backend/tests/test_extraction_decoder.py
make backend-format backend-lint backend-typecheck
git diff --check
git diff --stat
```

Do not run cumulative Stage 8, backend coverage or whole-repository acceptance during this packet.

### Escalation and review

Risk tier: **medium** because Codex has frozen the public error and trust-boundary semantics. Stop
without guessing if the existing CCEF models cannot express an accepted case, exception sanitizing
requires changing an earlier module, a new dependency/public field is needed, or any file outside
the permitted boundary must be edited. Report `pending Codex review`; do not start 8P-4B/8P-5 and
do not commit.

### Final Codex review status (2026-08-11)

**Accepted.** The actual decoder diff stays within the frozen boundary. Independent source review
confirmed truncation precedence, all-depth duplicate-key/non-standard-constant rejection,
strict CCEF structural/reference validation, provider-status distrust, response immutability and
sanitized exception detachment. Codex independently reran the three focused files: 131/131 passed.
No live/paid request was made. 8P-4A is complete; 8P-4B is the active packet above.

## Completed packet: DS-STAGE8-DEEPSEEK-ADAPTER-01

### Objective

Implement the first real `StructuredGenerationProvider` adapter for the official DeepSeek OpenAI-
compatible Chat Completions endpoint. It is fixed to `deepseek-v4-flash`, explicitly disables
thinking, requests JSON Object output, injects the caller-owned JSON Schema as a deterministic
system instruction, preserves raw assistant content for the later decoder, and maps transport/API
failures into the provider-neutral error contract.

This packet implements transport only. It performs no live request in tests and does not decode or
validate CCEF.

### Codex-frozen vendor facts and dependency

As of 2026-08-11 the official API documents:

- endpoint `POST https://api.deepseek.com/chat/completions`;
- model `deepseek-v4-flash` (legacy `deepseek-chat` is retired);
- thinking defaults to enabled, so non-thinking requires
  `"thinking": {"type": "disabled"}`;
- JSON Output uses `"response_format": {"type": "json_object"}` and still requires an explicit
  JSON instruction in a system/user message;
- official HTTP statuses include 400, 401, 402, 422, 429, 500 and 503.

Codex has already added the existing locked `httpx>=0.28,<1` package as a direct production
dependency in `backend/pyproject.toml` and refreshed `backend/uv.lock` offline. Those two files are
outside the worker edit boundary and must not be changed by this packet.

### Permitted edit boundary

- `backend/src/chess_workbench/extraction/deepseek.py` (new)
- `backend/src/chess_workbench/extraction/__init__.py` (export only)
- `backend/tests/test_extraction_deepseek.py` (new)
- `docs/agent/HANDOFF.md` (completion evidence only)

Do not edit the provider-neutral models, CCEF contracts/Schema, dependency files, configuration,
environment examples, jobs, SQL, services, routes, migrations, existing tests or any other file.

### Exact public adapter interface

Add `DeepSeekV4FlashProvider` and export it from `chess_workbench.extraction`:

```python
class DeepSeekV4FlashProvider:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 600.0,
        max_output_tokens_limit: int = 128_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None: ...

    async def generate(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResponse: ...
```

Constructor validation:

- `api_key` must be an actual non-whitespace string; trim accepted surrounding whitespace before
  use. Never expose it through `repr`, returned values, errors or HANDOFF/test output.
- `timeout_seconds` must be an actual finite int/float (not bool), in `[1, 1800]`.
- `max_output_tokens_limit` must be an actual int (not bool), in `[1, 384_000]`; this is the
  adapter's per-call output-cost ceiling.
- `transport` is only the httpx test seam. Production defaults to the normal transport.

The class must satisfy `StructuredGenerationProvider` at runtime. Do not add another public model,
settings object, environment lookup, client lifecycle API or retry API.

### Exact request mapping

For every accepted request create a fresh, non-streaming `httpx.AsyncClient` with the configured
timeout/transport and send exactly one POST to the official URL. No automatic retry.

Headers:

- `Authorization: Bearer <trimmed key>`;
- `Accept: application/json` (httpx may add ordinary transport headers);
- JSON request content type through `json=`.

Payload fields owned by the adapter:

```json
{
  "model": "deepseek-v4-flash",
  "messages": [],
  "thinking": {"type": "disabled"},
  "response_format": {"type": "json_object"},
  "max_tokens": 1,
  "stream": false
}
```

Prepend exactly one adapter system message before all caller messages. Its content is:

```text
Return exactly one JSON object that conforms to the JSON Schema below. Do not use Markdown fences or add commentary.
Schema name: <response_schema_name>
JSON Schema:
<canonical schema JSON>
```

Canonical schema JSON is `json.dumps(schema, ensure_ascii=False, sort_keys=True,
separators=(",", ":"))`. Then append caller messages unchanged and in their original order. Do not
mutate the request. Do not send the Schema in an invented provider field, use tools/function calls,
temperature, `reasoning_effort`, user IDs or the CCEF package type.

Before network I/O, reject a request whose `max_output_tokens` exceeds
`max_output_tokens_limit` as provider error `invalid_request`, non-retryable, with a sanitized fixed
message.

### Successful response mapping

For a 2xx response, require a JSON object containing:

- non-empty `choices` list whose first item is an object;
- first choice `message` object with non-whitespace string `content`;
- first choice `finish_reason` is one of the official non-streaming values; `stop` and `length`
  map to the provider-neutral response, `insufficient_system_resource` maps to retryable
  `unavailable`, and all other/null values map to `invalid_response`;
- top-level non-whitespace string `model`;
- top-level `usage` object with actual non-negative integer (not bool) `prompt_tokens`,
  `completion_tokens` and `total_tokens`.

Return `StructuredGenerationResponse` with raw `content` preserved verbatim,
`provider="deepseek"`, the returned model, finish reason, and token mapping
`prompt→input`, `completion→output`, `total→total`. Provider-private fields are ignored and never
stored. Raw content `{}` is valid at this layer. Empty/whitespace content, invalid JSON and every
malformed/missing/type-invalid required field map to `invalid_response`, non-retryable, with the
fixed safe message `DeepSeek returned an invalid response`.

Do not parse the assistant content as JSON and do not validate it against the Schema; 8P-4 owns
both operations. Preserve `finish_reason="length"` so the downstream decoder/policy can reject a
truncated candidate with evidence rather than losing the provider fact.

### Error and cancellation mapping

Never include response bodies, provider error text, request content, URL query data or credentials
in public errors. Map only by exception/status with fixed messages:

| condition | code | retryable |
|---|---|---|
| `httpx.TimeoutException`, HTTP 408/504 | `timeout` | true |
| other `httpx.TransportError` | `unavailable` | true |
| HTTP 401/402/403 | `authentication` | false |
| HTTP 429 | `rate_limited` | true |
| HTTP 400/404/409/422 and other 4xx | `invalid_request` | false |
| HTTP 500–599 except 504 | `unavailable` | true |
| other non-2xx | `unknown` | false |

Use concise fixed messages that may include only the numeric HTTP status. Do not call
`response.raise_for_status()` if doing so would leak a provider body through its exception string.
`asyncio.CancelledError`, `KeyboardInterrupt` and other `BaseException` values must propagate.

### Preserved invariants

- `provider.py` remains HTTP/vendor-free and unchanged.
- The caller supplies arbitrary JSON Schema; the adapter never imports CCEF contracts or names.
- API key is constructor-injected only. No environment/config/global secret access.
- Exactly one network attempt; retry/backoff orchestration belongs to a later job policy.
- No live DeepSeek request, API key or paid call in tests.
- No SQL, filesystem source ingestion, PDF/OCR, decoder, ConsumerAdapter, job or route work.
- No quality-gate reduction and no commit.

### Required focused tests

Use `httpx.MockTransport`; handlers must assert the actual URL, method, authorization, JSON content
type and exact payload. Cover at least:

1. successful request mapping with non-ASCII Schema, deterministic injected instruction, unchanged
   caller message order, explicit non-thinking/JSON mode, output bound and no request mutation;
2. successful response mapping with all token fields, provider/model/finish reason and ignored
   private response fields;
3. literal `{}` content accepted, while empty/whitespace content is `invalid_response`;
4. invalid top-level JSON and missing/wrong-type choices/message/content/model/finish_reason/usage or
   bool/negative token counts are `invalid_response`;
5. timeout and generic transport failure mappings, plus cancellation propagation;
6. every HTTP mapping row, with a secret/provider-body marker proving public errors do not leak;
7. constructor validation, trimmed key use, safe repr and output limit rejection before transport;
8. runtime Protocol conformance and proof the new module imports no CCEF, SQLAlchemy, Sanic, store,
   services, jobs or environment/settings modules.

### Acceptance commands

```bash
uv run --project backend --locked pytest -c backend/pyproject.toml -o addopts='' \
  backend/tests/test_extraction_provider.py backend/tests/test_extraction_deepseek.py
make backend-format backend-lint backend-typecheck
git diff --check
git diff --stat
```

Do not run cumulative Stage 8, backend coverage or whole-repository acceptance during this packet.

### Escalation and review

Risk tier: **medium** after Codex has frozen the vendor mapping. Stop without guessing if the
official request cannot be represented exactly, `httpx.MockTransport` cannot cover a required
case, an interface/dependency change is needed, or any file outside the permitted boundary must be
edited. Report `pending Codex review`; do not start 8P-4 and do not commit.

### Final Codex review status (2026-08-11)

**Accepted.** The exact request, explicit non-thinking mode, deterministic Schema instruction,
output-cost ceiling, strict response mapping, cancellation behavior and status table pass
independent review. Codex found and fixed one security blocker after the worker completed: chained
httpx/JSON/Pydantic exceptions retained the Authorization header or raw provider document through
`__cause__`/`__context__`. Mapped public errors are now raised only after leaving the sensitive
exception handler, and regressions prove those exception links are absent.

The provider/deepseek focused suite passes 108/108, configured backend format/lint/type gates are
clean, and an independent runtime adversarial check confirms neither API key nor malformed raw body
is reachable through the public error. No live or paid DeepSeek request was made. 8P-3 is complete;
8P-4 has not started and requires a separate Codex-designed packet.

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
   - optional provider-neutral `finish_reason: Literal["stop", "length"]`; adapters normalize
     complete output to `stop`, output-limit truncation to `length`, and map other vendor stop
     conditions to provider errors;
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
