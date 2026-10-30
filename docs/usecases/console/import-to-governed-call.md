# A builder takes a bank API from import to a governed agent call

Status: current. Id: `uc-086`. Service: `console`. Layers: ui.

an earlier change's path in one run, as the seeded people, in the console: the bank's keys stored as secrets, its OpenAPI
document imported, reviewed and published, a second version published, the reads tried and granted to an agent, a
chat write held until a second person approves it, and the call log naming who asked, who approved and how each call
ended. The design is [tool lifecycle](../../architecture/tool-lifecycle.md). It replaces uc-055 as the card's gate;
uc-055's last step belongs to the agent page.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Maya Okafor (approver) on Operations, Nadia Petrov (approver) on Security, Priya Shah (admin), Sam Adeyemi (admin on Security, the only one who changes egress); password `northfield-demo` |
| The core-banking fake on https | the ui harness's `tools: { bank: 'core' }` (`services/tools-service/scripts/fake_bank`): an `X-Api-Key` header on most routes, an `api_key` query key on `get_statement`, holds that later reads return; key `dev-bank-key` |
| Agents granted from tools-service | the ui harness's `tools: { gateway: true }` |
| No model calls | the scripted model; a chat message `call <tool> <json>` calls that tool |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam (Security admin) allows the bank's host and range | 201 |
| 2 | James adds `BANK_API_KEY` and `STATEMENTS_API_KEY` in Settings > Secrets, as Operations' secrets: a secret belongs to the team that uses it | 201 each; no response or page shows the value |
| 3 | James imports `https://api.bank.test/openapi.json`, ticks `place_hold`, unticks `get_statement`, saves the draft | 201; reads are Read, `place_hold` is Write |
| 4 | James requests a security review; Nadia approves it on the module's Approval tab | the module is published |
| 5 | James imports `get_statement` into the module and publishes a version | the version is listed on the Versions tab; `get_statement` has no `api_key` input |
| 6 | James runs `get_account` and `get_statement` from the test panel against the test environment | both reach the bank (a missing or wrong key answers 401); the URL the statement route repeats shows `api_key=[secret]` |
| 7 | James grants `get_account`, `get_statement` and `place_hold` to Branch Concierge and publishes it | the agent holds the three |
| 8 | James asks `call get_account {"account_id": "CHQ-2219"}` | "Here is what I found."; one call by the agent in the log |
| 9 | James asks `call place_hold {...25...}` | an approval card; no call logged and no new hold at the bank |
| 10 | Maya approves it in Reviews | one call runs and the bank holds exactly one new hold of 25 |
| 11 | James opens the module's Activity tab | the write's row names the agent that made it, Maya (by her sign-in email) as approver and the outcome, and links to the chat thread. The person who asked is not shown yet: the caller is the agents service until the runner signs a run context naming the user (planned, data-and-ai-gateways 4.3) |
| 12 | Every page | no page error, and the key never appears |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-086-ui.mjs` | passing |

## Non-vacuous check

Step 6's statement call answers 401 from the bank unless `{{STATEMENTS_API_KEY}}` in the query is resolved, and its
`requestedUrl` carries the key unless the gateway scrubs it. Step 10 counts holds at the bank itself, so a write that
ran twice or not at all fails it.
