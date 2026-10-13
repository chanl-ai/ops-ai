# Operations

Status: current, updated 2026-10-11 against HEAD; every decision is an option until the owner confirms it.

Make layout, every port, every environment name and the daily commands are in [make.md](make.md). Deployment targets
(one VM with systemd, Compose, Kubernetes with Kustomize) are in [service-map.md](service-map.md). Nothing deploys from
this repo yet.

## Running it

| Task | Command |
|---|---|
| First setup | `make install` |
| Start PostgreSQL and OPA, migrate, start agents, tools and console | Run `make up` under your secrets manager, so model keys reach the process |
| Is it up | `make health` |
| Follow one service | `make logs SVC=agents` (or `tools`, `console`) |
| Stop | `make down` (`KEEP_DB=1` keeps PostgreSQL and OPA) |
| Second stack beside the first | `ISOLATED=1` on any target: every port +1000, own compose project and data volume |
| Before committing | `make verify` (runs with model keys unset) |

Ports for the shared, isolated and use case stacks are in [make.md](make.md#ports).

## Environments

| Environment | `OPS_ENVIRONMENT` | What Settings enforces |
|---|---|---|
| Development | `dev` | Dev auth allowed; default review key and service token allowed |
| Test, production | `test`, `production` | Dev auth refused at start; the review key and the service token must be set, or the process refuses to start |

Services read only `OPS_*` variables plus the provider key names (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), through one
settings class in `ops_service_kit`. Locally a gitignored `.env` (contract: `.env.example`) feeds them through make; deployed services read the environment. Runtime settings that matter for operations:

| Variable | Default | Effect |
|---|---|---|
| `OPS_LEASE_TTL_SECONDS` | 15 | Time before a dead run's thread can be taken over |
| `OPS_SWEEP_INTERVAL_SECONDS` | 3 | How often each process looks for expired leases |
| `OPS_TIMER_POLL_SECONDS` | 1 | Timer poll interval; 0 turns the poller off |
| `OPS_GATEWAY_URL` | unset | Set: write tools and `send_reply` go through tools-service. Unset: tools run in process |
| `OPS_REVIEW_TOKEN_TTL_SECONDS` | 900 | Approval token lifetime |
| `OPS_MODEL_ALIAS` | `gpt-5.5` | Chat model; a `claude-*` alias selects Anthropic |
| `OPS_TURN_DEADLINE_SECONDS` | 120 | Upper bound on one chat turn |
| `OPS_PRICES` | `{}` | Model prices per million tokens by alias, as JSON (`{"gpt-5.5": {"input": "1.25", "output": "10"}}`). An alias with no entry costs zero |
| `OPS_ALLOW_SELF_APPROVAL_IN_CHAT` | `true` | Whether the person who asked a chat agent may approve its write; owner decision pending ([delivery.md](delivery.md)) |

## Health and logs

| Check | What it proves |
|---|---|
| agents-service `GET /health` | Process up, database reachable, and whether a model key is configured (`model` reports the error when not) |
| tools-service `GET /health` | Process up only; it does not probe OPA or the database |
| `make health` | Every service, OPA and PostgreSQL, with who owns each listener |
| `.logs/<svc>.log` | stdout and stderr of `make up` processes; structured events such as `model_call`, `timer_sync_failed`, `unhandled_error` |
| `GET /v1/threads/{id}/runs` | A thread's journal: runs, node sequences, owner, generation, crash records, SLA and lease rows |
| `GET /v1/threads/{id}/state` | Status, next node, pending interrupt, pinned version, SLA timers, cost and budget |

## The acceptance gate

A change is accepted when its use cases pass: `make usecase-test UC=<id>` (all of them with no `UC`). The runner
starts its own agents-service on the scripted model, on its own ports and database, removes model keys unless the
owner approved a number of real calls (`APPROVED_REAL_CALLS=<n>`), and passes a use case only on exit 0, no `FAIL`
line and at least one `PASS`. A registry status is a record of the last run, never evidence. Rules and layers:
[usecases/README](../usecases/README.md). Experiments are
capped at ten real model calls unless the owner approves more.

## What to watch

| Signal | Why | Healthy |
|---|---|---|
| Expired leases not taken over | The sweeper is down or stuck on a long recovery | None older than TTL + one sweep interval |
| `crashed` runs | A process died mid-node; each crash re-runs the node and its model calls | Rare; each followed by a `recovery` run |
| `lease_lost` runs and `stale_owner_finished` records | Pauses longer than the TTL: GC, a slow database, a stalled host | Near zero; a rise means the TTL is too short |
| `lease.fence_not_raised` | tools-service was down during a takeover | Zero |
| Timers due and unfired | The poller is off or every fire returns `busy` | Fired within one poll interval of due |
| `sla.fire_failed` | A breach resume failed three times | Zero; each needs a person |
| `gateway_calls` rows in `running` | A gateway died mid-write; the effect is unknown | Zero |
| Checkpoint write p95 | Grows with state size and concurrency | Under 50 ms; above it, look for payloads in state |
| Clock | Leases and timers use PostgreSQL's `now()`; processes must agree with it | Skew well under the TTL |
| Write-table bloat | Pruning deletes rows and returns no disk space | Scheduled REINDEX and VACUUM |

## Runbooks

### Stuck thread

1. `GET /v1/threads/{id}/state`: is it `busy`, `interrupted` or `error`, and what is `next`?
2. `GET /v1/threads/{id}/runs`: the last run's status, owner and generation.
3. `busy` with no live owner: wait TTL + sweep interval for the sweeper; if no `recovery` run appears, check the
   sweeper is running in some process (`make logs SVC=agents`).
4. `interrupted`: it waits for a person; check its SLA timers in the state. Nothing to recover.
5. `error`: the checkpoint holds the last good step. Fix the cause, then resume, or for a definition workflow `POST /v1/threads/{id}/route-to-people` with a reason.

### Bad version published

1. Move the pointer back (designed); today, publish the previous definition again so new threads take it.
2. Threads already on the bad version keep it. Migrate waiting ones with `POST /v1/threads/{id}/migrate` to a version
   where the waiting node exists, after diffing the definitions from that node onward.
3. Running threads on the bad version: `POST /v1/threads:route-to-people` with the workflow, version and a reason.

### Key rotation

| Key | Today | Steps |
|---|---|---|
| Review key (`OPS_REVIEW_KEY`) | HMAC, shared by agents-service and tools-service | Set the new value for both and restart both; tokens minted with the old key are refused, so re-approve open reviews with live tokens |
| Service keys (`OPS_SERVICE_SIGNING_KEY`, `OPS_SERVICE_SIGNING_KID`, `OPS_SERVICE_PUBLIC_KEYS`) | Each service signs its calls to another with its own Ed25519 key; a callee trusts the public keys it lists, each bound to one service | Give the service a new `OPS_SERVICE_SIGNING_KEY` and, with it, a new `OPS_SERVICE_SIGNING_KID`; add its public key to every callee's `OPS_SERVICE_PUBLIC_KEYS` beside the old one; restart the callees, then the caller; then drop the old kid from each callee's list and restart the callees again. An `OPS_SERVICE_TOKEN` left over from before is ignored; remove it |
| Model keys | Provider key names, read at start | Change in your secrets manager; `make restart SVC=agents` |
| Database credential | In `OPS_DATABASE_URL` | Change, then restart every service and rerun migrations under the new role |
