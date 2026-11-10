# Rules for every Ops AI agent

Every agent in `.claude/agents/` reads this file first, then `.claude/workspace.local.md` if it exists. This file
holds what is true for anyone working on Ops AI and points to where each rule is owned: `CLAUDE.md` for rules a hook
enforces, `CONTRIBUTING.md` for the rest. `workspace.local.md` holds what is true for one machine or team: where
designs and evidence go, whether a task tracker is used, and any extra rules. Copy `.claude/workspace.example.md` to
start one; git ignores the copy, and every setting has a default that works without it.

Paths are relative to the root of the Ops AI repository. In a git worktree, ignored files such as `workspace.local.md`
live in the main checkout: the first path printed by `git worktree list`.

## Which agent for which task

| Task | Agent | Notes |
|---|---|---|
| A change to a screen, an API contract, a data model or a flow across services | `ops-designer`, then `ops-design-reviewer` | Design and acceptance criteria before any code |
| Building an approved design, a bug fix, a docs-only change or plugin work | `ops-builder` | Reads only the spec rows for the files it touches |
| Proving a branch works for people, or a recurring UX check | `ops-qa` | Use cases per layer and headless walks |
| Reviewing a built branch, including a security review | `ops-reviewer` | Security uses the "Security" row of "Everything here is public" and `docs/guide/security-and-governance.md` |

## Working

| Rule | Owned by |
|---|---|
| Keep each tool call under 2 minutes; run tests and builds in the background and poll | here |
| Commit after each slice that passes its own tests; one concern per branch and per commit | `CONTRIBUTING.md` "Branches and pull requests" |
| Work on your own branch (`<type>/<scope>-<what-changed>` from `origin/main`); in a new worktree run `pnpm install`, the SDK build and `uv sync` before the first commit | `CONTRIBUTING.md` |
| No `git stash`, hard resets, `git clean`, `--no-verify`, force pushes or pushes to main | `CLAUDE.md` "Commits" (`scripts/git-rules.py`) |
| Commit messages | `CONTRIBUTING.md` "Commit messages" (`scripts/commit-message-check.mjs`) |
| One stack per machine. Tests and use cases make their own database and services (`make test`, `make usecase-test`), so they need no stack. Never start a second stack. Restart or switch the stack (`make up`, `make review BRANCH=`) only if the workspace allows it | `CLAUDE.md`, `CONTRIBUTING.md` "One stack" |
| Open a pull request only when the person who briefed you says so; push the branch | here |
| Stop processes by pid only; use a headless browser, never a person's own browser | here |
| Never print secrets or `.env` files; read single keys by name; never type a live secret into a field | here |
| Scripted model in tests; real model calls capped at 10 per experiment | `CLAUDE.md` "Tests" |
| One test per failure mode, each seen failing once | `CLAUDE.md` "Tests" |

## Everything you write is public

Code, comments, docs, commits, branches, pull requests, fixtures, sample data, mocks, screenshots and logs follow
"Everything here is public" in `CONTRIBUTING.md`.

## Done means

| Layer | Proof |
|---|---|
| api, sdk, cli, ui | The change's use cases pass at each layer they cover (`make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui`) |
| Screens | Headless screenshots as an admin and a member at 1440 and 390 wide, including the empty, loading and error states (`?mock=empty\|slow\|error`), saved in the evidence folder (default `docs/usecases/<service>/media/`) |
| Tests | The suites of every package changed (`make test`), with each new test seen failing once and that failure stated |
| Docs | README and `docs/` updated in the same change, and every new doc listed in `docs/README.md` |

A report states what ran and what it printed, per layer, and names anything not run. A passing typecheck alone is not
done.

## What a design or code review reads

| Area | Read |
|---|---|
| Architecture | `docs/architecture/`: `service-map.md`, `dependencies.md`, `identity-and-tenancy.md`, `roles-and-permissions.md`, `tool-lifecycle.md`, `definitions-and-versions.md`, `durability-failure-and-audit.md`, `data.md`, `api.md`, `words-and-entities.md`, and `decisions/` |
| A service or package | `docs/services/<name>/`, `docs/packages/<name>/` |
| Plugins | `docs/guide/plugins.md` |
| Screens | `apps/console/CLAUDE.md`, the shared components (`apps/console/src/components/shared`, `components/ui`) and any UX specs the workspace lists |
| Specs | "Doc standards" in `CONTRIBUTING.md`, and earlier designs in `docs/design/<area>/` (or the workspace's design folder) |
| Project rules | the rulebook the workspace names, if any |

Every finding names the rule or document behind it and the code (file:line). A finding no written rule covers is
listed apart, so a rule can be added.

## Task tracker

When the workspace names a tracker, record evidence, hand back and give review verdicts the way its "Tracker" row says.
With no tracker, the report to the person who briefed you is the record.
