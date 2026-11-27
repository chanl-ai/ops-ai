---
name: ops-handback
description: A builder's last step. Stop your own preview, push the branch, confirm the tree is clean, remove your worktree (the branch stays), and pass make agent-handback-check. Use at the end of every build, fix or review that made its own worktree, and before starting work in a new one.
allowed-tools: Bash(make *) Bash(uv run *) Bash(python3 *) Read Grep Glob
---

# ops-handback: push, stop your stack and remove your worktree before handing back

<!-- Generated from `docs/guide/skills/ops-handback.md` by `scripts/agent_skills.py`; change the page, not this file. -->

Make targets: make agent-handback-check, make wt-stop.

## When to use it

You made a worktree for a card, a lane, a fix or a review, and the work in it is pushed or about to be. Every worktree
left behind keeps a checkout, its packages and often a running stack: dozens of them filled the disk and the preview
ports. The agent that made a worktree removes it. A specialist working inside another agent's worktree leaves it to
that agent.

## Where a worktree starts

- Start every new worktree from `origin/develop`:
  `git fetch origin develop` then `git worktree add ../ops-ai-worktrees/<name> -b <branch> origin/develop`.
- The main checkout is the shared local develop. Only the release keeper updates it; never commit, pull or switch
  branches there.
- A review that asks for changes re-creates the worktree from the pushed branch:
  `git worktree add ../ops-ai-worktrees/<name> <branch>`.

## Steps

1. `make wt-stop BRANCH=<branch>` if you started a preview. It stops only that preview's own pids.
2. `git push` the branch (never force, never to develop or main).
3. `git status --porcelain` prints nothing. If it prints files, commit or drop them first. Never stash.
4. From the main checkout: `git worktree remove <path>`. No `--force`, and the branch is not deleted.
5. From the main checkout: `make agent-handback-check BRANCH=<branch>` prints `ok:`. Paste that line in the report.
   It fails while the worktree is still there (dirty, unpushed, or clean and only waiting to be removed), while the
   branch is not on origin or the local branch is ahead, and while the branch's preview still runs.

A throwaway worktree (a reviewer's revert test, a one-off fix) is removed in the same run that pushes or discards it.

## Proof

```bash proof
cd scripts/agents && uv run --no-project --with pytest python -m pytest -q test_handback_check.py
```
