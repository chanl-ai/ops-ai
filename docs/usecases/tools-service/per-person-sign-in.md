# People connect their own Salesforce account

Status: current. Id: `uc-558`. Service: `tools-service`. Layers: api, ui.
Card: an earlier change.

A Salesforce connection set to "Each person's own account" signs each call in as the person it acts for, so Salesforce
records that person as the editor and applies their own permissions. A person who has not connected gets
`CONNECTION_NOT_LINKED` with a connect link made for them alone; after they sign in, the same call goes through with
their token. Whom a call acts for comes only from a token platform-service signs for a member of the team, never from
the request body.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A person who has not connected is refused with a link made for them alone, and once connected the call acts as them | api | 1-4 | 4 |
| S2 | Each person's calls use their own sign-in, and a request body cannot choose whose | api | 5-7 | 7 |
| S3 | An admin tests the connection, and a run with nobody behind it uses the team account only when the backup is on | api | 8-9 | 9 |
| S4 | A sign-in that lacks a scope is asked again, and a person who disconnects is asked again | api | 10-11 | 11 |
| S5 | A person asked in chat connects in a pop-up and the chat goes on as them | ui | 12-13, 15 | 13 |
| S6 | A person sees their own sign-ins in Your connections and disconnects one | ui | 14, 16 | 16 |
| S7 | An admin sets whose account a connection uses and tests it with their own | ui | 17-18 | 18 |
| S8 | With the console switch off, none of this shows | ui | 19 | 19 |

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
| setup | Priya lists the hosts, creates the Salesforce connection with `signIn: person` and its production OAuth app, and publishes `uc558_update_case` (PATCH a case, scope `cases.write`); Nadia approves it; Priya publishes the `uc558_case_update` workflow | The connection reads `signIn: person`; module and workflow live |
| 1 | James starts a run | The tool step answers `CONNECTION_NOT_LINKED` with a connect link asking for the connection's scopes and the operation's `cases.write`; nothing reaches Salesforce |
| 2 | Ravi opens James's link | Refused (`connect_link_not_yours`); no sign-in starts |
| 3 | James opens his link, signs in to Salesforce as `handler@kestrel.example` with `cases.write`, and finishes the sign-in | 200; the connection shows James's sign-in, not a team one |
| 4 | James starts the run again | It ends `updated`; Salesforce records `handler@kestrel.example` as the editor; the call log says `credential` person, acting for James |
| 5 | Wanjiru starts a run | `CONNECTION_NOT_LINKED` for Wanjiru: James's token is never used for her |
| 6 | Wanjiru connects as `supervisor@kestrel.example` and runs again | Salesforce records `supervisor@kestrel.example` |
| 7 | A call sent with a service token whose body names James as `actingFor` | Refused (an unknown field, or `CONNECTION_NOT_LINKED`); no edit reaches Salesforce |
| 8 | Priya signs in her own account and presses Test connection | The userinfo read answers 200 with Priya's own account named; the result is stored on the connection |
| 9 | A call with nobody behind it (service token, no acting-for), backup off | `CONNECTION_NOT_LINKED`; after Priya turns the backup on and signs in the team account, the same call uses the team account |
| 9b | The update operation is marked `needsPerson` and republished; the same call with nobody behind it, backup still on | `CONNECTION_NOT_LINKED` with reason `needs_person`; the team account is not used |
| 10 | Priya, signed in from the connection itself in step 8 (its scopes only, no `cases.write`), runs | `CONNECTION_NOT_LINKED` with reason `insufficient_scope` and a link asking for `cases.write` |
| 11 | James lists `GET /v1/me/connections`, then disconnects | His Salesforce sign-in is listed; after Disconnect his next run asks him to connect again |
| 12 | With `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` on, James asks a chat agent holding the update operation to move a case | The reply shows the Connect Salesforce card; nothing reaches Salesforce |
| 13 | He presses Connect, signs in to Salesforce in the pop-up as `handler@kestrel.example` | The pop-up closes, the card reads Connected, the chat sends a follow-up and the agent's new call updates the case: Salesforce records exactly one edit, his |
| 14 | He opens Your connections from the person menu | His Salesforce sign-in is listed with its account |
| 15 | At 375 px, Your connections and the chat with the card | Neither page scrolls sideways |
| 16 | He disconnects on Your connections | The list is empty and `GET /v1/me/connections` returns none |
| 17 | Priya opens the connection's page and chooses "Each person, team account as backup" | Three settings are offered with "Each person's own account" chosen; after Save the connection reads `person_or_team` with the backup on |
| 18 | She connects her own account from the page and presses Test connection | The page shows 200; the connection keeps a passing health with her own account |
| 19 | The console built without the switch | No Your connections in the person menu, and its page is not found |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-558-api.py` | passing (2026-10-29) |
| ui | `tools-service/scripts/test-uc-558-ui.mjs` | passing (2026-10-29); the console switch `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` on |

## Non-vacuous check

Step 4 reads the editor from the fake Salesforce, which takes it from the bearer token's subject, so a call made with
the team's or another person's token fails it. Step 7 fails if tools-service reads `actingFor` from the body.
