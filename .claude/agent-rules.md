# Rules for every Ops AI agent

Every agent in `.claude/agents/` reads this file first, then `.claude/workspace.local.md` if it exists. This file
holds what is true for anyone working on Ops AI. `workspace.local.md` holds what is true for one machine or team: where
design pages and test results live, which shared stack not to touch, and any extra rules. Copy
`.claude/workspace.example.md` to start one; it is ignored by git.

Paths below are relative to the root of the Ops AI repository. In a git worktree, files ignored by git (such as
`workspace.local.md`) live in the main checkout: the first path printed by `git worktree list`.

## Working

| Rule | Why |
|---|---|
| Keep each tool call under 2 minutes; run tests, builds and stacks in the background and poll | Long calls stall the agent and the run is lost |
| Commit after each slice that passes its own tests, one concern per commit | Uncommitted work is lost when an agent stops |
| Work in your own git worktree on your own branch (`<type>/<scope>-<what-changed>`), cut from `origin/main`; run `pnpm install`, the SDK build and `uv sync` there before the first commit | The commit hook needs them; other checkouts belong to other people |
| Never `git stash`, `--no-verify`, force push, or push to main | Other work lives in shared trees; main is protected |
| Open a pull request only when the person who briefed you says so; push the branch | They decide when a change is ready for review |
| Run your own stack on a port offset (`OPS_PORT_OFFSET=<n>`) and stop it when done. Never restart, reset or write to a shared stack (`workspace.local.md` names it) | A shared stack holds other people's data |
| Stop processes by pid only | Name matches stop other people's processes |
| Use a headless browser for tests, never a person's own browser | A person's browser holds live sessions |
| Never print secrets or `.env` files; read single keys by name. Never type a live secret into a field | Secrets in logs and transcripts leak |
| Real model calls: at most 10 per experiment | Cost |

## Everything you write is public

Code, comments, docs, commits, branches, pull requests, fixtures, sample data, mocks, screenshots and logs all follow
"Everything here is public" in `CONTRIBUTING.md`: a neutral, factual tone; no real customers, people or internal
names; fictional sample data from several industries; no secrets; security issues described only once fixed. The
commit hook also enforces a subject under 72 characters, a 1–2 sentence description and a `Changelog:` trailer for a
feat or fix under `apps/` or `services/`.

## Done means

| Layer | Proof |
|---|---|
| API | The change's use case at the api layer passes on a stack (`make usecase-test UC=<id> LAYER=api`) |
| SDKs | The same use case through the Python and TypeScript SDKs |
| UI | The ui use case passes, plus headless screenshots as an admin and a member at 1440 and 390 wide, saved in the evidence folder `workspace.local.md` names (default `docs/test-results/<topic>/`) |
| Tests | One test per failure mode, each watched failing once with the fix reverted, and that failure stated |
| Docs | README and `docs/` updated in the same change |

A report states what ran and what it printed, per layer, and names anything not run. A passing typecheck alone is not
done.

## What a design or code review reads

| Area | Read |
|---|---|
| Architecture | `docs/architecture/`: `service-map.md`, `dependencies.md`, `identity-and-tenancy.md`, `roles-and-permissions.md`, `tool-lifecycle.md`, `definitions-and-versions.md`, `durability-failure-and-audit.md`, `data.md`, `api.md`, `words-and-entities.md`, and `decisions/` |
| A service | `docs/services/<name>/` |
| Plugins | `docs/guide/plugins.md` |
| Screens | the console's components (`apps/console/src/components/shared`, `components/ui`) and the UX specs `workspace.local.md` lists |
| Earlier designs | the design folder `workspace.local.md` names (default `docs/design/`) |
| Project rules | the rulebook `workspace.local.md` names, if any |

Every finding names the rule or document behind it and the code (file:line). A finding no written rule covers is
listed apart, so a rule can be added.
