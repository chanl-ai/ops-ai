# Delivery

Status: current, updated 2026-11-18. What is proven, what is still open, and the questions only the bank can answer.

Each claim below names the use case or experiment that proves it, so a reviewer can run the check instead of trusting
the sentence. Use cases run on the scripted model; experiments marked "real model" used a small number of real calls.

## What is proven

Experiments are under `docs/services/agents-service/experiments/`; use cases under `docs/usecases/`, run with
`make usecase-test UC=<id>`.

| Claim | Evidence | Status |
|---|---|---|
| A chat agent, a simple workflow and a complex workflow run through the same four thread calls | uc-003, uc-004; `services/agents-service/scripts/prove-graphs.py` (real model) | Holds |
| A chat turn streams an answer with a citation | uc-001 | Holds |
| A write tool pauses the turn, and an approval with step-up resumes it | uc-002 | Holds |
| A paused workflow decided from the console's Reviews resumes once, and a repeated decision does not resume again | uc-008 | Holds |
| A paused thread survives a SIGKILL and a restart | uc-005; [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds |
| Our asyncpg checkpointer passes LangGraph's conformance suite (81 cases) and removes every LGPL package | [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds |
| Row-level security on the checkpointer tables stops one tenant reading another's checkpoints | [own-checkpointer](../services/agents-service/experiments/own-checkpointer.md) | Holds in tests; the service runs as one tenant today |
| A thread paused on version 1 finishes on version 1 after versions 2 and 3 are published | [pause-survives-graph-change](../services/agents-service/experiments/pause-survives-graph-change.md) | Holds |
| Two processes cannot run one thread; a run killed mid-node is recovered by the sweeper in about 5.5 s | [leases-and-sweeper](../services/agents-service/experiments/leases-and-sweeper.md) | Holds |
| A stale owner cannot write after a takeover: checkpoints, journal, status, timers, tool writes | [fencing](../services/agents-service/experiments/fencing.md), [fence-on-takeover](../services/agents-service/experiments/fence-on-takeover.md) | Holds, with the residuals listed in durability-failure-and-audit.md |
| A write tool that asks runs only with an approval token bound to its input hash (writes run without asking by default, row E49); money needs two approvers | [gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md); uc-007 | Holds, with the [prototype shortcuts](identity-and-tenancy.md#prototype-shortcuts-still-in-the-code) |
| Step-up is verified for signature, subject and age; a workflow review's requester cannot decide it; one person cannot be both money approvers | [approval-trust](../services/agents-service/experiments/approval-trust.md); uc-009 | Holds; `POST /v1/threads/{id}/approvals` runs the same decider check as decide (row E51) |
| An approved write re-sent after a crash runs once at the gateway | [gateway-approval-token](../services/agents-service/experiments/gateway-approval-token.md) | Holds |
| SLA timers warn, breach, escalate and time out into the outcome pinned in the definition | uc-006; [timers-and-sla](../services/agents-service/experiments/timers-and-sla.md) | Holds |
| Checkpoint storage stays bounded with references in state and pruning after the journal | [checkpoint-growth](../services/agents-service/experiments/checkpoint-growth.md) | Holds |
| The runtime adds under 150 ms to a chat turn | [chat-turn-latency](../services/agents-service/experiments/chat-turn-latency.md) (real model) | Holds: 52 to 89 ms at p50 |
| Redelivered mail opens no second case; replies to a busy case queue in order | [mailbox-adapter](../services/agents-service/experiments/mailbox-adapter.md) | Holds on a fake mail source; a real tenant is not run |
| The lock has no copyleft beyond file-level MPL-2.0, and makes no outbound call under a socket guard except tiktoken's first download | [dependencies.md](dependencies.md) | Holds with one condition: vendor the tiktoken encoding |
| Delegation tokens with an `act` claim from the IdP | Not run | Open |
| The engine conformance suite passes on the LangGraph adapter (13 tests) | [conformance-suite](../services/agents-service/experiments/conformance-suite.md) | Holds; no `Engine` interface and no second engine yet |
| A re-run agent node replays its recorded model call; route to people stops a workflow at a step end and skips the rest | [conformance-suite](../services/agents-service/experiments/conformance-suite.md) | Holds on the LangGraph adapter |
| Every graph model call writes a usage row; a thread pauses for a person when its budget is spent; metering adds about 3 ms per call | [cost-and-budgets](../services/agents-service/experiments/cost-and-budgets.md) | Holds on the scripted model; chat routes are not metered and key budgets admit every key |
| A person signs in, refreshes and signs out; members and roles; every write is audited; anonymous and foreign tokens are refused; another service verifies tokens from JWKS | uc-021, uc-023, uc-025, uc-026 | Holds |
| A builder manages a tool module; every call runs through the registry and is logged with its verified caller | uc-010, uc-011 | Holds |
| Tools import from OpenAPI and MCP; a credential is a secret that never comes back; egress only to allowed hosts | uc-012, uc-013 | Holds |
| An agent and a workflow go from draft to published with a second person's approval, from the API and the console | uc-018, uc-019 | Holds |
| Chat starts a workflow and a reviewer approves its step | uc-020 | Holds |
| An agent runs on the model alias its publisher chose, through models-service | uc-028 | Holds on the scripted model |
| An approval outlives its token | uc-027 | Holds |
| In-run grading agrees with a person | Not run | Open |

## How a claim becomes proven

| Rule | Detail |
|---|---|
| One use case per user-facing operation | `docs/usecases/<service>/<topic>.md` plus one script per layer, run by `make usecase-test` |
| Name the non-vacuous check | Each use case and experiment names the check that fails when the behaviour breaks; it is watched to fail once with its guard removed |
| Scripted model for volume | Real model calls only for an approved baseline, ten per experiment at most |
| Experiments write facts | One file per experiment under `docs/services/agents-service/experiments/`: what was built, measurements, failure modes, gotchas, verdict |
| Code from an experiment stays only if `make verify` is green and a test was watched to fail | Otherwise it is removed |

## What is still open

| Work | Why it matters | Where it is described |
|---|---|---|
| Reviews, Cases and decisions in their own package, `ops_hitl` | The code lives in agents-service, so a deployment cannot run workflows without it | [Service map](service-map.md#steps-left) |
| Schedule, webhook, email and poll triggers in one package, `ops_triggers` | Each channel starts runs its own way today | [Service map](service-map.md#steps-left) |
| Several services in one process | `deploy/host` starts each service as its own process from one image; embedding several in one process is not built | [Service map](service-map.md#deployment-targets) |
| SQL Server and Azure SQL at run time | The store, service-kit and identity tests pass on SQL Server 2025 in CI and the schema scripts are ready for a DBA; no install has run every service on it end to end yet | [Azure SQL](../guide/azure-sql.md) |
| Delegation tokens with an `act` claim from the bank's identity provider | platform-service mints the tokens today; one issued by an outside provider is untested (open question 6) | [Identity and tenancy](identity-and-tenancy.md) |
| Grading quality | The grade node is a judge prompt with unknown calibration; the cheapest proof is 30 drafts scored by the judge and by a person | [Human in the loop](human-in-the-loop.md) |
| A reviewer's day | The Reviews queue for days-long pauses has not been walked by an operator with five paused cases | [Human in the loop](human-in-the-loop.md) |

## Gaps known from the experiments

| Gap | Where it is described |
|---|---|
| A gateway that dies mid-write leaves an unknown outcome; needs a reconciler | [durability-failure-and-audit.md](durability-failure-and-audit.md) |
| A recovery after the approval token's TTL has no re-review path | [human-in-the-loop.md](human-in-the-loop.md) |
| Events are stored only when a run ends; no re-attach or per-thread `seq` | [api.md](api.md) |
| Inbox race between the state check and the insert | [channels-and-deployments.md](channels-and-deployments.md) |
| Migrate checks node names only | [definitions-and-versions.md](definitions-and-versions.md) |
| Prototype trust shortcuts | [identity-and-tenancy.md](identity-and-tenancy.md#prototype-shortcuts-still-in-the-code) |
| No retention job; checkpoint pruning is not scheduled | [data.md](data.md) |

## Open decisions

| Decision | Options | Default until decided |
|---|---|---|
| May a chat user approve their own drafted write? (open question 18) | Never; for non-money write classes a published policy names; per risk tier | `requesterMayDecide` is on by default, so the person who asked decides where their role lets them; a team that turns the two-person rule on refuses them (403 `own_request`) unless they are an Admin of the team (register row E51); workflow reviews refuse the requester, and a money call through the gateway needs two distinct approvers |
| Graph runtime: the open-source LangGraph library or LangGraph's hosted Agent Server | Library with our leases, sweeper, timers and event log; Agent Server as a paid product | The open-source library with our own durability code; Agent Server stays an option for later |

The engine was settled on 2026-10-16: `ops_engine` with LangGraph as the runner on PostgreSQL, with no Temporal
adapter. The decision records list further questions with defaults: the timer poll interval, the fence store in the
gateway and external schedulers ([ADR-0016](decisions/fencing-and-timers.md)).

## Open questions

Questions only the bank can answer. Specs and decision records cite them by number; a settled question is removed and
its number is not reused.

| # | Question | Blocks |
|---|---|---|
| 1 | Which Kubernetes platform and regions; is any public cloud allowed? | Engine choice, deployment |
| 2 | Is PostgreSQL an approved operational database? | Phase 1 |
| 3 | Who operates the runtime, the gateways and the registry, on what on-call model? | Phase 1 |
| 4 | Who owns retention and legal hold for mail, journals, gateway logs and evidence, and for how long? | First workflow |
| 5 | Which WORM storage product is used on-prem? | First workflow |
| 6 | Does the IdP support token exchange with an `act` claim; can systems of record log an actor? | First write action |
| 7 | Maximum case duration; is continue-as-new at a decision point acceptable to Audit? | Phase 2 |
| 8 | Which risk tier sits below the change board's pre-approval line? | Promotion design |
| 9 | Must an existing case system remain the record for operations cases? | Cases |
| 11 | Does the bank run n8n, Camel or an API gateway it wants reused as connector sources? | Tool modules |
| 12 | Which AWP specification is intended; is portability in a policy or contract? | Definition format |
| 13 | Which model providers and private endpoints are approved; does any forbid prompt retention? | Model aliases |
| 14 | Is the n8n Sustainable Use License acceptable for internal use? | Tool modules |
| 15 | May the AI gateway send configuration and usage metadata (no prompts) to a vendor? | Phase 1 |
| 16 | Can Exchange administration grant an application access to specific shared mailboxes on request, and how fast? | Workflow 2 onward |
| 17 | Who are the chat users; is another assistant the staff standard? | Phase 2 |
| 18 | Which risk tiers allow a user to approve their own drafted action in chat? | Chat writes |
| 19 | Does Security accept policy approval tokens for the write classes a gate policy names? | First workflow's approval rules |
| 20 | Does the network review allow Graph change notifications for mailboxes and SharePoint? | Phase 2 |
| 21 | Who names the Model Risk second-line approver group, and when? | First `high` workflow |

## From draft to main

| Column | What puts it there | What runs |
|---|---|---|
| Draft | A pull request opened as a draft | Nothing from `ci.yml`; CodeQL and the leak scan as usual |
| Ready | Marked ready for review | The jobs of what it changed (below) |
| Reviewed | The reviewer adds the label `reviewed`; `hold` keeps it out, a push removes the label unless it only merged develop in | `auto-queue.yml` arms it: not a draft, base `develop`, from this repository. A stacked pull request is armed only once its base merged and it was retargeted to `develop` |
| Queue | Armed pull request | The merge queue: every job of the plan, SQL Server included. A second red run drops it with the label `queue-failed` and a comment naming each failed job |
| `develop` | The queue's merge | Staging deploys it (skipped with a notice while a release or hotfix branch exists) |
| Release branch | `make release-start` | Every job on each push, `release-security.yml`, the staging deploy; `make release-rc` tags a candidate |
| `main` | The owner merges the release pull request | `release-finish.yml` tags `vX.Y.Z`, publishes, merges back into `develop` ([Releasing](../deploy/release.md)) |

## What a pull request runs

A pull request runs fast feedback for the areas it changed: the plan, `checks` (the script tests too, when `scripts/` or a workflow changed), the touched services' and packages' tests, the console and docs jobs when touched, and the maintainer review. The slow jobs (`repo`, `store-mssql` and `release-proof`) have `needs.plan.outputs.heavy == 'true'` in their `if:`; `scripts/ci-plan.sh` prints `heavy=false` for a `pull_request` event unless the pull request is titled `[ci full]` or labelled `ci:full`. The merge queue (`merge_group`), pushes to develop and pushes to `release/*` or `hotfix/*` run them, so every change passes them before it reaches develop. A push to develop of a commit a green merge queue run of `ci.yml` already tested plans nothing (`CI_TESTED` in `scripts/ci-plan.sh`), so a merge is tested once on develop's tip; `ci-ok` and the staging deploy still run. `ci-ok` counts a skipped job as passed. `scripts/tests/test_ci_plan.py` fails when `store-mssql` or `repo` is planned on a pull request.

The `repo` job is one matrix entry per `repo_jobs` item of the plan: each suite of the full plan outside the services (`pool-pyright`, `pool-store`, `pool-engine`, `pool-packages`, `pool-deploy`), `checks` (ruff on `packages/`, the check list, the maintainer-review history), `scripts` (the script tests on `pytest -n auto --dist loadfile`) and `sdk` (`sdk-verify`, `changelog-verify`), all in parallel.
