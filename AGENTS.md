# AGENTS.md

## Project overview

ChessWorkbench is a single-user, local-first chess knowledge workbench for organizing
theory, interactive training, game review, and AI-assisted content import. The internal
model is a position graph (not a PGN tree), and the system enforces a strict four-layer
separation: Source → Knowledge → Repertoire → Exercise.

Current phase: the operator accepted the v8/v9 PDF extraction and review workflow for personal use on 2026-10-01. PDF work is now maintenance driven by concrete user failures; R5/P6 broad evaluation and remaining Stage 8D-7 scope are deferred pending roadmap reprioritization.
See `PLANS.md` for current tasks and `docs/development-plan.md` for the full roadmap.

## Repository layout

```
chess-workbench/
├── AGENTS.md              ← this file
├── PLANS.md               ← current task plan
├── Makefile               ← local development and verification commands
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

1. During an iterative single-task change, run only the smallest formatter, type checker and test
   selection that directly exercises the changed behavior. Do not run full suites, smoke or
   unrelated checks merely for reassurance. Run broader local checks only when they address a
   concrete risk or the user requests them.
2. This is primarily a personal, local-first site. During feature discovery, prove the concrete
   user-visible or artifact-level outcome before expanding defensive coverage. Test volume must be
   proportional to the implementation and actual risk: prefer one focused regression for a bug or
   critical persisted-data invariant, and do not build exhaustive combinatorial or cross-dialect
   proof suites merely to anticipate hypothetical future failures. It is acceptable to fix
   non-critical product bugs as they are encountered. Broader coverage checks are
   optional full checks, not an iterative development ritual.
3. Review `git diff --stat` for unintended changes.
4. Update `docs/agent/HANDOFF.md`.
5. Summarize: files changed, tests run and results, failures, assumptions, remaining risks.
6. Do **not** commit, rebase, reset, or delete files without explicit permission.

## Personal-project implementation scale

The operator explicitly requires a practical single-user website, not exhaustive defensive
engineering. These rules govern new work and the interpretation of historical task packets:

- Deliver a visible behavior or inspectable artifact before expanding infrastructure or coverage.
  Fix observed problems; non-critical gaps may be recorded for later work.
- Validate at external-input, chess-authority and persistence/publication boundaries. Do not repeat
  full schema, hash or graph validation between internal functions that already receive validated
  values, unless a relevant transformation or trust-boundary crossing requires it.
- Preserve source fidelity, legal persisted moves, immutable history and human approval. Treat
  extraction ambiguity as a localized review issue where possible, not another whole-run blocker.
- Prefer straightforward functions, small typed models and the existing sequential worker. Do not
  introduce generic workflow/repair frameworks, plugin registries, multiple model fallback chains
  or hypothetical compatibility layers without a concrete current need.
- Develop by user-visible slices, not one approval/test packet per tiny function or type. A slice
  may include related files needed to deliver the behavior; it need not prove global completeness.
- A focused regression is the default for a bug; add integration coverage when an actual persisted
  invariant changes. Documentation and reversible low-impact presentation changes do not require
  new tests. Avoid tests that mirror the implementation and combinatorial defensive matrices.
- Use three verification levels: local checks while editing; owning tests when a slice is complete;
  broader local coverage checks at closeout or when genuinely affected. Existing coverage floors
  remain unchanged. Do not run global coverage or unrelated database-dialect
  suites after every small change, and do not weaken gates to hide failures.
- Human comparison of a real source PDF and extracted output is valid semantic acceptance evidence.
  It complements focused automated regressions; it is not restricted to visual styling or wording.
- Once relevant checks pass, proceed. Broaden or repeat only for new edits, failures or a concrete
  unresolved concern. Report product outcomes and remaining limitations, not test count as progress.

PDF redesign scope and delivery slices: [ADR 0022](docs/decisions/0022-source-first-pdf-extraction-redesign.md) and [R1–R5 status](docs/agent/pdf-extraction-r1-r5-implementation-2026-09-27.md).
The deferred P6 evaluation inventory is historical. Do not resume it automatically.

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
21. Automated tests use fixtures; do not make real paid or external API calls.
22. Tests must be deterministic; random/property tests must print and fix their seed.

## Agent work

All subsequent repository work is performed by Codex unless the operator explicitly changes this decision. Historical DeepCode delegation instructions are archived. Coordinate through Git, the short current plan, the short handoff and ADRs. No agent commits without explicit authorization.
