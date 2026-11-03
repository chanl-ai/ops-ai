# A builder runs the two composition Examples

Status: current. Id: `uc-624`. Service: `agents-service`. Layers: sdk.

A builder on a fake stack reuses the R4 citing agent and the R2 three-node workflow. A workflow Agent step
asks A2 and keeps the cited answer. A published agent starts W1 as `workflow:<id>` and returns the three-node
output. Neither path writes or opens a human task. `ops examples` stays unused.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder sets up composition 1, which reuses the citing agent, then a test run returns the cited answer | sdk | 1-2 | 2 |
| S2 | A second composition 1 setup prints FOUND and changes nothing | sdk | 3 | 3 |
| S3 | They set up composition 2, which reuses the three-node workflow, then chat returns that output | sdk | 4-5 | 5 |
| S4 | Neither path opens a human task | sdk | 2, 5 | 5 |
| S5 | A second composition 2 setup prints FOUND and changes nothing | sdk | 6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| Local fake stack | `make up DEMO_MODEL=fake` |
| Sample team | `make sample-team` |
| R4 A2 citing agent | `examples/agents/02-cite-the-handbook` already set up |
| R2 W1 three-node workflow | `examples/workflows/01-normalize-a-request` already set up |
| Public Python SDK | `ops_ai` against the running services |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `uv run python examples/compositions/01-workflow-asks-agent/setup.py` | Prints READY; does not print MADE; reuses A2 |
| 2 | `uv run pytest examples/compositions/01-workflow-asks-agent/test_example.py` | Passes; `ops.workflows.run(..., mode="test")` returns the cited answer; no `taskId` |
| 3 | The same setup again | Prints FOUND; `.bindings.json` is unchanged |
| 4 | `uv run python examples/compositions/02-agent-starts-workflow/setup.py` | Prints READY; does not print MADE; reuses W1 |
| 5 | `uv run pytest examples/compositions/02-agent-starts-workflow/test_example.py` | Passes; `ops.agents.chat` starts `workflow:normalize_support_request` and the child run outcome is `accepted`; no `taskId` |
| 6 | The same setup again | Prints FOUND; nothing added |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| sdk | `agents-service/scripts/test-uc-624-sdk.py` | current |

## Non-vacuous check

Step 2 fails while `test_example.py` only asserts `outcome:` in YAML. Step 5 fails when the agent never
calls `workflow:normalize_support_request`.
