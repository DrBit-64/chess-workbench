# ADR 0021: Bounded structural extraction recovery

- Status: Accepted (operator requested implementation on 2026-09-17)
- Supersedes: ADR 0018 recovery routing only; the existing generic patch authority is unchanged.

## Problem

A complete provider JSON can reference annotations whose bodies were never emitted and omit
existing moves from reading flow. The generic scalar patch cannot add these collections. Sending
such a case to that patch provider spends tokens on an operation the local authority forbids.
The current compatible endpoint also continued reasoning when only `thinking: disabled` was sent.

## Decision

Before paying for a generic patch, classify raw sequence identities and flow coverage. Unknown
move references, duplicate/ambiguous identities and unsupported collection shapes stop explicitly.
Missing annotation bodies and missing references to existing moves/annotations use one dedicated,
hash-bound structural supplement, before the normal validator. The supplement is capped at 64
missing entries across at most eight sequences, 16,384 output tokens and 256 KiB response bytes.

The model selects trusted text fragments (optionally an exact, uniquely occurring excerpt) for
each missing annotation ID, and insertion predecessors for missing flow references. It cannot
generate annotation prose, alter existing nodes, remove/rewrite flow entries or replace existing
annotations. Local code copies source text/evidence and constructs the additions. Existing flow
remains an exact subsequence; existing annotations retain their values and relative order. All
requested gaps must be covered exactly once. Duplicate source spans within the supplement are
rejected. No hidden whole-extraction retry is permitted.

Fragment IDs are enumerated in the request Schema, and node evidence uses the same short IDs.
Each annotation can select at most 64 line fragments; a paragraph may legitimately exceed twelve
PDF text lines. Local validation, not the model's claimed Schema compliance, owns these bounds.

### Local annotation evidence windows (2026-09-17)

Before constructing a provider request, locate each missing annotation between its preceding
and following source-bound flow moves. Forward source intervals are bounded to 64 fragments;
backwards jumps, shared boundary fragments and one-sided anchors use short anchor neighborhoods.
No anchor or an oversized window stops explicitly rather than exposing the entire book as a
fallback. Each model-selected span must belong to that annotation's own window, not merely to
some supplied page. Requests contain the union of pending windows and relevant neighboring nodes.

A sole annotation between two uniquely located score-only boundary fragments may copy the
intervening prose locally when the following node is a direct child, the interval is short and
spans at most adjacent pages, and no other missing/existing annotation competes for that evidence.
Board text and numeric page furniture are excluded, and intervening score lines prevent automatic
assignment. Consecutive annotations, branch transitions and source jumps remain model choices.
Automatic selections retain original flow/node values and are recorded with a localization
algorithm version and fragment IDs in the recovery chain. If they solve every structural gap,
there is no provider call; otherwise the model supplies only unresolved additions.

Full CCEF, evidence, metadata, chess and continuation validation still belongs to the owning
pipeline. After structural supplementation, at most one ordinary scalar patch and one existing
move-coverage supplement may run. Unsupported or failed recovery stops without retry. Successful
artifacts retain the original response and nested deterministic/structural/patch/coverage history;
persisted candidate replay recognizes the structural chain without buying another generation.

Recovery uses its own configured model (optional; defaults to the main model), effort
(`none/low/high/max`, default `none`) and JSON-mode switch. Explicit `none` is sent with disabled
thinking. Empty final content after a length stop reports output-budget exhaustion, including the
reported reasoning-token count when present. Provider failures remain non-retryable at recovery.
The live 512-token synthetic probe with explicit `none` completed using five output tokens.

## Validation

Use synthetic fixtures to prove additive authority, complete gap coverage, no provider call for
unsupported structures, source binding, pipeline callback validation and immutable replay. Use the
saved failed Catalan response for offline diagnosis, never as a production special case or a public
test fixture. Small operator-authorized API probes may validate transport and bounded supplements;
historical failed jobs remain immutable and no runtime SQL is rewritten.
