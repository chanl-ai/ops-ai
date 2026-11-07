# agents-service: working rules

Status: current.

The agents service (`ops_agents`, :8700) owns agents, workflows and their versions, chat, threads and the runs that
execute them, cases, task types, Reviews, guardrails, skills, memories, widgets and channels (mailboxes, the
embedded chat). It runs as two processes from one code base: the API (`python -m ops_agents.api`) and the workflow
worker (`python -m ops_agents.api.worker`), which claims `engine_work` and runs workflows with `packages/ops_engine`.

It does not make tool calls or model calls itself: every tool call, read or write, goes through tools-service's
gateway (`activities/gateway.py`), and model calls go through models-service when `OPS_MODELS_URL` is set. Shared
service rules: [services/CLAUDE.md](../CLAUDE.md). Cross-folder rules: [root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_agents/api/app.py` | `create_app` (`:243`): the FastAPI app, wiring of stores, gateway, models and background loops |
| `src/ops_agents/api/routers/` | One router per area (agents, chat, workflows, cases, reviews, tasks, widgets, mailboxes, ...) |
| `src/ops_agents/api/` (other modules) | Chat turns, leases and the sweeper, timers, metering, the journal, the worker, review and publish flows |
| `src/ops_agents/api/auth.py` | The route dependencies: `caller` (`:55`), `caller_in(area)` (`:61`), which still asks a service token for `<area>:view` |
| `src/ops_agents/store/` | All database code; `store/tenancy.py:30` names the tenant role `ops_runtime_tenant` |
| `src/ops_agents/graphs/` | LangGraph graphs (`agent_wrapper`, `simple_workflow`, `complex_workflow`), JSON definitions, versions |
| `src/ops_agents/activities/` | Tool, knowledge and gateway calls the graphs and the agent kernel make; the seed catalogue loader |
| `src/ops_agents/domain/`, `app/` | The first pieces moved into the onion layout (evals) |
| `seed/` | Dev records loaded at start: agents (`chat_agents.json`), workflows, case and task types, guardrails, skills, widgets, mailboxes |
| `migrations/` | Alembic chain, version table `alembic_version`; row security policies for the run tables |
| `experiments/` | `e<n>_*.py` experiments, run with `make experiment E=<n>` from the root |
| `scripts/` | `check_standards.py`, `check_openapi.py`, `scripted_server.py` (the service on the scripted model, used by use cases) |
| `tests/` | `api/`, `unit/`, `engine/`, `store/`, `timers/`, `checkpointer/`, `gateway/` (tools-service's gateway tests), `conformance/`, `loader/`; fixtures only in `tests/fixtures/` |

Layer order inside the module, enforced by `scripts/check_standards.py`: `ops_engine` → `ops_agents.domain` →
`ops_agents.app` → `ops_agents.activities` → `ops_agents.graphs` → `ops_agents.store` → `ops_tools` →
`ops_agents.api`. The rest of the code is not yet in the domain/app/adapters/api shape the service map asks for
([steps left](../../docs/architecture/service-map.md)). `api/ops_tools.py` holds the Ops assistant's tools; it is
unrelated to the `ops_tools` package of tools-service.

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8700 | `make stop` (the `make up` copy), then `make run` |
| The workflow worker in the foreground | `make worker` |
| One test file | `make test T=tests/test_seed_folders.py`, or from the root `make test PKG=services/agents-service T=tests/test_seed_folders.py` |
| One test | `make test T='tests/api/test_chat.py::<name>'` |
| Lint, types | `make lint`, `make typecheck` |
| Standards (layers, env reads, fixtures, every route authenticated) | `make standards` |
| OpenAPI gate / regenerate | `make openapi-check` / `make openapi` (then `make sdk` at the root) |
| The embedded chat loader in a real browser | `make loader-test` |
| Everything but the tests (what CI runs beside the test shards) | `make checks` |
| Apply the chain | `make migrate` (the root `make migrate` applies every chain) |
| New revision | `make migration NAME="add case table"` from the root |
| Background process | `make logs FOLLOW=0`, `make health` |

A bare `uv run pytest` refuses to start on any PostgreSQL database except the test database
(`tests/test_live_database_guard.py`); go through `make test`, which makes one. Most API tests run on in-memory SQLite
with the scripted model from `tests/conftest.py:143`; the gateway, checkpointer, timer and lease tests need
PostgreSQL, which `make test` provides. No test makes a real model call.

## Try it as a person

```bash
make api GET /v1/agents AS=builder SVC=agents Q='pageSize=5'
make api GET /v1/cases AS=viewer SVC=agents Q='pageSize=5'
make chat-agents AS=james                      # what New chat offers this person
make chat AS=james SAY='Reply with the single word ok.'   # one turn on the team's default agent
```

`make chat` runs one turn through the routes the chat screen calls (`/v1/chat/agents`, `/v1/chat/threads`,
`/v1/chat/threads/{id}/messages` as server-sent events) and prints the tool calls; it reaches a real model when the
stack's chat alias points at one. Reference: [make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| Graphs on threads | An agent, a workflow and a chat session all run as a graph on a thread: create a thread, run or resume it with a stream, read its state (`/v1/threads`, `/v1/threads/{id}/runs/stream`, `/v1/threads/{id}/state`) |
| Human steps | A human step pauses the graph with an interrupt; it resumes only through a review decision |
| Approval tokens | A write tool call carries an approval token bound to its input hash and the run's lease generation; tools-service refuses a stale one |
| Definitions are data | Agents, workflows, guardrails, skills, task and case types are records seeded from `seed/`, never code |
| Experiments | Each `experiments/e<n>_*.py` has a write-up under 60 lines in `docs/services/agents-service/experiments/`; its code stays only while `make verify` is green |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/agents-service/overview.md](../../docs/services/agents-service/overview.md) | What is built and where the code differs from the specs |
| [design.md](../../docs/services/agents-service/design.md), [chat-streaming.md](../../docs/services/agents-service/chat-streaming.md) | Design and the chat stream format |
| [workflow-node-coverage.md](../../docs/services/agents-service/workflow-node-coverage.md) | Which workflow nodes run |
| [docs/architecture/workflow-runner.md](../../docs/architecture/workflow-runner.md) | The engine and the worker |
| [docs/architecture/human-in-the-loop.md](../../docs/architecture/human-in-the-loop.md) | Reviews and approval tokens |
| [docs/usecases/agents-service/](../../docs/usecases/README.md) | 75 use cases, `make usecase-test UC=<id>` |
| [openapi.json](openapi.json) | The API, checked by `make openapi-check` |

Known differences from the docs: the overview says `migrations/` still holds tools-service's tables; tools-service
now has its own chain (`alembic_version_tools`), and only the gateway tests remain here in `tests/gateway`.
