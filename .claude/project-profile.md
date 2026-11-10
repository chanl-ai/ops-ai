# Project profile: Ops AI

Every fact about this repository that an agent or an agent script needs lives here, once. The agents in
`.claude/agents/` hold only the practice of their job and read this file for the paths, commands, layers and
conventions of Ops AI; `.claude/agent-rules.md` holds the rules every agent follows; `.claude/workspace.local.md`
holds what is true for one machine. To use the agents on another repository, replace this file.

The scripts under `scripts/agents/` read the tables below (`scripts/agents/profile.py`, `profile.mjs`). A table a
script reads keeps its heading and columns; a flag on the command line overrides a row. `OPS_AGENT_PROFILE` names
another profile file. Paths are relative to the repository root.

## Layers

Which files belong to which layer, what a change to them must read, and the gate that checks them. Globs follow
`fnmatch` with `**` crossing folders. The first matching row wins.

| Layer | Paths | Read | Check |
|---|---|---|---|
| tests-python | `services/*/tests/**`, `packages/*/tests/**`, `scripts/tests/**`, `docs/usecases/*/scripts/**` | `CLAUDE.md` "Tests", `docs/usecases/README.md` | `uv run ruff check <files>` |
| tests-console | `apps/*/src/**/*.test.ts`, `packages/*/src/**/*.test.ts` | `apps/console/CLAUDE.md` "Run and check from this folder" | `pnpm --filter @ops-ai/console test` |
| migrations | `services/*/migrations/**`, `deploy/database/**` | `docs/architecture/data.md`, `docs/design/data/sql-server.md`, `docs/deploy/database.md` | `uv run python scripts/check_portable_store.py --strict` |
| service | `services/*/src/**` | `docs/architecture/service-map.md`, `dependencies.md`, `data.md`, `api.md`, `identity-and-tenancy.md`, `roles-and-permissions.md`, `docs/services/<name>/` | `make test PKG=services/<name>` |
| package | `packages/*/src/**` | `packages/CLAUDE.md`, `packages/<name>/CLAUDE.md`, `docs/packages/<name>/` | `make test PKG=packages/<name>` |
| openapi | `services/*/openapi.json` | `docs/architecture/api.md`, `sdk/CLAUDE.md` | `make openapi` then `make sdk-verify` |
| sdk | `sdk/**` | `sdk/CLAUDE.md`, `docs/sdk/` | `make sdk-verify` |
| console | `apps/console/src/**`, `apps/embed/src/**` | `apps/console/CLAUDE.md`, `docs/console/page-plan.md` | `pnpm verify` |
| plugins | `plugins/**`, `packages/ops_plugin_sdk/**` | `docs/guide/plugins.md`, `docs/architecture/tool-lifecycle.md` | `make test PKG=packages/ops_plugin_sdk` |
| deploy | `deploy/**`, `.github/**`, `Makefile`, `make/**` | `deploy/CLAUDE.md`, `docs/architecture/make.md`, `docs/deploy/` | `make verify` |
| docs | `docs/**`, `*.md` | `CONTRIBUTING.md` "Doc standards" | `node scripts/check-docs.mjs` |
| scripts | `scripts/**` | `scripts/CLAUDE.md` | `uv run pytest -q scripts/tests` |
| changelog | `changelog/**`, `roadmap.json` | `CLAUDE.md` "Commits" | `make changelog-verify` |

## Checks a review runs first

The scripts run these before an agent reads anything; a `make` target wraps each script (`make/agents.mk`).

| Check | Command | Fails when |
|---|---|---|
| leak scan | `python3 scripts/leak_scan.py --base <base>` | the change adds a home path, tracker id, session link or a tone word (`config/leak-patterns.txt`) |
| public paths | `node scripts/check-public-paths.mjs <files>` | a tracked file names a path a public checkout does not have |
| docs | `node scripts/check-docs.mjs <files>` | a doc is outside `docs/`, undated, unlisted in `docs/README.md` or has no status line |
| python lint | `uv run ruff check <files>` and `uv run ruff format --check <files>` | ruff finds a lint or format error |
| console standards | `pnpm --filter @ops-ai/console check:standards` | a grep-provable console rule in `apps/console/CLAUDE.md` is broken |
| commit message | `node scripts/commit-message-check.mjs` | the subject or body breaks `CONTRIBUTING.md` "Commit messages" |

## Public surface

What the review-context script lists as new public surface, found on added lines of the diff.

| Surface | Pattern (Python regex on an added line) | Files |
|---|---|---|
| HTTP route | `@(?:router|app|[a-z_]+_router)\.(get|post|put|patch|delete)\(\s*["']([^"']+)` | `services/*/src/**/*.py` |
| Response or request model | `^class\s+(\w+)\((?:[\w.]*BaseModel|[\w.]*Schema)[^)]*\):` | `services/*/src/**/*.py`, `packages/*/src/**/*.py` |
| Migration | `migrations/versions/` | path contains it |
| OpenAPI document | `openapi.json` | path ends with it |
| Console route | `apps/console/src/app/**/page.tsx` | path matches |
| Console contract | `apps/console/src/lib/api/*-contract.ts` | path matches |
| SDK surface | `sdk/python/src/**`, `sdk/typescript/src/**` | path matches, outside `generated` |

## Tests

How tests are laid out and run, per kind of code. The test-audit script mutates only code with a `Tests` folder here.

| Code | Tests | Runner (from the code's folder) | Needs |
|---|---|---|---|
| `services/<name>/src/<module>/**` | `services/<name>/tests/` | `uv run pytest -q -x -p no:cacheprovider` | `OPS_TEST_DATABASE_URL` and `OPS_DATABASE_URL` set to the same throwaway PostgreSQL database, made by `uv run python scripts/test_db.py <url>` (`make test` sets both) |
| `packages/<name>/src/<module>/**` | `packages/<name>/tests/` | `uv run pytest -q -x -p no:cacheprovider` | the same two variables for `ops_store`, `ops_engine` and `ops_checkpointer`; the rest run on SQLite |
| `apps/console/src/lib/<file>.ts` | `apps/console/src/lib/<file>.test.ts` beside it | `node --test <test file>` | nothing |
| `packages/usecase-runner/src/<file>.ts` | `packages/usecase-runner/src/<file>.test.ts` | `node --test <test file>` | nothing |
| `scripts/<file>.py` | `scripts/tests/test_<file>.py` | `uv run pytest -q <test file>` | nothing |
| a use case (`docs/usecases/<service>/scripts/test-uc-NNN-<layer>.*`) | itself | `make usecase-test UC=<id> LAYER=<layer>` | PostgreSQL :5477 (`make db-up`) |

| Test database | Value |
|---|---|
| URL template | `postgresql+asyncpg://ops:ops@localhost:5477/<name>` |
| Name for an audit run | `ops_test_r<pid>_<hex>_audit` (the sweep drops it once the run's pid is gone) |
| Live database, never used by tests | `ops_runtime` |

| Non-vacuous evidence | Where |
|---|---|
| A use case prints `PASS <name>` or `FAIL <name>: <detail>` per check | `docs/usecases/README.md` "A pass needs evidence" |
| Each use case doc names the check that fails when the behaviour breaks | `docs/usecases/README.md` "Every use case names its non-vacuous check" |
| A unit test was seen failing once before it is trusted | `CLAUDE.md` "Tests" |

## Designs, specs and decisions

| Thing | Where | Shape |
|---|---|---|
| A design for a change | `docs/design/<area>/<topic>.md` (areas: workflows, tools, human-tasks, cases, chat, data, research); the workspace may name another folder | the 11 sections of "Every spec has this shape" in `CONTRIBUTING.md`; listed in `docs/README.md` |
| Acceptance criteria and tests | the design's "Acceptance tests" section, plus "Acceptance criteria and tests" added by the test designer | a table: failure mode, layer, use case id, Given/When/Then, what to revert to see it fail |
| Mocks | `docs/design/<area>/images/`, built on the console's compiled stylesheet | PNG or HTML; component named per region in a note outside the screen |
| Architecture pages | `docs/architecture/`: `overview.md`, `service-map.md`, `dependencies.md`, `identity-and-tenancy.md`, `roles-and-permissions.md`, `tool-lifecycle.md`, `definitions-and-versions.md`, `durability-failure-and-audit.md`, `data.md`, `api.md`, `words-and-entities.md`, `make.md` | status line, tables, mermaid diagrams |
| Decision records | `docs/architecture/decisions/`, one ADR per decision, id in the title, every ADR a proposal until a maintainer accepts it | title, status, context, decision, consequences; a change to a decision is a new or superseding ADR, named under a spec's "Open questions" |
| Service and package pages | `docs/services/<name>/overview.md`, `docs/packages/<name>/overview.md` | routes, tables, tests |
| Console page plan and UI standard | `docs/console/page-plan.md`, `apps/console/CLAUDE.md` | every page and what it shows; the components table and the states |
| Use case registry | `docs/usecases/README.md` | the table the runner reads |
| Evidence folder | `docs/usecases/<service>/media/` (committed) or `.logs/agents/` (ignored by git) | screenshots and reports |
| Change notes for people using the console | `changelog/<topic>.json` with a `Changelog:` trailer on the commit | `make changelog-verify` |

## Architecture rules the architect checks

| Rule | Owned by |
|---|---|
| One of each thing: one API per resource, one component per pattern, one helper per rule, one source per fact | `CLAUDE.md` "Four rules every change follows" |
| No hard coding: access through `can()` over the roles grid; definitions are database records seeded from files; settings from the settings class | `CLAUDE.md` "Four rules every change follows" |
| Use cases are configuration, never a code path or screen for one use case | `CLAUDE.md` "Four rules every change follows" |
| Layers: `domain` → `app` → `adapters` → `api` inside a service; services → API → SDK → console and CLI across the product; packages never import a service; services never import each other | `CLAUDE.md` "Design in layers", `docs/architecture/service-map.md`, `.importlinter` |
| Every route is authenticated except health and the OpenAPI document | `CONTRIBUTING.md` "Code standards" |
| A service never reads another service's tables; tenancy and team scope on every query | `docs/architecture/identity-and-tenancy.md`, `data.md` |
| Tool calls and model calls go through `tools-service` and `models-service`, the only egress | `CLAUDE.md` "Service map" |
| Runs on PostgreSQL and SQL Server; portable store code only | `docs/design/data/sql-server.md`, `scripts/check_portable_store.py` |
| The engine stays open (ADR-0015); no code treats one engine as settled | `CLAUDE.md` "Architecture" |
| Every release runs on one virtual machine with PostgreSQL and no container runtime | `CLAUDE.md` "Service map" |

## Console

What a browser walk needs. The dev password is the seed's, in the public repository (`packages/ops_service_kit/src/ops_service_kit/settings.py`); it is a placeholder, never a secret.

| Setting | Value |
|---|---|
| Console origin | `http://localhost:3016` (`OPS_CONSOLE_PORT` in `make/env.mk`) |
| Sign-in page | `/login`; fields labelled `Email` and `Password`; the button's name starts with `Sign in` |
| Signed in when | the URL leaves `/login` |
| Loading, error and empty states | `?mock=slow`, `?mock=error`, `?mock=empty` on any route when the console runs on the mock (`pnpm dev`); `?mock=off` resets |
| Widths | 1440 and 390 |
| No-stack path | a ui use case with `withUiStack` from `@ops-ai/usecase-runner/harness` (`docs/usecases/README.md`) |
| Shared components | `apps/console/src/components/shared/`, primitives in `components/ui/` (never edited) |
| Tokens for mocks | the CSS variables in `apps/console/src/app/globals.css` (`docs/console/standards.md`); a mock draws with them or with a screenshot of the real component |

| Role for walks | Email | Password |
|---|---|---|
| admin | `p.shah@harborpine.example` | `northfield-demo` |
| builder | `j.richardson@harborpine.example` | `northfield-demo` |
| approver | `m.okafor@harborpine.example` | `northfield-demo` |
| member | `r.menon@harborpine.example` | `northfield-demo` |
| security admin | `s.adeyemi@harborpine.example` | `northfield-demo` |

## Commands an agent runs

| Task | Command |
|---|---|
| Tests for the files changed since main | `make test` (`scripts/verify-changed.sh`) |
| One package or service | `make test PKG=services/<x> T=tests/<file>` |
| One use case at one layer | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui` |
| Use cases the change touches | `make uc-impacted BASE=origin/main` |
| Everything a commit must pass | `make verify` |
| Regenerate OpenAPI and SDKs | `make openapi` |
| Review context bundle | `make agent-review-context BASE=origin/main` |
| Test audit (static checks and mutation on changed lines) | `make agent-test-audit BASE=origin/main [DESIGN=docs/design/<area>/<topic>.md]` |
| Browser walk of routes as two roles at two widths | `make agent-ui-walk ROUTES="/a /b" [AS=admin,member] [STATES=1]` |
| Commit named files through the hooks | `make commit FILES='…' MSG='type(scope): subject' [CHANGELOG=<topic>]` |

## Conventions

| Convention | Rule | Owned by |
|---|---|---|
| Branch names | `<type>/<scope>-<what-changed>` from `origin/main` | `CONTRIBUTING.md` "Branches and pull requests" |
| Commit messages | `type(scope): subject`, body of at most three lines saying why and what ran | `CONTRIBUTING.md` "Commit messages" |
| Doc file names | kebab-case topics, no dates or numbers; ids in the title | `CONTRIBUTING.md` "Doc standards" |
| Headings | sentence case | `CONTRIBUTING.md` "Writing rules" |
| Sample data | fictional, several industries, `example.com` domains; "Harbor & Pine Bank" only in the console | `CONTRIBUTING.md` "Everything here is public" |
| Copy in the console | product copy, sentence case, buttons say the action, `plural()` for plurals | `apps/console/CLAUDE.md` "Copy" |
| Docstrings | a module docstring; a docstring on every public function, class and route; imperative summary line | `CONTRIBUTING.md` "Code standards" and the architect's documentation practice |
| Calling the stack | the make targets as a seeded person (`make api … AS=<role>`), never an ad-hoc script, SQL or `.env` file | `CLAUDE.md` "Calling the API as a person" |
