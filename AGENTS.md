# AGENTS.md

## Project overview

ChessWorkbench is a single-user, local-first chess knowledge workbench for organizing
theory, interactive training, game review, and AI-assisted content import. The internal
model is a position graph (not a PGN tree), and the system enforces a strict four-layer
separation: Source → Knowledge → Repertoire → Exercise.

Current phase: Stage 8P portable AI-extraction contract after accepted Stage 6.
See `PLANS.md` for current tasks and `docs/development-plan.md` for the full roadmap.

## Repository layout

```
chess-workbench/
├── AGENTS.md              ← this file
├── PLANS.md               ← current task plan
├── Makefile               ← single entry-point for all verification
├── README.md
├── frontend/
│   └── src/
│       ├── app/            ← router shell, layouts
│       ├── components/     ← shared presentational components
│       ├── logic/api/      ← HTTP client + generated API types
│       ├── types/          ← OpenAPI-generated TypeScript types
│       └── test/           ← Vitest setup
├── backend/
│   ├── src/chess_workbench/
│   │   ├── api/            ← Sanic routes, middleware, error handling
│   │   ├── domain/         ← chess rules, position identity (no HTTP deps)
│   │   ├── schemas/        ← Pydantic API contracts
│   │   ├── services/       ← application logic
│   │   └── store/          ← SQLAlchemy models, repositories, migrations
│   ├── migrations/         ← Alembic migrations
│   └── tests/
├── docs/
│   ├── agent/HANDOFF.md    ← short-term handoff state
│   ├── decisions/          ← Architecture Decision Records
│   ├── chess-workbench-project-description.md
│   └── development-plan.md
├── scripts/                ← codegen, coverage checks, smoke test
├── data/                   ← runtime SQLite, sources, engines (gitignored)
└── .agents/skills/         ← shared agent skills
```

## Required workflow

### Before editing

1. Run `git status --short`.
2. Read `PLANS.md` and `docs/agent/HANDOFF.md`.
3. Read the relevant ADR in `docs/decisions/` if touching architecture-sensitive code.
4. Inspect the relevant implementation and existing tests.
5. Do not assume another agent's uncommitted edits are complete or correct.

### After editing

1. Run the relevant formatter, type checker, and tests (see Commands below).
2. Review `git diff --stat` for unintended changes.
3. Update `docs/agent/HANDOFF.md`.
4. Summarize: files changed, tests run and results, failures, assumptions, remaining risks.
5. Do **not** commit, rebase, reset, or delete files without explicit permission.

## Commands

All commands run from the repository root.

| Action | Command |
|--------|---------|
| Install all dependencies | `make bootstrap` |
| Format (backend) | `make backend-format` |
| Lint (backend) | `make backend-lint` |
| Type check (backend) | `make backend-typecheck` |
| Backend tests + coverage | `make backend-test` |
| Backend full check | `make backend-check` |
| Format (frontend) | `make frontend-format` |
| Lint (frontend) | `make frontend-lint` |
| Type check (frontend) | `make frontend-typecheck` |
| Frontend tests | `make frontend-test` |
| Frontend build | `make frontend-build` |
| Frontend full check | `make frontend-check` |
| Regenerate OpenAPI + TS types | `make contracts` |
| Check contract drift | `make check-contracts` |
| Full verify (all checks) | `make verify` |
| Smoke test (start services) | `make smoke` |
| Stage 2A acceptance | `make acceptance-stage-2a` |
| Stage 2B acceptance | `make acceptance-stage-2b` |
| Stage 2C acceptance | `make acceptance-stage-2c` |
| Stage 2D acceptance | `make acceptance-stage-2d` |
| Full Stage 2 acceptance | `make acceptance-stage-2` |
| Stage 3A acceptance | `make acceptance-stage-3a` |
| Stage 3B acceptance | `make acceptance-stage-3b` |
| Stage 3C acceptance | `make acceptance-stage-3c` |
| Stage 3D acceptance | `make acceptance-stage-3d` |
| Full Stage 3 acceptance | `make acceptance-stage-3` |
| CI entry point | `make acceptance` |

## Engineering rules

1. Do not introduce unapproved large frameworks.
2. Do not add distributed architecture ahead of schedule.
3. Authoritative data is written only through the backend SQL API.
4. Frontend `chess.js` is for instant interaction only; all persisted moves must be validated
   by `python-chess`.
5. PGN is an import/export format, not the internal model. The internal model is the
   Position/MoveEdge graph.
6. AI output must not bypass human review and enter the official knowledge base.
7. WebSocket is for lightweight invalidation notifications only, not as a replacement
   for the HTTP API.
8. Critical domain behavior must have tests.
9. New architectural decisions are written in `docs/decisions/` as ADRs.
10. Do not copy the reducer/ZeroMQ/full-mirror/Remote-ESM pattern from the sibling project.
11. Code must prioritize clarity, readability, and debuggability over abstraction.
12. All API schemas use `extra="forbid"`; never silently ignore unknown fields.
13. Persisted moves use standard lowercase UCI.
14. `position_key` uses `standard:v1:<canonical-fen first 4 fields>` format.
    Halfmove clock and fullmove number are excluded from graph identity.
15. Occurrences carry course-specific context (order, NAG, comments); global edges do not.
16. Source, Knowledge, Repertoire, and Exercise are separate domain layers.
17. Use explicit archiving with reference protection; no hard deletes that cascade
    into shared Position/MoveEdge rows.
18. UTC for all persisted timestamps. UUIDs for all entity IDs.
19. Expected-version optimistic concurrency with `stale_version` error code.
20. Minimum coverage: 80% line / 75% branch; key domain modules at least 90%.
21. No real Lichess/OpenAI calls in PR tests; use fixtures only.
22. Tests must be deterministic; random/property tests must print and fix their seed.

## Agent division

- **Deep Code (DeepSeek-V4-Flash)**: executes small, bounded work after the behavior and acceptance
  oracle are already defined — local code search/explanation, documentation, formatting, type
  fixes, focused unit tests, configuration edits, clear single-module bugs and already-designed
  small features. Default to thinking enabled with `high` effort; non-thinking is only for purely
  mechanical work, and `max` is not the routine default.
- **Codex (OpenAI)**: architecture design, cross-module changes, complex debugging,
  formal verification, security review, final diff review, task planning and scoping,
  ambiguous requirements.

V4-Flash task packets must name the relevant files, invariants that must remain unchanged, exact
acceptance commands and the permitted edit boundary. Prefer one independently verifiable behavior
per packet. Tests and generated contracts may accompany their owning module, but a task that needs
changes across more than two unrelated implementation modules belongs to Codex or must first be
split by Codex.

### Deep Code escalation rules

Deep Code must stop implementation, leave the worktree recoverable and report evidence instead of
guessing when any of the following is true:

- the task requires changing public architecture, an unspecified API/interface, database schema,
  protocol, authentication, authorization or a concurrency/state-machine invariant;
- more than two unrelated implementation modules need modification;
- existing tests contradict the requested behavior or the requested oracle appears incorrect;
- the root cause remains unclear after inspecting the named code and reproducing the failure;
- implementation requires an assumption not stated in the task, a new dependency or a material
  expansion of scope;
- the same attempted fix fails twice, or the focused gate exposes a new failure outside the task
  boundary.

On escalation, report the reproduction, inspected files, best current hypothesis, attempted changes
and exact blocking decision. Do not weaken tests, coverage floors, type checks, lint rules or
warnings-as-errors to obtain a pass.

Low-risk Flash work with a complete deterministic gate may continue without an individual Codex
review when the current task packet explicitly permits it. Batch related medium-risk changes for
one Codex review. High-risk work goes directly to Codex. These review tiers do not grant permission
to commit: no agent commits unless the user explicitly authorizes it.

Work is coordinated through Git, `PLANS.md`, `docs/agent/HANDOFF.md`, and ADRs —
not by sharing raw chat history.

### Codex-led automatic delegation

The user talks only to Codex. When a V4-Flash packet satisfies the rules above, Codex may invoke
the project skill `$delegate-deepcode`; the skill starts DeepCode in a private PTY, waits for its
completion notification and returns control to the same Codex turn. The user does not manually
relay prompts or completion reports.

Codex must inspect the actual diff and independently run the focused oracle before accepting a
delegated result. A DeepCode completion message is evidence, never approval. Ambiguous failures,
architecture or interface decisions, cross-module fixes and a repeated failed correction remain
Codex work. Neither agent may auto-commit.

Runtime transport under `.agent-sync/` is disposable and gitignored. Durable task state remains in
`PLANS.md`, `docs/agent/HANDOFF.md` and Git. A delegated DeepCode process (identified by
`DEEP_AGENT_RUN_ID`) must never invoke `$delegate-deepcode` recursively.
