---
name: delegate-deepcode
description: Delegate an already-designed, bounded repository task from Codex to the local DeepCode CLI, wait for its completion notification, and then independently review the resulting diff. Use only when PLANS.md contains an exact V4-Flash packet with a permitted edit boundary, invariants, deterministic acceptance commands, and escalation rules. Do not use for architecture, ambiguous requirements, public interfaces, database or protocol design, security decisions, unclear cross-module bugs, or when running inside an existing delegated DeepCode process.
---

# Delegate to DeepCode

Keep Codex as the sole controller. DeepCode is an implementation worker, not a peer agent and not
an authority for accepting its own work. The user should never need to copy messages between the
two tools.

## Eligibility gate

Delegate only when all of these are true:

- `PLANS.md` has one named packet for the task.
- The packet states the exact behavior, permitted files, preserved invariants, focused tests and
  escalation conditions.
- The work is small and mechanically reviewable, normally within one implementation module plus
  its tests.
- A deterministic acceptance oracle already exists.
- `git status --short` has been inspected and existing user changes can be preserved.

Codex must implement the task itself when the root cause is unclear, the change designs a public
interface or architecture, the task crosses unrelated modules, or a failed worker attempt needs
substantial diagnosis. Never invoke this skill when `DEEP_AGENT_RUN_ID` is present; that would
recursively delegate from DeepCode.

## Run the worker

From the repository root, start the launcher with the exact packet ID:

```bash
python3 .agents/skills/delegate-deepcode/scripts/delegate.py \
  --packet DS-EXAMPLE-01 \
  --timeout-seconds 1800
```

The launcher:

1. verifies that the packet exists in `PLANS.md`;
2. takes an exclusive project lock so two delegated workers cannot edit the worktree together;
3. starts the installed DeepCode CLI inside a project-scoped tmux private PTY because DeepCode
   0.1.34 rejects non-TTY stdin and its advertised `--prompt` launch path is unreliable;
4. stores the prompt, baseline Git state, terminal transcript and result under the ignored
   `.agent-sync/runs/<run-id>/` directory;
5. waits for `.deepcode/settings.json` to invoke `notify.py` at completion;
6. prints a small JSON summary containing the result path and exits nonzero on failure or timeout.

Use an execution call that yields within ten seconds. If it is still running, poll its session at
intervals shorter than sixty seconds so the user continues to receive progress updates. Do not
launch another DeepCode instance while the delegated run holds the lock.

The managed execution environment may require an escalated command because tmux creates a Unix
socket and the DeepCode model process needs network access. This does not broaden the worker's
project permissions in `.deepcode/settings.json`: destructive actions, Git-history mutation,
out-of-workspace access, tool network and MCP remain denied.

## Interpret completion

Read the `result_path` printed by the launcher. Treat the worker's body as a report, not proof.

- `completed`: inspect the actual diff, verify every changed path is permitted, run the focused
  acceptance commands independently, and look for missing negative cases or weakened assertions.
- `failed`: inspect the result and terminal transcript. If the task packet was incomplete, Codex
  corrects the design. If the bug is still small and understood, Codex may issue one correction
  packet. Otherwise Codex takes over.
- `timeout` or missing notification: terminate the worker, inspect the recoverable worktree and
  transcript, then diagnose locally. Do not blindly resume the same session.

If the same attempted correction fails twice, or a new failure appears outside the packet's edit
boundary, Codex must take over according to `AGENTS.md`.

## Review and handoff

After independent review:

1. fix any complex or cross-boundary issue directly as Codex;
2. update `PLANS.md` and `docs/agent/HANDOFF.md` with the accepted status or next bounded packet;
3. report files changed, focused commands and remaining risks to the user;
4. never commit, reset, rebase or delete user work without explicit permission.

The Git worktree, `PLANS.md` and `docs/agent/HANDOFF.md` remain the durable shared memory. Runtime
files in `.agent-sync/` are only transport and diagnostics; they are not project truth.
