# Use cases

Status: current.

A use case is one user-visible behaviour checked end to end through a public surface: the HTTP API, the SDK, the
CLI or the console. This folder is the central testing surface for those layers. Each service keeps its own unit and
integration tests (pytest in the Python services); use cases only drive what a client can drive.

## Run them

| Task | Command |
|---|---|
| Prerequisite: PostgreSQL :5477 and OPA :8181 | `make db-up` |
| One use case, every layer it lists | `make usecase-test UC=uc-001` |
| One layer | `make usecase-test UC=uc-002 LAYER=ui` |
| All of them | `make usecase-test` |
| Registry, one entry, coverage | `make usecase-list`, `make usecase-show UC=uc-002`, `make usecase-coverage SERVICE=agents-service` |
| Register a new one | `make usecase-new SERVICE=<service> TITLE="<title>"` |

Run make under your secrets manager as for the rest of the stack. The scripts do not need model keys and the runner
removes them.

## Rules

| Rule | Detail |
|---|---|
| Scripted model only | A script starts its own agents service on the scripted model (`services/agents-service/scripts/scripted_server.py`) on ports and a database the run owns: free ports picked at start and a database `ops_usecase_r<pid>_<hex>` dropped when the run ends, so two sessions' runs never meet (`OPS_USECASE_*` set explicitly wins). The runner removes `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the script's environment unless `APPROVED_REAL_CALLS=<n>` is set, with n the number of real calls the owner approved |
| A pass needs evidence | A script prints one `PASS <name>` or `FAIL <name>: <detail>` line per check. The runner passes a use case only when the script exits 0, printed no FAIL line and printed at least one PASS line |
| Every use case names its non-vacuous check | The check that fails when the behaviour breaks, often a refusal paired with the success it guards. Each doc says which check that is |
| The status column is not evidence | It records the last state someone saw; only `make usecase-test` decides |
| Layers that do not exist yet | `sdk` (until `packages/sdk-py` or `packages/sdk-ts` exists) and `cli` (until `packages/ops-cli` exists) report "not available yet; run LAYER=api" and exit 3 when nothing else ran |

## Layout

| Path | Holds |
|---|---|
| `docs/usecases/README.md` | This registry; the runner reads the table below |
| `docs/usecases/<service>/<topic>.md` | The use case, named for its topic, with its id in the header: preconditions, steps and expected results, acceptance layers, non-vacuous check |
| `docs/usecases/<service>/scripts/test-uc-NNN-<layer>.py` or `.mjs` | One script per layer; Python for api, Node with Playwright for ui |
| `docs/usecases/lib/usecase_harness.py` | Checks, the four thread calls, and the scripted services, shared by the Python scripts |
| `packages/usecase-runner/` | Registry parser, layer resolver, PASS/FAIL reporter, exit codes, and the ui harness; `scripts/usecase.mjs` calls it |

Exit codes: 0 every run use case passed, 1 a use case failed or a required script is missing, 2 usage error or a
malformed registry, 3 nothing ran because the requested layer is not available yet.

## Registry

| Id | Service | Title | Layers | Status |
|---|---|---|---|---|
| uc-001 | agents-service | Chat turn with citation | api | passing |
| uc-002 | agents-service | Write tool pauses and approval resumes with step-up | api, ui | passing |
| uc-003 | agents-service | Simple workflow through the four thread calls | api, ui | passing |
| uc-004 | agents-service | Complex workflow with fan-out, grade loop, review pause and send | api | passing |
| uc-005 | agents-service | A pause survives a restart | api | passing |
| uc-006 | agents-service | SLA timer breach escalates | api | passing |
| uc-007 | tools-service | A tool write without a token is refused | api | passing |
| uc-008 | agents-service | A paused workflow is decided from the console | api, ui | passing |
| uc-009 | agents-service | Self-approval is refused | api | passing |
| uc-010 | tools-service | A builder manages a tool module | api, ui | passing |
| uc-011 | tools-service | A tool call runs through the registry and is logged with its caller | api | passing |
| uc-012 | tools-service | A builder imports tools from OpenAPI and MCP and calls them on allowed hosts only | api, ui | passing |
| uc-013 | tools-service | A tool's credential is a secret that never comes back | api, ui | passing |
| uc-015 | tools-service | Tool module details page | ui | passing |
| uc-018 | agents-service | Create, edit, publish an agent and chat with it | api, ui | passing |
| uc-019 | agents-service | Create a workflow from draft JSON, validate, test, publish and start it | api, ui | passing |
| uc-020 | agents-service | Chat starts a workflow | api, ui | passing |
| uc-021 | platform-service | Sign in, session, refresh, sign out | api, ui | passing |
| uc-023 | platform-service | Members and roles | api | passing |
| uc-025 | platform-service | Audit | api | passing |
| uc-026 | platform-service | Anonymous and dev boundary | api | passing |
| uc-027 | agents-service | An approval outlives its token | api | passing |
| uc-028 | agents-service | An agent runs on the model its publisher chose | api | passing |
| uc-038 | tools-service | A failed tool call says which side failed, and a test call reaches the real system (live, OPS_LIVE_EGRESS=1) | api | passing |
| uc-040 | tools-service | Security decides a tool module review | api, ui | passing |
| uc-041 | tools-service | Workflow approvals use agents-service workflows | api | passing |
| uc-042 | tools-service | A module's call counts and activity come from real calls | api | passing |
