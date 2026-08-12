# CCEF → ChessWorkbench one-way mapping plan

Status: **design only. No adapter, API route, table, migration or SQL write exists yet.**

This document freezes the mapping plan from CCEF v1 (ADR 0010, `docs/architecture/ccef-v1.md`)
into the existing ChessWorkbench `Source` / `CourseContentBlock` / `CourseOccurrence` /
`KnowledgeNote` model (ADR 0006). It is the Codex-frozen contract for a future
`ConsumerAdapter`; it does not implement anything. The standalone example consumer
(`examples/ccef_consumer/consumer.py`) and the public fixtures
(`contracts/examples/chess-content-extraction-v1.{sample,reader}.json`) exist only to prove
portability; they contain no ChessWorkbench mapping code.

Every decision below is one-way: mapping never mutates the immutable raw CCEF package or the
separately stored locally normalized CCEF package.

## 1. Preconditions and ownership

- The mapping input is the **immutable raw CCEF** produced by the extraction core plus the
  **separately stored locally normalized CCEF** (the deterministic python-chess pass
  `normalize_chess_moves`). Only a **human-approved revision** may enter a later
  ConsumerAdapter; AI output must never bypass human review (AGENTS.md rule 6).
- `package_id` and `source_ref` are **never reused as SQL IDs**. `source_ref` is an opaque
  consumer-owned string that the Stage 8 caller resolves to the owning `Source`/`SourceVersion`;
  it is **not parsed as a path, URL or UUID** by the adapter.
- Mapping is **one-way and side-effect free on both packages**: no field, warning, diagnostic or
  extension is rewritten, dropped silently or promoted.

## 2. Evidence

- Deduplicate each full `EvidenceRef` tuple `(page, bbox, start_offset, end_offset,
  fragment_sha256)` before creating spans.
- Page + bbox can map to `schemas/domain.PageSpan` (and the stored `SourceSpan` with
  `locator_kind='page'`).
- The current stored `SourceSpan` (locator kinds `whole | page | video | text`) **cannot
  losslessly represent simultaneous page + text offsets** (a `page` span has no offsets; a `text`
  span has no page number) **or `fragment_sha256`** (no such column exists).
- Therefore the immutable candidate/receipt **must retain the original evidence**, and
  publication **must not claim those fields were transferred**. This is an explicit
  **Stage 8A/8D persistence-design blocker**, not permission to discard them.

## 3. Ordered items

- CCEF item order becomes `CourseContentBlock.sort_order` **only after review**.
- `heading` maps to a `section_header` block. The current **200-character internal limit**
  (`CourseContentBlock.heading` is `String(200)`) blocks publication of longer headings until
  they are edited — never truncate.
- Unanchored prose maps to a `narrative` block. Plain text needs a **defined
  literal-to-Markdown escaping step before implementation**; Markdown remains sanitized by the
  existing renderer.

## 4. Moves

- A `move_sequence` creates **one `move_sequence` block and one root `CourseOccurrence`** from its
  `initial_position`.
- Process nodes in topology order; `parent_id` resolves **only inside that sequence**.
- `sibling_order` maps to the occurrence `sort_order`.
- Persisted moves use **`uci_candidate`** and are **revalidated by the existing python-chess
  service**.
- Compare the persisted full FEN with CCEF `fen_after`; a mismatch
  aborts the whole publish transaction. A sequence **cannot publish while an included node is
  not `valid`**; excluding or fixing a branch must be an **explicit audited human edit**.

## 5. NAG mismatch

- CCEF permits an **ordered list** of NAGs; `CourseOccurrence` stores **one** NAG.
- Zero or one NAG maps losslessly.
- **Multiple NAGs block publication** until the internal model is extended or the reviewer
  explicitly chooses one. Never silently take the first.

## 6. Anchored prose

- A `move_node` prose anchor maps to a **course-scoped draft `KnowledgeNote`** targeting that
  node's occurrence plus a `knowledge_note` block.
- A `position` anchor maps automatically **only when exactly one occurrence in the candidate
  module has the same validated full position**; zero or multiple matches require **human
  selection**.
- Unanchored prose never becomes a KnowledgeNote.

## 7. Figures / unresolved

- A `chessboard` figure is **extraction/review evidence only**; it is **not copied into the final
  Block stream** after its position is resolved.
- Non-chess figures have **no current lossless Block target** and block publication unless
  explicitly rejected or a later media block is added.
- **Every unresolved item and every error diagnostic blocks publication; neither may be dropped.**

## 8. Atomicity / idempotency

- Later publication creates SourceSpans, occurrences, notes and blocks **in one transaction** with
  a durable receipt keyed by **consumer-owned source/version + canonical CCEF hash + mapping
  version**.
- Replay returns the prior result; any validation/conflict/write error produces
  zero formal partial writes.
- Exact receipt/schema design belongs to **8A/8D**.

## 9. Stage boundary / checklist

Explicit ownership:

- **8A** — immutable source storage, raw CCEF storage and receipts;
- **8B** — OCR fragments;
- **8C** — provider execution and candidate validation;
- **8D** — review plus the atomic one-way mapping above.

Current blockers (four):

1. evidence offset/hash fidelity (`SourceSpan` cannot hold page + text offsets together or
   `fragment_sha256`);
2. multiple NAGs vs. single-NAG `CourseOccurrence`;
3. position-anchor occurrence selection (unique-match rule);
4. non-chess figures, heading length and plain-text escaping.

None of these blockers is waived; each must be resolved by design before 8D can publish.

## References

- ADR 0010 `docs/decisions/0010-portable-ai-extraction-contract.md` — CCEF v1 architecture.
- ADR 0006 `docs/decisions/0006-chapter-content-block-format.md` — Block stream and span model.
- `docs/architecture/ccef-v1.md` — field-level CCEF contract.
- Current classes cited above: `Source`, `SourceSpan`, `CourseOccurrence`, `CourseContentBlock`,
  `KnowledgeNote` (`backend/src/chess_workbench/store/models/content.py`) and `PageSpan`
  (`backend/src/chess_workbench/schemas/domain.py`).
