# Agents service

Status: current. Prototype: chat and graphs work on seed data; see "What differs from the specs".

The agents service owns agents, workflows, their versions, chat and the runs that execute them
(`docs/architecture/service-map.md`). Today it serves the console's chat API: agents, threads, replies streamed over
SSE from a Pydantic AI agent loop (spec 15), gated writes that stop for approval and continue once approved, and
citations from a keyword passage store. The tools an agent may hold are tools-service's published operations: `GET
/v1/tools`, the grant check and every run read them from tools-service (`activities/tool_directory.py`), and every
call, read or write, runs through its gateway's `/v1/calls` (c-048 G1). The stack's seeded agents, granted seeded
operations, are in `services/agents-service/seed/chat_agents.json`; passages and the fixture tools the unit tests
run on stay in `services/agents-service/tests/fixtures/seed/`.

## Code

| Module | Role |
|---|---|
| `src/ops_agents/api` | FastAPI app, routers (chat, graphs, reviews, timers), chat turns, leases and sweeper, timers, metering, journal |
| `src/ops_agents/graphs` | LangGraph graphs `agent_wrapper`, `simple_workflow`, `complex_workflow`; JSON definitions, versions, SLA settings |
| `src/ops_agents/activities` | Tool, knowledge and gateway calls the graphs and the kernel make; seed catalogue loader |
| `migrations/` | Alembic history 0001 onward. It still holds the tools service's and review tables until migrations split per service |
| `tests/` | API, unit, checkpointer, gateway and timer tests; `tests/fixtures/` is the only place fixture data lives |
| `experiments/` | Experiment scripts; their write-ups are in `experiments/` next to this page |

Libraries it uses: `packages/ops_agent_kernel`, `packages/ops_checkpointer`, `packages/ops_service_kit`,
`packages/contracts`.

## Graphs on four calls

Chat agents and workflows also run as LangGraph graphs on threads, through four calls that mirror LangGraph Server.
State is saved after every node by the checkpointer, so a pause survives a restart.

| Call | Does |
|---|---|
| `POST /v1/threads` `{graph, metadata}` | Creates a thread for `agent_wrapper`, `simple_workflow` or `complex_workflow` |
| `POST /v1/threads/{id}/runs/stream` `{input}` or `{resume}` | Runs or resumes; SSE of `{event, runId, seq, node?, data?}`; a repeated `runId` replays |
| `GET /v1/threads/{id}/state` | Values, next nodes, pending interrupt |
| `GET /v1/threads?graph=` | Lists threads |

## Settings

| Setting | Env | Default |
|---|---|---|
| Database | `OPS_DATABASE_URL` | `postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime` |
| Port | `OPS_PORT` | `8700` |
| Model | `OPS_MODEL_ALIAS` | `gpt-5.5` (a `claude-*` alias selects Anthropic) |
| Model key | `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` for a `claude-*` alias | none |
| Tool gateway | `OPS_GATEWAY_URL` | none: tools then run in process from the fixture catalogue (unit tests only); the stack sets tools-service |
| Seeded agents | `OPS_AGENTS_SEED_FILE` | `chat_agents.json` in the seed directory (the fixture agents); the stack sets `seed/chat_agents.json` |

Values carry the `OPS_` prefix because a shared secret store may already define `DATABASE_URL` for another
service. Without a model key the service starts, `/health` reports the missing key and sending a message returns 503.

## Proofs

| Task | Command (from `services/agents-service`) |
|---|---|
| End-to-end chat against the running service | `uv run python scripts/prove-chat.py` |
| Three graphs through the four calls, plus a kill-and-resume | `uv run python scripts/prove-graphs.py` (needs a model key) |
| Regenerate `docs/architecture/dependencies.md` | `make sbom` |

Real model calls are capped at 10 per experiment unless the owner approves more; everything else runs on the
scripted model in `tests/conftest.py`.

## Cases and Reviews facade

The console's Cases runs and Reviews read runtime threads through `ops_agents/api/hitl_facade.py`, on the console's
own paths, so `NEXT_PUBLIC_OPS_CASES_API_URL` points those two areas here while the rest stays on the mock. Rows are
built server-side from each thread's state, run journal, SLA timers and decisions. These routes are a stand-in: they
move to `hitl-service` when it exists.

| Route | Does |
|---|---|
| `GET /runs?view&workflowId&state&queue&search&page&pageSize` | Workflow threads as `RunRow`s with view counts and facets; chat threads excluded |
| `GET /runs/{id}` | One `RunRow` with its node steps for the run sheet |
| `GET /reviews?view&…`, `GET /reviews/{id}` | Paused review steps and recorded decisions as `Review`s |
| `POST /reviews/{id}/decision` | Records the decision (keyed by the interrupt id), then resumes the thread under a run id derived from it. A failed resume leaves the decision standing and a repeat retries it once. Money movement needs a step-up token; `returned` is refused |
| `POST /reviews/bulk-decision`, `POST /reviews/assign` | Bulk decide per id; assignment reports every id skipped until `hitl-service` owns it |

Building a row reads each thread's state and journal, so a list costs a few queries per thread. That is fine at
demo volume and is the first thing to replace with stored columns.

## What differs from the specs

| Spec | Here |
|---|---|
| 14 R10–R15 sessions and turns under `/v1/chat/sessions` | The console's thread routes (`/chat/*`, also under `/v1/chat/*`) |
| 07 CD-11 AI SDK UI message stream | The console's `ChatStreamEvent` frames, which map one to one |
| 15 §5 resume stream after approval | The approval request runs the continuation and stores it as a new message; the console re-fetches |
| 13 step-up token verified | Any non-empty token is accepted and recorded on the interrupt |
| 07 CD-7 no self-approval | Not enforced: the dev auth mode has one user |
| 17 §2 schema `runtime` | Tables in `public`, so the API tests run on SQLite |
| 17 §4 generated `ops_contracts` | Hand-written models mirroring `apps/console/src/lib/types/chat.ts` |
