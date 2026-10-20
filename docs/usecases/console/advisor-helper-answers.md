# The advisor's helper answers about a customer

Status: current. Id: `uc-078`. Service: `console`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| The demo stack | withUiStack's `demo` option: kb-service and models-service with the fake OpenAI (`services/models-service/seed/demo-fake-openai`), the demo seeds run against the run's ports |
| platform-service's dev seed | James Richardson; password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James asks the Advisor's Helper "What does Priya Natarajan have with us?" | her record (CUS-1002) draws as fields, her accounts (BUS-7781) as a table, and the summary ("Priya Natarajan holds one … account") follows |
| 2 | He asks to compare Savings Plus and Money Market | the answer cites the Retail Product Sheet with page 4 |
| 3 | Read the comparison | a table widget compares the two accounts |

The comparison table comes through the model's present() tool (c-055 T021). get_customer's record carries accountIds
and each account row carries holds; the shaper joins lists into a cell and counts objects (c-055 T024).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-078-api.py` (usecase_harness.demo: fake OpenAI demo rules, core bank through tools-service, demo knowledge) | passing (5/5) |
| ui | `console/scripts/test-uc-078-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails if tool results do not reach the message as parts: no record or table widget draws. At the api layer every check was seen failing with the bank module and the demo knowledge left out of the stack (5/5 red): the parts carry the bank's id and balance, the text quotes the balance from the tool result, and the comparison's rows and page come from the product sheet's passage.
