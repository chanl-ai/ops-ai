# An agent reads with a tool, asks for approval, and the write runs only after approval, in mock and real mode

Status: current. Id: `uc-753`. Service: `tools-service`. Layers: api, sdk, cli, ui.

Short title: An agent reads with a tool, asks for approval, and the write runs only after approval, in mock and real mode

## Story

As an account desk agent, I read an account at once and a freeze waits for a person to approve it.

## People

| Person | Role | Does what |
|---|---|---|
| Maya Okafor | reviewer | Approves the write with a step-up |

## In this example

A tool module on a mock upstream has a read (balance) and a write (a hold) whose approval switch is on with one approver. An agent holding both is asked to read, then to freeze.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The read answers at once, the write waits, runs once after approval and is logged | api | 1-5 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Mode switch

`MODE=mock` (default): scripted model, mock upstream (`lib/fake_bank_https.py`, `lib/main_chains.py`). `MODE=real` (`APPROVED_REAL_CALLS` 1 to 40): a real model and the Salesforce test org (`make sf-signin-env AS=<person>`): a read, then an approved write on a test record. Real mode is **not built**: `make sf-signin-env` reads its keys from a `.env` file, which this repo forbids, and no model alias key is available on this machine.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `call <read>` | Succeeds with the upstream balance and no approval card |
| 2 | `call <write>` | A pending approval card |
| 3 | The upstream is read | No hold received while the card waits |
| 4 | Maya approves with a step-up | The card is approved and the upstream holds exactly one hold |
| 5 | The call log is read per tool | One allow/ok row for the read and one for the write |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-753-api.py` | passing |
| sdk | `tools-service/scripts/test-uc-753-sdk.py` | passing |
| cli | `tools-service/scripts/test-uc-753-cli.py` | passing |
| ui | `tools-service/scripts/test-uc-753-ui.mjs` | passing |

## Open

The api script runs tools-service without platform-service, which the fail-closed rule (503 approval_rules_unavailable) refuses for a write without its own approval switch; its write has the switch on, so it still waits for approval. The sdk and cli scripts run on `bank_stack` (platform sign-in).

## Non-vacuous check

Step 3 pairs with step 4: the upstream saw no hold while the card was pending, so the one hold is the approval's doing.
