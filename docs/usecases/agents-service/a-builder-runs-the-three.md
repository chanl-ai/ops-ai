# A builder runs the three foundation Examples

Status: current. Id: `uc-621`. Service: `agents-service`. Layers: sdk. Card: an earlier change (R1).

A builder on a fresh fake stack sends one message, searches the account-opening handbook, and calls the sample-team
read tool. Each Example folder's setup prints READY, its public test uses the SDK (not YAML alone), and a second
setup prints FOUND and changes nothing. None of the three folders teach approval, roles, or evaluation.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder runs chat setup, sends the fixture message through the public SDK, and reads a reply | sdk | 1-3 | 2 |
| S2 | They add or find the account-opening handbook, search "beneficial owners", and see a passage | sdk | 4-6 | 5 |
| S3 | They call the sample-team read tool with ada@example.test and get that customer | sdk | 7-9 | 8 |
| S4 | A second setup of each folder prints FOUND and writes no new bindings | sdk | 10 | 10 |

## Preconditions

| Needs | How |
|---|---|
| Local fake stack | `make up DEMO_MODEL=fake` |
| Sample team | `make sample-team` |
| Public Python SDK | `ops_ai` against the running services |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `uv run python examples/chat/01-ask-once/setup.py` | Prints READY; does not print MADE |
| 2 | `uv run pytest examples/chat/01-ask-once/test_example.py` | Passes; public SDK send returns a reply (`hasReply`) |
| 3 | The same setup again | Prints FOUND; `.bindings.json` is unchanged |
| 4 | `uv run python examples/knowledge/01-search-a-page/setup.py` | Prints READY; reuses the account-opening handbook |
| 5 | `uv run pytest examples/knowledge/01-search-a-page/test_example.py` | Passes; search returns a passage (`hasPassage`) |
| 6 | The same setup again | Prints FOUND; nothing added |
| 7 | `uv run python examples/tools/01-find-a-customer/setup.py` | Prints READY; reuses `search_customers` |
| 8 | `uv run pytest examples/tools/01-find-a-customer/test_example.py` | Passes; the record email is `ada@example.test` |
| 9 | The same setup again | Prints FOUND; nothing added |
| 10 | The three READMEs | No approval, roles, or evaluation as a required lesson |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| sdk | `agents-service/scripts/test-uc-621-sdk.py` | current |

## Non-vacuous check

Step 2 fails while `test_example.py` only asserts `outcome:` in YAML. Step 8 fails when the fake bank has no
`ada@example.test`. Step 1 fails when first setup prints MADE instead of READY.
