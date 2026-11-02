# An agent with many tools finds the one it needs by searching, and runs it through the same checks

Status: passing. Id: `uc-610`. Service: `agents-service`. Layers: api. Card: an earlier change.

Above OPS_TOOL_SEARCH_ABOVE granted tools (default 20), an agent is offered only its built-ins; it searches its tools
by words, the matches are revealed with their inputs, and it calls the one it needs by its own name, through the same
approval, person sign-in, tool budget and audit as any call.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent holding the bank's tools is sent none of their schemas until it searches | api | 1 | 1 |
| S2 | It searches, finds the right tool for each question, and the call runs through the gateway | api | 2-3 | 2 |
| S3 | A write it finds still pauses for a person's approval and runs once after it | api | 4-5 | 5 |
| S4 | A tool the agent is not granted is never found, and calling it by name is refused clearly | api | 6-7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The banker demo's stack | harness `demo()`: models-service on the fake OpenAI with the committed demo rules (the `uc610` ones), tools-service with the core bank module published, kb-service |
| Search mode | The script sets OPS_TOOL_SEARCH_ABOVE=3 for the stack, so `ag_advisor`, granted every bank operation but `open_dispute`, searches |

No real model is called. The fake calls a tool only when it is offered, which is how step 1 shows what the first request
held.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Chat "uc610 balance of BUS-7781" | The first call is `search_tools`, not `get_account`: the rule that calls `get_account` at once did not fire, so it was not offered |
| 2 | (same turn) | The search returns `get_account`, which then runs (`success`) and returns BUS-7781's balance; the reply answers |
| 3 | Chat "uc610 notes for CUS-1002" | `search_tools`, then `list_customer_notes` (`success`) |
| 4 | Chat "uc610 hold on BUS-7781" | `search_tools` finds `place_hold`; the turn pauses on an approval card |
| 5 | Maya approves (with a step-up when asked) | The resumed turn runs `place_hold` once (`success`) and says the hold is in place |
| 6 | Chat "uc610 dispute on TX-1" | `search_tools` returns no `open_dispute`, and nothing calls it |
| 7 | Chat "uc610 force dispute on TX-1" (a forced rule calls `open_dispute` by name) | The call is refused (not `success`), nothing reaches the gateway, and the reply finishes with no error event |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-610-api.py` | passing, `make usecase-test UC=uc-610 LAYER=api` (2026-11-01) |

## Non-vacuous check

Step 1: with deferral off (`tool.defer_loading` always false in `ops_agent_kernel/kernel.py`), the first rule calls
`get_account` before any search and the step fails; the kernel unit tests for the same case went red the same way
(`services/agents-service/tests/unit/test_tool_search_mode.py`, seen 2026-11-01).
