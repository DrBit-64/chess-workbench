# AGENTS.md

## Project overview

ChessWorkbench is a single-user, local-first chess knowledge workbench for organizing
theory, interactive training, game review, and AI-assisted content import. The internal
model is a position graph (not a PGN tree), and the system enforces a strict four-layer
separation: Source → Knowledge → Repertoire → Exercise.

Current phase: Stage 2 — position identity, domain model kernel, and core CRUD APIs.
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
| Full Stage 2 acceptance | `make acceptance-stage-2` |
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

- **Deep Code (DeepSeek-V4-Pro)**: bounded, well-specified implementation tasks —
  single API endpoints, unit tests, type annotations, formatting, documentation,
  config changes, simple refactoring, bug fixes with clear repro steps.
- **Codex (OpenAI)**: architecture design, cross-module changes, complex debugging,
  formal verification, security review, final diff review, task planning and scoping,
  ambiguous requirements.

Work is coordinated through Git, `PLANS.md`, `docs/agent/HANDOFF.md`, and ADRs —
not by sharing raw chat history.
