# Connect your own Salesforce account

Status: current. Service: `tools-service`. Layers: api, sdk, cli, ui.

In this example we will start a workflow that updates a Salesforce case, as two people who have not connected their own
Salesforce account yet. It assumes a team that set Salesforce to "Each person's own account" and published its update
tool.

| Use case | |
|---|---|
| Id | `uc-558` |
| Area | Tools and apps |
| Runs | Python, TypeScript, CLI; the api and console steps are in their own scripts |
| Run it | `make usecase-test UC=uc-558` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| James, a claims handler | Builder | the `james` profile |
| Wanjiru, a supervisor | Admin | the `wanjiru` profile |
| Priya, the team admin | Admin | the `priya` profile |

The run gives each person a profile with their own sign-in on a stack it starts for itself: platform-service signing
people in, tools-service, agents-service and a worker, and a fake Salesforce. The team's hosts, Salesforce app, update
tool and the `case_update` workflow are already live. Nobody has connected.

## Before you start

```python tab="Python" tab-group="language"
from ops_ai import OpsAI

james = OpsAI(profile="james")
wanjiru = OpsAI(profile="wanjiru")
```

```ts tab="TypeScript"
import assert from 'node:assert/strict';
import { OpsAI } from '@chanl-ai/ops-ai';

const james = new OpsAI({ profile: 'james' });
const wanjiru = new OpsAI({ profile: 'wanjiru' });
```

```bash tab="CLI"
set -euo pipefail
```

## Steps

### 1. Start a case update as someone who has not connected

James starts the workflow live. It does not go on as the team or as anyone else: it waits for James to connect his own
account, naming the account and the event his connecting reports.

```python tab="Python" tab-group="language"
started = james.runs.start("case_update", input={"status": "Awaiting documents"}, mode="live")
waiting = james.runs.wait(started["runId"], timeout=60)
assert waiting["status"] == "waiting"
assert waiting["waiting"]["payload"]["event"] == "app_account.connected"
```

```ts tab="TypeScript"
const started = await james.runs.start('case_update', { input: { status: 'Awaiting documents' }, mode: 'live' });
const waiting = (await james.runs.wait(started.runId, { timeoutMs: 60_000 })) as Record<string, any>;
assert.equal(waiting.status, 'waiting');
assert.equal(waiting.waiting.payload.event, 'app_account.connected');
```

```bash tab="CLI"
OPS_PROFILE=james opsai runs start case_update --input status="Awaiting documents" --live --wait --json | jq -e '.status == "waiting" and .waiting.payload.event == "app_account.connected"'
```

Expected: the run is waiting on `app_account.connected`, and nothing has reached Salesforce.

### 2. Another person's run waits for them, not on James

Wanjiru starts the same workflow. Her run waits for her own account; James's sign-in, when he makes it, is never used
for her. Her connectors list shows Salesforce with no account connected.

```python tab="Python" tab-group="language"
hers = wanjiru.runs.start("case_update", input={"status": "Awaiting documents"}, mode="live")
assert wanjiru.runs.wait(hers["runId"], timeout=60)["status"] == "waiting"
card = next(c for c in wanjiru.me.connectors.list() if c["name"] == "Salesforce claims")
assert card["accountCount"] == 0
```

```ts tab="TypeScript"
const hers = await wanjiru.runs.start('case_update', { input: { status: 'Awaiting documents' }, mode: 'live' });
assert.equal(((await wanjiru.runs.wait(hers.runId, { timeoutMs: 60_000 })) as Record<string, any>).status, 'waiting');
const card = (await wanjiru.me.connectors.list()).find((c) => c.name === 'Salesforce claims');
assert.equal(card?.accountCount, 0);
```

```bash tab="CLI"
OPS_PROFILE=wanjiru opsai runs start case_update --input status="Awaiting documents" --live --wait --json | jq -e '.status == "waiting"'
OPS_PROFILE=wanjiru opsai connectors list --json | jq -e 'map(select(.name == "Salesforce claims"))[0].accountCount == 0'
```

Expected: both runs wait; Wanjiru's card has no connected account.

## Gaps

| Product fix | Step | What the SDKs and the command line cannot do |
|---|---|---|
| A `connect` call in `ops.me.connectors` and `opsai connectors connect`, taking the account's link, returning the sign-in address and finishing the sign-in | Connect | James cannot open his connect link, sign in to Salesforce and finish the sign-in: `ops.raw.tools` has no call for a connect link or `sign-ins/complete`, and `opsai connectors` has only `list` and `disconnect`. The steps after it (his waiting run goes on as him, Salesforce records him as the editor, his sign-in is listed, Disconnect makes his next run wait) cannot be written on this page |

A call that acts for a person is made by agents-service with a token platform-service signs, never by a person, so "a
request body cannot choose whose" (api step 7) stays in the api script.

## What proves it

Step 1 fails if a run for someone who has not connected goes on as the team or as another person: the status would not be
`waiting`. Step 2 fails if Wanjiru's run is answered by James's connecting.

## Details

| | |
|---|---|
| Services the run starts | tools stack: platform-service, tools-service, agents-service and a worker, with a fake Salesforce (navikt mock-oauth2-server behind an https front) |
| Api script | `docs/usecases/tools-service/scripts/test-uc-558-api.py` (steps 1 to 11 below) |
| Console script | `docs/usecases/tools-service/scripts/test-uc-558-ui.mjs` |

## Api and console steps


A Salesforce account set to "Each person's own account" signs each call in as the person it acts for, so Salesforce
records that person as the editor and applies their own permissions. A call for a person who has not connected gets
`CONNECTION_NOT_LINKED` with a connect link made for them alone, and a run for them waits until they connect, then goes
on with their token. Whom a call acts for comes only from a token platform-service signs for a member of the team, never from
the request body.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A person who has not connected is asked with a link made for them alone, their run waits, and once they connect the run goes on as them | api | 1-4 | 4 |
| S2 | Each person's calls use their own sign-in, and a request body cannot choose whose | api | 5-7 | 7 |
| S3 | An admin tests the connection, and a run with nobody behind it uses the team account only when the backup is on | api | 8-9 | 9 |
| S4 | A sign-in that lacks a scope is asked again, and a person who disconnects has their next run wait for them | api | 10-11 | 11 |
| S5 | A person asked in chat connects in a pop-up and the chat goes on as them | ui | 12-13, 15 | 13 |
| S6 | A person sees their own sign-ins in My accounts and disconnects one | ui | 14, 16 | 16 |
| S7 | An admin sets who signs in on the app's Settings and connects their own account there | ui | 17-18 | 18 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs the OAuth server |
| platform-service signing people in; tools-service and agents-service verifying its tokens | `platform()`, `tools()` and `agents()` with `OPS_AUTH_MODE=platform`, as uc-410 does |
| A fake Salesforce | `fake_salesforce.salesforce()`: navikt mock-oauth2-server behind `https://login.salesforce.test`, the REST API at `https://kestrel.my.salesforce.test`, accepting only that server's tokens and recording each case edit's account |
| A worker | `python -m ops_agents.api.worker` on the run's database and gateway |
| People | Priya (team_ops admin), James (builder), Wanjiru (admin in every team), Ravi (viewer), Sam (adds egress hosts), Nadia (Security approver of the module review) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| setup | Priya lists the hosts, adds the Salesforce app with `signIn: person` and its OAuth app, and publishes `uc558_update_case` (PATCH a case, scope `cases.write`); Nadia approves it; Priya publishes the `uc558_case_update` workflow | The account reads `signIn: person`; module and workflow live |
| 1 | James starts a run | It waits for James to connect, naming the app's account and the event his connecting reports; nothing reaches Salesforce |
| 2 | A call acting for James (as a chat makes one); Ravi opens the link it answers | `CONNECTION_NOT_LINKED` with a connect link asking for the account's scopes and the operation's `cases.write`; Ravi is refused (`connect_link_not_yours`) and no sign-in starts |
| 3 | James opens his link, signs in to Salesforce as `handler@kestrel.example` with `cases.write`, and finishes the sign-in | 200; the account shows James's sign-in, not a team one |
| 4 | James's waiting run | It goes on and ends `updated`; Salesforce records `handler@kestrel.example` as the editor; the call log says `credential` person, acting for James |
| 5 | Wanjiru starts a run | It waits for Wanjiru: James's token is never used for her |
| 6 | Wanjiru connects as `supervisor@kestrel.example` with the link a call for her answers | Her waiting run goes on; Salesforce records `supervisor@kestrel.example` |
| 7 | A call sent with a service token whose body names James as `actingFor` | Refused (an unknown field, or `CONNECTION_NOT_LINKED`); no edit reaches Salesforce |
| 8 | Priya signs in her own account and presses Test connection | The userinfo read answers 200 with Priya's own account named; the result is stored on the account |
| 9 | A call with nobody behind it (service token, no acting-for), backup off | `CONNECTION_NOT_LINKED`; after Priya turns the backup on and signs in the team account, the same call uses the team account |
| 9b | The update operation is marked `needsPerson` and republished; the same call with nobody behind it, backup still on | `CONNECTION_NOT_LINKED` with reason `needs_person`; the team account is not used |
| 10 | Priya, signed in from the account itself in step 8 (its scopes only, no `cases.write`): a call for her, then a run | `CONNECTION_NOT_LINKED` with reason `insufficient_scope` and a link asking for `cases.write`; her run waits for her |
| 11 | James lists `GET /v1/me/accounts`, then disconnects | His Salesforce sign-in is listed; after Disconnect his next run waits for him to connect again |
| 12 | James asks a chat agent holding the update operation to move a case | The reply shows the Connect Salesforce card; nothing reaches Salesforce |
| 13 | He presses Connect, signs in to Salesforce in the pop-up as `handler@kestrel.example` | The pop-up closes, the card reads Connected, the chat sends a follow-up and the agent's new call updates the case: Salesforce records exactly one edit, his |
| 14 | He opens My connectors from the person menu | His Salesforce card is listed with the account he signed in as |
| 15 | At 375 px, My connectors and the chat with the card | Neither page scrolls sideways |
| 16 | He opens the card's menu, chooses Disconnect and confirms | His card offers Connect again and `GET /v1/me/accounts` returns none |
| 17 | Priya opens the app's page, then Settings, and turns People can connect their own account off and on | It reads on; off saves `team`, on saves `person_or_team` (team backup on) |
| 18 | Priya opens My connectors and presses Connect on the card | The card reads `lead@kestrel.example`, and `GET /v1/me/accounts` lists it |
| 19 | Retired: the console switch was removed (af724998) | |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-558-api.py` | passing (2026-10-29) |
| ui | `tools-service/scripts/test-uc-558-ui.mjs` | passing (2026-11-12), 11 checks |

## Non-vacuous check

Step 4 reads the editor from the fake Salesforce, which takes it from the bearer token's subject, so a call made with
the team's or another person's token fails it. Step 7 fails if tools-service reads `actingFor` from the body.
