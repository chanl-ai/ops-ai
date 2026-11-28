# Coding guide for agents version 2

Status: proposed design, written 2026-11-26. It applies to every change made for releases 1.4.0, 1.5.0 and 1.6.0.

This guide tells an engineer how to write the code the specs in this folder describe: where each kind of code goes, how
the agent library is kept behind our own contract, how each of the five protections is enforced and which test proves
it, and how to test without writing too many tests. It adds nothing to the architecture standards; where a rule already
exists there, this page names it and says how it applies here.

## Where code goes

The layering rules are in `docs/architecture/standards/layers.md`. Applied to this work:

| Kind of code | Goes in | Rule |
|---|---|---|
| The runtime contract: requests, results, events, ports | `packages/ops_agent_kernel` (`types.py`, `ports.py`, `events.py`) | LY5: the package imports no service |
| Everything that imports the agent library | `packages/ops_agent_kernel/src/ops_agent_kernel/strands_loop/` and nowhere else | LY9: an outside system sits behind a port. Enforced by an import contract, below |
| Features that are ours (plan, skills, typed answers, guardrails, judge, tool search) | `packages/ops_agent_kernel`, outside `strands_loop/`, written against `LoopSeams` | They must work with any loop driver |
| Budget checks and the model-call record | `services/models-service` | LY7: one owner per job. No second ledger in the agents service |
| Tool policy, approvals, the exit gate, web tools | `services/tools-service` | SC1: two gateways, no other way out |
| Sandbox lifecycle and backends | `services/sandbox-service` | A backend is an adapter behind `SandboxBackend` |
| The spec file's model, validation and storage | `services/agents-service`: `domain/agent_spec.py` (pure), `app/agent_spec.py` (use cases), `store/` (rows), `api/routers/agent_spec.py` (one route does one thing, LY2) | LY1: imports point inward |
| Connection kinds, groups, undo, rebuild | `packages/ops_engine` | The engine imports neither the agents service nor the kernel; it calls `AgentPort` |
| Human task behaviour | `services/agents-service/src/ops_agents/app/tasks.py`; notifiers are adapters behind `TaskNotifier` | LY9 |
| Shapes shared by two services | `packages/contracts` | LY4: services never import each other |
| SDK nouns and CLI commands | `sdk/`; the CLI calls the SDK only | LY6, UI7 |
| Console screens | `apps/console`, through hooks over the generated client | UI2 |

Names say what a module does (LY8). No module in this work is named with `new`, `v2`, `helper`, `util` or `manager`; the
folder is `strands_loop`, not `loop_v2`.

## Wrapping the agent library behind our contract

The specification is [runtime contract and Strands loop](runtime-contract-and-strands-loop.md). The rules for code:

| Rule | Detail | Check |
|---|---|---|
| One import site | Only files under `strands_loop/` import `strands`. An import-linter contract named `strands-only-in-its-adapter` forbids it everywhere else, including tests outside that folder | `lint-imports` in the gate |
| No library type crosses the contract | `TurnRequest`, `TurnResult`, `Interrupt`, `KernelEvent` and every port use our types. A Strands message, event or snapshot is converted inside the adapter | The typed-boundaries check, and a test that builds `TurnResult` with the library uninstalled from the import path of the caller |
| The library never reaches the network | Its model client is given the `ModelEndpoint` of the model gateway and nothing else. Its own tool-server client, session managers, retry sleeps, telemetry exporters and hosted tools are off | A test with a transport that fails any request not addressed to the scripted gateway |
| Pause state is opaque outside the adapter | `LoopState.data` is bytes plus a schema number. Only the adapter reads it. It is stored by our checkpointer as every checkpoint is: a tenant-scoped row, with no added encryption | A resume test in which the state is passed through a second process |
| A second loop is a second adapter | Another loop implements `LoopDriver` in its own folder with its own import contract. `KernelPorts.loop` selects it from a setting our engineers control; it is not in the spec file | The contract test suite runs against every registered driver |
| Version pin | The library is pinned to a minor range in `packages/ops_agent_kernel/pyproject.toml`. An upgrade is its own pull request that runs the contract suite and experiments 1 to 3's scripts | SC4 |
| Scripted model | Tests use `ops_agent_kernel.testing.ScriptedModel`, which answers the gateway's completion route from a Python function. Tests never patch the library | TS6, TS8 |

Order of the switch, so the suite is never red for a reason nobody can read:

| Step | What changes |
|---|---|
| 1 | Add the scripted-model seam and move the kernel's tests onto it, still under the current loop |
| 2 | Add `LoopDriver` and `LoopSeams`; wrap the current loop as a driver; tests unchanged |
| 3 | Add the Strands driver; run the same tests against both drivers |
| 4 | Make the Strands driver the default; delete the old driver, its dependency and the half of the kernel that drove it |

## How each protection is enforced

| Protection | Enforced where | The test that proves it |
|---|---|---|
| A run can pause for days and survive a restart | The kernel returns an `Interrupt` with `LoopState`; the checkpointer stores it; the engine stores a waiting step with a reference. Nothing is held in memory | A turn pauses for approval; every process is stopped; a different process resumes it; the write is sent once and no model call is charged twice. Runs on both databases |
| Each tenant's data is separate | Every new table has `tenant_id` and the isolation policy. A worker enters one tenant per item (EV6). Sandbox storage keys carry the tenant prefix. One sandbox serves one conversation | The isolation test per new table; the sandbox suite's row 1; a turn for tenant A given tenant B's thread id answers 404 |
| A person approves any action that changes data | The kernel asks the tool gateway to decide before a tool runs and pauses there. The tool gateway refuses a write without an approval token, and from 1.4.0 it is the only process that mints one (`POST /v1/approvals`); the signing key leaves the agents service. Who may approve is the tenant's approval policy | A scripted model calls a write tool under every loop kind and from inside a sandbox: each ends in an interrupt and the scripted system saw no request. With the two-person rule on, the asker's own approval is refused by the tool gateway |
| Secrets stay behind the two gateways | The agents service holds no provider key and no tool credential. The model gateway adds provider keys; the tool gateway and its exit gate add tool secrets | The network test above; a scan of every model request and sandbox environment in the suite for the planted secret values |
| A cost budget | The model gateway reserves cost, calls and tokens against every budget named in `X-Budget-Id` before a call and settles after. Keys of kind agent, workflow and purpose are refused without a budget id and a replay key. The kernel only reacts to `budget_reached` | With a budget of three calls, the fourth is refused at the gateway even when the caller is a helper, a team member or a retry; concurrent callers cannot overspend by more than one reservation |

A change that touches a path in the "Enforced where" column re-runs that row's test before it is committed, and the
commit body names the output.

## Errors

| Rule | Detail |
|---|---|
| Typed and coded | Every failure a caller can act on is an `ApiError` subclass with a stable `code` (OB3). The codes this work adds are listed on the [API page](api.md) |
| Actionable message | The message says what was refused and what the reader can do: "The host files.example.org is not allowed for this agent. A security admin can add it on the Egress page." |
| No bare `except` | Catch the type you can handle. A library exception is converted to ours at the adapter's edge, keeping the original as the cause |
| Model and tool failures inside a turn | Returned to the model as a tool result or ended as a stop reason, per the contract's stop-reason table. They are not raised through `run_turn` unless the turn cannot continue |
| Refusals are not retried | `budget_reached`, an approval refusal and a policy refusal carry `retryable: false`; the kernel's retry wrapper retries only what the error row marks retryable (OB6) |
| A 4xx or 5xx in a use case is a failure | A use case never treats an error status as expected unless the case is about that error |

## Events

| Rule | Detail |
|---|---|
| Kernel events | Frozen dataclasses in `ops_agent_kernel/events.py`. Adding one adds its row to the event mapping table in the runtime contract in the same change |
| Stream frames | Typed models in `packages/contracts` with a `type` field. The agents service maps kernel events to frames in one module. A frame is added to the union, the OpenAPI document and both SDKs together |
| Outbox events | Written in the same transaction as the change (EV1), through the one relay (EV2). A receiver tolerates a repeat (EV3). Names are `<noun>.<past tense verb>`: `sandbox.state_changed`, `models.budget_exhausted` |
| Payloads | Ids and counts. No message text, tool input or file content in an outbox event |
| Logs | Through the kit (OB1), with tenant, thread, run and call ids. A model request's content is never logged |

## Tests

The standard is `docs/architecture/standards/testing.md`. In practice:

| Rule | How to apply it |
|---|---|
| Name the failure modes first (TS1) | Each spec's "Acceptance criteria" table is that list. Write one test per row, and stop. A row that an existing test already covers gets no new test |
| Budget (TS2) | At most 5 new tests for a small change, 10 for a medium one, 15 for a large one. A lane that implements a whole spec is large. More needs a written reason in the pull request |
| Check before adding | Break the behaviour first and run the existing tests. If one fails, extend it |
| Through the public seam (TS4) | Kernel behaviour is tested through `run_turn` with ports. Services are tested through their routes. No test imports a private function, asserts call order or inspects `LoopState.data` |
| Mock only at the edge | Three things are faked: the model (the scripted model), the network (scripted HTTP hosts, the fake Sprites API, the fake Kubernetes API) and the clock. Our own modules, stores and gateways are real |
| Seen failing once (TS3, DL9) | Revert the change or break the line, run the test, and paste the failing output in the commit body or pull request. A test never seen red is removed |
| No test of a library (TS8) | No assertion about what Strands, the HTTP client or the database driver does on its own. If a test would only fail when a dependency changes, delete it |
| Both databases (TS6, DA9) | Store tests and migrations run on PostgreSQL (`make test PKG=…`) and SQL Server (`make mssql-remote-test PKG=… T=…`). A new statement uses `ops_store.dialect`; the portable-store check keeps raw dialect SQL out |
| Different hands (TS7) | The test writer commits the failing tests for a spec's table; the builder makes them pass and does not edit them. A disagreement goes back to the spec |
| Delete as you go | The old loop's tests that assert its internals are deleted with it, not ported |

### Use cases

A use case proves a flow end to end on a running stack, once per layer (TS5).

| Item | Rule |
|---|---|
| Where | `docs/usecases/<area>/scripts/test-uc-<number>-<layer>.py` (api, sdk, cli), `.mjs` for the TypeScript SDK, `.spec.ts` for ui |
| Run | `make usecase-test UC=<id> LAYER=api\|sdk\|cli\|ui` |
| What to write | The rows of each spec's "Use cases per layer" table, inside out: api first, then sdk, cli, ui |
| Model | The stack's scripted model alias, so a use case costs nothing and is repeatable |
| Done | A change is done when its use case has run at every layer it touches and the output is in the pull request. Typecheck and unit tests passing is not that |
| Registry | A use case listed as passing without a script that ran is removed from the registry |

## Both databases

| Rule | Detail |
|---|---|
| Statements | SQLAlchemy Core only (DA2). Differences live in `ops_store.dialect` (DA3): `claim`, `upsert`, `insert_ignore`, the clock |
| Migrations | One chain per service, one head (DA8); each migration upgrades and downgrades on both databases (DA9). A new tenant-scoped table adds its SQL Server policy in the same migration |
| Types | JSON through the store's JSON type; binary as `LargeBinary`; money as `Numeric(18, 6)`; timestamps with time zone |
| Indexes | Every foreign key and filter column (DA7). No partial index; SQL Server filtered indexes behave differently and none is needed here |
| Lists | Filter, sort and page in SQL (DA5); no query in a loop (DA4) |
| Writes | State the state they expect (DA12): a conditional update with a row count check, not a read followed by a write |

## Where this work departs from the standards

The product is not in production, so two compatibility rules are set aside for these releases. Everything else applies.

| Standard | Departure | Why |
|---|---|---|
| DA10: a column is dropped one release after it stops being read | Columns and tables of the old runtime are dropped in the release that stops using them | No tenant has data to keep; installs are reseeded |
| DL6: an upgrade from the previous release is proven | Not proven for agent and conversation data across 1.3 to 1.4. The upgrade proof still runs for every other service | The decision is to reseed, with no migration of old agent definitions or paused conversations |
| API compatibility | Changed and removed routes have no alias and no deprecation period | Same |

Still required: DA9 (every migration downgrades), DL4 (every merge reaches staging under the real migrations).

## Settings

| Rule | Detail |
|---|---|
| One settings object per process (CF1) | New settings are fields on the service's settings class, with the names in each spec's "Settings" table |
| No literal host, port, model or timeout in code (CF2) | The constants this work finds, such as the tool-server client's timeout, become settings |
| Missing required settings stop the process (CF3) | A sandbox backend without its required settings does not start |
| Secrets from the secret store (CF4) | The Sprites token, each tenant's Teams app secret (a connection), the exit gate's certificate key |
| The default is the safe value (CF5) | Network deny, sandbox off, web tools off, the weak isolation level refused for a shared install |

## Generating the SDK

| Step | Command |
|---|---|
| After a route or model changes | `make openapi`, which regenerates each service's `openapi.json` and then both SDKs' generated layers |
| Check | `make sdk-verify`: the generated layer matches the documents and both SDKs' tests pass |
| Hand-written layer | Add the noun's method in Python and TypeScript in the same pull request (UI6); the parity test fails otherwise |
| Never | Edit a file under `_generated/` or `generated/` by hand, or write a request shape by hand in the SDK |

## Comments and names

| Rule | Detail |
|---|---|
| Comments say why | A constraint, an ordering requirement, a failure being worked around. Not what the next line does |
| No history or first person | "Recompiled per call: the shared instance carries state between matches." Not "this used to be broken" or "I found" |
| Module docstrings state the contract | What the module owns and what it must not do, as the existing kernel and engine modules do |
| Index and constraint comments state the guarantee | "Unique (tenant_id, thread_id): one sandbox per conversation" |
| Names describe the thing | `GatewaySandbox`, `exit_gate`, `rebuild.py`. Not `SandboxManager`, `utils.py`, `new_loop.py` |
| Banned words in prose and comments | "simply", "just", "easy", "obviously", "of course" |

## What never to do

| Never | Because |
|---|---|
| Import the agent library outside `strands_loop/` | The contract is the only thing that lets the loop be replaced |
| Give the loop, a helper or a sandbox a provider key, a tool credential or a service token | Secrets stay behind the two gateways |
| Call a model provider or any outside host from the agents service | SC1 |
| Check or count a budget in the agents service, or send a model call without a budget id and a replay key | One owner: the model gateway, which refuses such a call |
| Mint an approval token anywhere but the tool gateway, pause a turn anywhere but `before_tool`, or let a setting switch approvals off for a write | A person approves every change |
| Keep a paused turn in memory, a local file or a library's session store | It must resume on another server |
| Reuse a sandbox computer for a second conversation | Tenant isolation |
| Decide a command is safe by reading its text | The check can be bypassed; approvals sit at points the sandbox cannot avoid |
| Add a second ledger, queue, scheduler or audit path | LY7. List what already does the job and use it |
| Join, count or filter lists in the browser | UI1 |
| Write raw SQL strings or a dialect-specific statement outside `ops_store.dialect` | DA2, DA3 |
| Put a card or ticket id, a machine path, a session link, a customer's name or a real mailbox in code, tests, docs or commits | The repository is public (SC5). Sample data comes from several industries |
| Commit code that has not been run end to end | Typecheck passing does not show that it works |
| Skip a hook with `--no-verify`, stash in a shared tree, or push to the trunk | DL1, DL2 |

## Open points

| # | Open point | Settled by |
|---|---|---|
| 1 | Whether the contract suite should run against the old driver until 1.4.0 ships or be deleted with it at step 4 | The 1.4.0 lead; this guide assumes deletion at step 4 |
| 2 | Whether the SQL Server run is required on every pull request of these lanes or nightly | The pipeline's owner; the store tests of each new table are required on both before merge |
