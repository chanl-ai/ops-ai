# A workflow step notifies an outside system's webhook with a case's data

Status: passing. Id: `uc-230`. Service: `tools-service`. Layers: api.

The court order demo sends the data read from a notice to an outside system. `notify_webhook` is an operation of the core
bank module: a POST through the gateway, to a host on the egress allow-list, signed with a stored secret, logged like
any call. The bank stand-in's `/webhooks` receiver plays the outside system and lists what it received on a page.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The core bank fake on https as api.bank.test | `core_bank()`; its `/webhooks/{hook}` route is `notify_webhook` in its OpenAPI document |
| The module imported and published | `publish_bank_module()`, which sets `notify_webhook` to run at once as `reimport_bank_module.py` does |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Import the bank's document | `notify_webhook` is a write that runs without a person's approval |
| 2 | Call it with no `LEVY_WEBHOOK_SECRET` stored | The call fails; the receiver holds nothing |
| 3 | Store the secret and call it | Allowed; the receiver holds the payload as sent, with its signing header |
| 4 | Read the call log and the inbox page | Both calls are logged; the page lists the payload |
| 5 | Send the same call again | Answered from the first result; nothing new reaches the receiver |

A team whose toolWritesNeedApproval policy is on still has the call wait for a person, as every write does.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-230-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-230 LAYER=api` (2026-10-18) |

## Non-vacuous check

Step 2 is the receiver refusing an unsigned call: with the operation's header removed, step 3 fails the same way.
