# A builder asks the first three published agents

Status: current. Id: `uc-622`. Service: `agents-service`. Layers: sdk. Card: an earlier change (R4).

A builder on a fake stack publishes three agents that reuse the R1 handbook and read tool. Each answers through
`ops.agents.chat`. A2 cites the account-opening page. A3 calls `search_customers`. A missing page or customer takes
the documented failure. `ops chat send` stays Planned.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder publishes the instructions-only agent, asks one question through the public chat SDK, and reads a reply | sdk | 1-3 | 2 |
| S2 | They attach the R1 handbook, ask a question the page answers, and see a citation | sdk | 4-5, 7 | 5 |
| S3 | A question the page does not answer takes the documented no-answer | sdk | 6 | 6 |
| S4 | They grant the R1 read tool, the agent calls it for Ada, and a missing customer takes the documented failure | sdk | 8-10 | 9 |

## Preconditions

| Needs | How |
|---|---|
| Local fake stack | `make up DEMO_MODEL=fake` |
| Sample team | `make sample-team` |
| R1 handbook and read tool | Account opening handbook and `search_customers` from sample-team / R1 |
| Public Python SDK | `ops_ai` against the running services |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `uv run python examples/agents/01-answer-from-instructions/setup.py` | Prints READY; does not print MADE |
| 2 | `uv run pytest examples/agents/01-answer-from-instructions/test_example.py` | Passes; `ops.agents.chat` returns a reply (`hasReply`) |
| 3 | The same setup again | Prints FOUND; `.bindings.json` is unchanged |
| 4 | `uv run python examples/agents/02-cite-the-handbook/setup.py` | Prints READY; reuses the account-opening handbook |
| 5 | `uv run pytest examples/agents/02-cite-the-handbook/test_example.py` | Passes; the reply cites the R1 page |
| 6 | The missing-page fixture | Documented no-answer; no citation |
| 7 | The same setup again | Prints FOUND; nothing added |
| 8 | `uv run python examples/agents/03-look-up-a-customer/setup.py` | Prints READY; reuses `search_customers` |
| 9 | `uv run pytest examples/agents/03-look-up-a-customer/test_example.py` | Passes; the agent calls the read tool; a missing customer fails as documented |
| 10 | The same setup again | Prints FOUND; nothing added |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| sdk | `agents-service/scripts/test-uc-622-sdk.py` | current |

## Non-vacuous check

Step 2 fails while `test_example.py` only asserts `outcome:` in YAML. Step 5 fails when the agent has no handbook.
Step 9 fails when the agent never calls `search_customers`.
