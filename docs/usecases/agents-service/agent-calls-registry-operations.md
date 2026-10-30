# An agent is granted and calls a published tools-service operation

Status: passing. Id: `uc-048`. Service: `agents-service`. Layers: api. Card: an earlier change (G1).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| agents-service on the scripted model, with tools-service as its gateway | started by the script on the run's own ports (`agents(gateway_url=...)`) |
| A bank system on https | the fake bank (`lib/fake_bank_https.py`), listed on egress with its private range |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A module with one read and one write on the fake bank, sent to review; `GET /v1/tools` on agents-service | neither operation offered; no fixture-only tool (`lookup_account`) offered either |
| 2 | Security approves the review; after agents-service's 30 s cache, `GET /v1/tools` | the read offered with its module name, access `read` and input schema (`accountId` required); the write marked as needing approval |
| 3 | `PATCH /v1/agents/{id}` granting `lookup_account` | 400 `unknown_tool` |
| 4 | Grant the two operations and publish the agent | 200, then 201 |
| 5 | Chat: the scripted model calls the read | `tool_start` names it, the fake bank receives `GET /v1/accounts/CHQ-2219`, tools-service logs it allowed and ok |
| 6 | Chat: the scripted model calls the write | the turn stops for approval; the fake bank receives no POST |

The scripted model calls a granted tool when the message reads `call <tool> <json>` (`tests/conftest.py`), so the
use case checks the plumbing, not a model's choice; no provider is called.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-048-api.py` | passing |

In the console: uc-055's and uc-086's ui scripts: the operation is granted from the agent page's tools picker, and a chat read runs it through the gateway.

## Non-vacuous check

`the approval card shows the input the call will send` was seen failing (no fields) with the generic card's field list removed.
Step 1's fixture check was seen failing on a database where the old tools-service dev seed had written the "Runtime
demo tools" module (`lookup_account` offered), and step 3 then accepted the grant (200). Steps 2 and 5 cannot pass
with agents-service's fixture catalogue: the operation exists only in tools-service.
