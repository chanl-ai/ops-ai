# The branch policy agent answers from the manual

Status: current. Id: `uc-079`. Service: `console`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| The demo stack | withUiStack's `demo` option, as for uc-078; `services/kb-service/seed/pdfs/fee-schedule-v2.pdf` |
| platform-service's dev seed | Maya Okafor (asks), Nadia Petrov (owns Branch operations); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya asks the Branch Policy agent the outgoing wire fee, the daily ATM limit and how to stop a cheque | each answer cites its document with its page: Fee Schedule p. 1, Branch Operations Manual p. 2 and p. 3 |
| 2 | She asks about a mortgage prepayment penalty | "That is not in the knowledge base." and no citation |
| 3 | Read the rate table | a rows widget with the manual's four debit-card limits (the demo rules present() them after the cited answer) |
| 4 | Nadia uploads fee schedule version 2 under the same name and syncs; Maya asks the fee again | the citation names a newer version of the Fee Schedule |
| 5 | Open Changes, Decided view | a row "Fee Schedule changed from vN to vN+1" (a sync's replacement is recorded as decided) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-079-api.py` (usecase_harness.demo; the v2 schedule through seed_demo_knowledge.py --fees v2) | passing (7/7) |
| ui | `console/scripts/test-uc-079-ui.mjs` | passing (6/6 on withUiStack demo, after 301bd3e) |

## Non-vacuous check

Step 2 fails if the agent cites anyway: the citation count grows after the uncovered question. At the api layer: with the demo knowledge left out of the stack the six evidence checks go red (citations, pages, 30.00, the limits' rows, 35.00 after re-sync); with the uncovered question's rule changed to answer with a citation marker, its check goes red.
