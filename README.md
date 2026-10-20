# Ops AI

Status: current.

Ops AI is an open design and reference implementation for running AI agents and workflows inside a regulated
enterprise, starting with banks. It covers the parts that decide whether such a platform passes a risk review: every
tool call and model call goes through a gateway, people approve sensitive actions, and every version carries its
test evidence. The repository holds three things:

| Part | What it is | State |
|---|---|---|
| Console (`apps/console/`) | A Next.js operations console for a fictional bank, Northfield Bank: agents, workflows, the human review queue, knowledge, tools and governance | Working, on an in-memory mock API |
| Services (`services/`) | Python backend that replaces the mock one area at a time | Runtime prototype working (chat, workflows as graphs, tool gateway); other services planned |
| Design (`docs/`) | Problem statement, architecture, decision records and one spec per topic | Draft for review |

It is for engineers, architects and risk reviewers who are evaluating or building an agent platform for a regulated
environment. Every architecture decision record is a recorded option, not a final decision, until it is confirmed.

## Run it

### Console only (no backend, no credentials)

Needs Node 20 or later and pnpm 10 (`corepack enable` provides it).

```bash
pnpm install
pnpm dev          # http://localhost:3016
```

The console runs on an in-memory mock, so state resets on reload. Add `?mock=slow`, `?mock=error` or `?mock=empty` to
any URL to see loading, error and empty states; `?mock=off` resets.

### Full stack

Needs Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (for PostgreSQL and OPA), Node 20 or later and pnpm 10.
Copy `.env.example` to `.env` and add `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY` with a `claude-*` alias in
`OPS_MODEL_ALIAS`); the key is only needed for real chat. `.env` is gitignored.

```bash
make install      # pnpm install and uv sync, once per clone
make up           # http://localhost:3016 on the real services
make health       # every service, its port and who started it
```

Without a model key every service still starts: `/health` reports the missing key and a chat message returns 503.

### Stack commands

Run from the repository root.

| Command | What it does |
|---|---|
| `make up` | Starts PostgreSQL and OPA, then platform, agents, tools and the console. Restarts any service older than the code, and rebuilds the database when the code changed it |
| `make health` | Shows each service's port, whether it is up, and who started it |
| `make down` | Stops the stack; `KEEP_DB=1` leaves the database running |
| `make restart` | Restarts every service, migrating each first; `SVC=tools` restarts one |
| `make logs SVC=agents` | Follows one service's log; `FOLLOW=0` prints and exits |
| `make ports` | Prints the ports this stack uses |
| `make up AUTH=platform` | Real sign-in through platform-service; sign in as a seeded person with the dev password `northfield-demo` |
| `make up ISOLATED=1` | A second, separate stack on ports +1000 with its own database |
| `make up` again | Migrates your database in place; your data and sign-in stay. It stops, naming the service, if the database is ahead of your checkout |
| `make dev` | The console alone on the in-memory mock, on :3016, with no backend |
| `make db-shell` | psql into the stack's database |
| `make reset-db` | Deletes the stack's database and rebuilds it from empty (asks first on the shared stack); `make db-reset` is the same |
| `make migrate` | Applies every service's migrations |
| `make verify` | Everything a commit must pass, on the scripted model with no paid model calls |
| `make usecase-test UC=uc-010 LAYER=ui` | Runs one use case; leave out `UC` or `LAYER` to run more |
| `make usecase-list` | Lists every use case |

Every port can be moved with its `OPS_*_PORT` variable in `.env`; `make ports` shows the names.

## Three common tasks

### Check a change before committing

```bash
pnpm verify                        # console type-check and standards check, docs check
make verify                        # everything: console, docs check, ruff, strict pyright, pytest (starts PostgreSQL)
```

`pnpm install` installs a pre-commit hook that runs `pnpm verify` on the staged content. A console change is also checked in a browser,
including the `?mock=` states.

### Add an API operation end to end

| Step | File |
|---|---|
| 1 Type | `apps/console/src/lib/types/<area>.ts` |
| 2 Contract method | `apps/console/src/lib/api/<area>-contract.ts` |
| 3 HTTP client | `apps/console/src/lib/api/<area>-http.ts` |
| 4 Mock | `apps/console/src/lib/api/mock/`, the only place fixtures exist |
| 5 Hook | `apps/console/src/hooks/<area>-queries.ts` |
| 6 Service route | The service that owns the console section (table below) |

The console's contract is the source of truth for the API. A screen never fetches outside a hook, and counts and
totals come from the API.

### Find the design for an area

Start at `docs/README.md`, which gives a reading order for engineers, architects and risk reviewers. Specs live in
the codeloop wiki at `.codeloop/wiki/concepts/`, decisions in `docs/architecture/decisions/`.

## Architecture

Each backend service is named after the console section it serves. `packages/` holds reusable libraries; `services/`
holds deployables.

| Service | Console section | Owns |
|---|---|---|
| `platform-service` | Access, Audit log, Settings | Sign-in, tenancy, roles, audit, API keys; routes requests to the other services |
| `agents-service` | Agents, Workflows, Deployments, Skills, Chat, Assurance | Definitions, versions, publishing, evals, channels, and running agents and workflows |
| `hitl-service` | Cases, Reviews | Cases, queues, SLAs, review decisions, approval tokens |
| `tools-service` | Tools, Connections | Every tool call: policy, credentials, approvals, call log |
| `models-service` | AI gateway | Every model call: provider keys, budgets, failover |
| `kb-service` | Knowledge bases, Wiki | Sources, ingestion, retrieval, citations |
| `files-service` | Documents | File storage, scanning, retention, legal hold |

This is the target layout (`docs/architecture/service-map.md`). Working code today: `services/agents-service/` and
`services/tools-service/` (prototypes), `services/files-service/` (service logic, no server yet), and the
libraries in `packages/`. The other services are not started.

The platform must run on one virtual machine with no container runtime, using native PostgreSQL and systemd, with
Docker Compose and Kubernetes (Kustomize) as optional targets under `deploy/`. Only the Compose dev stack exists
so far.

## Not built

Persistence for any area other than chat, authentication beyond a development mode, every service other than the
runtime, the AI gateway screens, and the deployment targets.

## Contributing

`CONTRIBUTING.md` covers doc standards, code standards, verification and commit messages. `AGENTS.md` holds the rules
for coding agents.

## Licence

Apache-2.0. See `LICENSE`.
