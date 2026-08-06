---
name: project-handoff
description: Prepare or consume a handoff between coding agents (Deep Code ↔ Codex).
---

# Project handoff workflow

## At task start

1. Read `AGENTS.md` at the repository root.
2. Read `PLANS.md` and `docs/agent/HANDOFF.md`.
3. Run `git status --short`.
4. Inspect the latest relevant commits: `git log --oneline -5`.
5. Confirm the exact task boundary before editing.
6. Do not assume another agent's uncommitted edits are complete.

## During implementation

- Keep changes within the assigned scope (see `PLANS.md`).
- Preserve unrelated edits — do not refactor adjacent code.
- Record material architectural decisions in `docs/decisions/`.
- Add or update tests for behavioral changes.
- Match the existing code style and patterns.

## At task completion

1. Run the relevant formatter, linter, type checker, and tests (see `AGENTS.md` Commands).
2. Run `git diff --stat` — verify no unintended changes.
3. Update `docs/agent/HANDOFF.md` with:
   - Files changed
   - Behavior implemented
   - Tests run and their results
   - Assumptions made
   - Unresolved issues
   - Recommended next action
4. Do **not** claim success when verification was not run.
5. Do **not** commit, rebase, reset, install dependencies, or modify files outside
   the repository without explicit permission.

## Agent responsibilities

### Deep Code (DeepSeek-V4-Pro)

- Bounded, well-specified implementation tasks
- Single API endpoints and unit tests
- Type annotations, formatting, config changes
- Documentation updates
- Bug fixes with clear reproduction steps

### Codex (OpenAI)

- Architecture design and cross-module changes
- Complex debugging and root-cause analysis
- Security review and final diff review
- Task planning, scoping, and decomposition
- Handling ambiguous or under-specified requirements

## Shared state

| What | Where | Purpose |
|------|-------|---------|
| Long-term rules | `AGENTS.md` | Stable conventions both agents follow |
| Task plan | `PLANS.md` | Current goal, scope, steps, and criteria |
| Handoff state | `docs/agent/HANDOFF.md` | What the next agent needs to know |
| Architecture decisions | `docs/decisions/` | Irreversible design choices (ADRs) |
| Skills | `.agents/skills/` | Reusable workflows for both agents |
| Code + history | Git repository | Authoritative source of truth |

Chat history is **not** authoritative project state. Do not rely on it across sessions.
