# CLAUDE.md

Ops AI is an open design for an operational AI platform for enterprises, plus working code that shows it: a Next.js
console (`apps/console/`) over Python services (`services/`) built on shared libraries (`packages/`), with SDKs and a
CLI (`sdk/`). The console runs on an in-memory mock that the services replace one area at a time. This file is a map:
the rules every change follows, where each folder's guide is, and the shared working rules those guides link to. Read
the guide of the folder you change before changing it.

## Where the rules live

| Source | Decides |
|---|---|
| [Four rules every change follows](#four-rules-every-change-follows) (below) | DRY, no hard coding (`can()` for access), use cases as configuration, layers |
| [AGENTS.md](AGENTS.md) | Rules for every coding agent: verify, fixtures, data flow, branches, secrets, names in code |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branches and pull requests, commit messages, what is public, doc standards and the 11-section spec shape, code standards |
| [.claude/agent-rules.md](.claude/agent-rules.md), [.claude/project-profile.md](.claude/project-profile.md) | Which agent does which stage, what "done" means, the checks a review runs first |
| [docs/architecture/README.md](docs/architecture/README.md) | The current design per area; [service map](docs/architecture/service-map.md) for who owns what |
| [docs/architecture/engineering-standards.md](docs/architecture/engineering-standards.md) | Target state for how code is written: numbered rules per layer with the check that enforces each; a review cites the rule id |
| [docs/architecture/decisions/](docs/architecture/decisions/) | ADRs. Each is a proposal until a maintainer accepts it; ADR-0015 keeps the engine open (Temporal or LangGraph on PostgreSQL), so no code or doc treats one engine as settled. A spec that needs a decision changed proposes a new ADR under "Open questions" |
| [docs/usecases/README.md](docs/usecases/README.md) | The use case registry and the rules every use case follows |

## Four rules every change follows

| Rule | What it means here |
|---|---|
| One of each thing (DRY) | One API per resource, one component per pattern, one helper per rule, one source per fact. Before writing something, find the existing one and use or extend it. |
| No hard coding | Who may do what is decided only by `can()` over the roles grid and team policies, with open defaults: never a check on a role name, an owner, an id prefix or a flag in code. Agents, workflows, tools, skills, guardrails and document types are database records seeded from files, never definitions in code. Settings come from the settings class, and states, kinds and limits are named constants or settings, not literal strings scattered through code. |
| Use cases are configuration | Ops AI must serve thousands of use cases like the levy example. A use case is workflows, document types, agents, tools and settings a builder configures, never a code path, a screen or a field written for one use case. Screens and nodes are generic and read what to show from the step's settings and data; levy is one worked example among several in tests and docs. |
| Design in layers | Inside a service: domain, then app, then adapters, then api, each depending only inward. Across the product: services, then API, then SDK, then console and CLI as thin peers. Subsystems never call each other to act; workflows compose them (`docs/architecture/service-map.md`). Anything that may later live outside us (a vault, models, search) sits behind a port with ours as one adapter. |


## Service map

`services/` holds the deployables, each named after the console section it serves; `packages/` holds the libraries
they share. The table of services with ports, owners and the cross-service rules is in
[services/CLAUDE.md](services/CLAUDE.md); the packages and their rules are in [packages/CLAUDE.md](packages/CLAUDE.md);
the full design is [docs/architecture/service-map.md](docs/architecture/service-map.md).

## Commands

Everything runs from the root `Makefile` (`make help`); each service also has its own (`make -C services/<x> help`).
Every fragment, target and variable: [make/CLAUDE.md](make/CLAUDE.md) and
[docs/architecture/make.md](docs/architecture/make.md).

| Task | Command |
|---|---|
| Install console and Python workspace | `make install` |
| Whole stack in the background (database, every service, worker, console :3016, embed :3020) | `make up`; `make health`; `make logs SVC=<svc> FOLLOW=0`; `make ports` |
| Run someone's branch on the same stack | `make review BRANCH=<name>` |
| Console on the mock, no services | `make dev` (http://localhost:3016; not while `make up` holds :3016) |
| Call a route or drive an area as a seeded person | `make api GET /v1/me AS=viewer`, `make chat …`, `make kb-search …` |
| Tests for what you changed | `make test PKG=services/<x> T=tests/<file>.py`; `make test` runs what changed since `origin/main` |
| One use case | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui` |
| Console gate | `pnpm verify` |
| Everything a commit must pass (CI runs it on every pull request) | `make verify` |
| Regenerate OpenAPI documents and SDKs after a route change | `make openapi`, then `make sdk-verify` |
| Check every guide's links, paths and make targets | `make docs-guides-check` |

Python is one uv workspace at the root (`pyproject.toml`, `uv.lock`) with ruff and strict pyright. Settings use the
`OPS_` prefix and are read only by the settings class in `packages/ops_service_kit`; keys come from the environment or
a gitignored `.env` (contract: `.env.example`). Never commit a `.env`.

## Docs

Full docs live only under `docs/`, in folders that map to the repo; a code folder carries a `README.md` brief of at
most 40 lines and a `CLAUDE.md` for agents. No dates in file names, a status line on every doc, every doc listed in
`docs/README.md`, roles instead of personal names, unconfirmed claims marked **unverified**
(`CONTRIBUTING.md`, "Doc standards"; enforced by `scripts/check-docs.mjs` in `pnpm verify`).

## Working in one folder

A folder's `CLAUDE.md` says what the folder owns and how to run, test and lint it. The rules in this section hold in
every folder, and the folder guides link here instead of repeating them.

### Onion order

A change moves inside out and lands in one change across the layers it touches: service, then its OpenAPI document,
then the SDKs, then the CLI and console, which are thin peers over the SDK. Inside a service the order is `domain` →
`app` → `adapters` → `api`. A lower layer never imports a higher one: packages never import a service, and services
never import each other's code (the departures are listed in [services/CLAUDE.md](services/CLAUDE.md#cross-service-rules)). `.importlinter`
(`uv run lint-imports`) and `services/agents-service/scripts/check_standards.py` enforce part of this.

| Layer | Folder | After changing it |
|---|---|---|
| Service route, DTO or rule | `services/<x>/` | `make test PKG=services/<x> T=tests/<file>` |
| OpenAPI document | `services/<x>/openapi.json` | `make openapi` writes every service's document, then regenerates the SDKs |
| SDKs | `sdk/python`, `sdk/typescript` | `make sdk-verify` (the generated layer matches the documents, both test suites pass) |
| Console | `apps/console/` | `pnpm verify`, then the changed routes in a headless browser |

A screen that needs data the API does not return gets the route first. Counts, joins and totals come from the API,
never from the console.

### One local stack

One stack runs per machine, on fixed ports (`make ports`), from the checkout that last ran `make up`. Its logs, pids
and data live in the main checkout (`.logs/`, `.run/`, `.data/`), which every worktree shares.

| Task | Command |
|---|---|
| Start or bring up to date (migrates, then restarts only what changed) | `make up` |
| Run another branch on the same ports | `make review BRANCH=<name>` |
| Is everything up | `make health` |
| One service's log | `make logs SVC=agents FOLLOW=0` |
| Restart one service, migrating it first | `make restart SVC=tools` |

Never start a second stack or run a service by hand on a port the stack holds. Tests never touch the stack's
database: each run makes a throwaway one (`OPS_TEST_DATABASE_URL`, `scripts/test_db.py`), and a use case starts its
own services on free ports. `make reset-db` and `make up RESET=1` wipe the database every checkout shares. Detail and
gotchas: `docs/architecture/make.md`.

### Calling the API as a person

Test and call the system through the make targets (`api`, `chat`, `kb-*`, `apps-*`, `tools-*`, `runs-*`, `tasks-*`,
`memories-*`, `test-data-clean`), with `AS=` to act as a person, instead of ad-hoc scripts or SQL; read the database
only to diagnose. Every target, variable and the test-data rule:
[make/CLAUDE.md](make/CLAUDE.md#calling-the-api-as-a-person-devmk-climk).

### Tests

| Rule | Detail |
|---|---|
| Run the tests for the files you changed | `make test PKG=packages/<x>` or `PKG=services/<x>`, with `T=tests/<file>.py` naming files (every service Makefile passes it to pytest); `make test` with no `PKG` runs the suites of what changed since `origin/main` and every member that depends on a changed package (`scripts/verify-changed.sh`) |
| Full suites run in CI | `.github/workflows/ci.yml` runs everything `make verify` runs on every pull request; run `make verify` locally to reproduce a CI failure |
| Use cases | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui`; registry and rules in `docs/usecases/README.md` |
| Scripted model | Tests and use cases run on the scripted model with model keys removed; real model calls are capped at 10 per experiment unless a maintainer approves more |
| One test per failure mode | Name the ways the change can break, write one test for each, and watch each new test fail once before trusting it |

### Commits

`pnpm install` in the main checkout installs three hooks from `.githooks/` (`scripts/install-hooks.sh`). Never bypass
them with `--no-verify`. `scripts/git-rules.py`, run as a Claude Code PreToolUse hook on Bash, refuses `git stash`, hard
resets, `git clean`, skipped hooks, force pushes and pushes to `main`; `make git-rules` prints the rules and self-tests
them.

| Hook | Checks |
|---|---|
| `pre-commit` | The gates the staged files need, on an export of the staged content (`scripts/verify-staged.sh`) |
| `commit-msg` | `scripts/commit-message-check.mjs`: `type(scope): subject` of at most 72 characters; a body of at most three lines and 320 characters saying why the old behaviour was wrong and what ran to prove the fix; no first person, narration, history or filler words. Then `scripts/changelog-check.mjs` |
| `pre-push` | ruff check and format on the Python files the pushed commits change |

A `feat` or `fix` commit that changes `apps/` or `services/` carries a `Changelog: <topic>` trailer and stages
`changelog/<topic>.json` in the same commit. The entry is what a person using the console reads under What's new:
`{"date": "YYYY-MM-DD", "title": "…", "description": "…", "tag": "new|improved|fix"}`, a title of at most 60
characters, a description of one or two sentences, and no file paths, file names, ids, commit hashes or first person
(`make changelog-verify` checks every entry).

`make commit FILES='a.py b.md' MSG='fix(tools): fill query placeholders' CHANGELOG=query-placeholders` commits only the
named files through both hooks, from HEAD plus those files; `make whats-mine FILES=…` shows what it would commit, and
`make my-hunks` with `make commit-hunks` commit your hunks of a file others are also editing.

## Folder guides

| Folder | Guide |
|---|---|
| `apps/console/` | `apps/console/CLAUDE.md`: layers, components, states, copy, checks |
| `apps/docs/`, `apps/embed/` | `apps/docs/CLAUDE.md`, `apps/embed/CLAUDE.md` |
| `services/` and each `services/<x>/` | `services/CLAUDE.md`, then the service's own |
| `packages/` and each `packages/<x>/` | `packages/CLAUDE.md`, then the package's own |
| `sdk/` | `sdk/CLAUDE.md`: both SDKs, the generated layer and the CLI |
| `deploy/` | `deploy/CLAUDE.md`, then each target's `README.md` or `CLAUDE.md` |
| `make/` | `make/CLAUDE.md`: the fragments and the API-as-a-person targets |
| `scripts/` | `scripts/CLAUDE.md`: what each group of scripts does and its tests |
| `docs/usecases/` | `docs/usecases/README.md` |
| `examples/` | `examples/CLAUDE.md` |
| `plugins/` | `plugins/README.md`: the install's plugins folder, ignored by git apart from its README |

Folders without a guide of their own:

| Folder | Holds | Change it with |
|---|---|---|
| `changelog/` | One What's new entry per file ([Commits](#commits)) | `make changelog-verify` |
| `roadmap.json` | Coming next items the console shows | `make changelog-verify` |
| `config/` | The leak scan's patterns and baseline (`scripts/leak_scan.py`, `.github/workflows/leak-scan.yml`) | `uv run pytest -q scripts/tests/test_leak_scan.py` |
| `.githooks/` | The three hooks above | `bash scripts/tests/test-verify-staged.sh` |
| `.github/` | CI workflows; `copilot-instructions.md` and `prompts/` are generated from `AGENTS.md`, this file's "Four rules" section and `docs/guide/skills/` | `python3 scripts/agent_skills.py`, then `python3 scripts/agent_skills.py --check` |
| `.devcontainer/` | The development container, running the stack with `OPS_INFRA=external` | `make skills-proof` runs every developer skill in a fresh one |
