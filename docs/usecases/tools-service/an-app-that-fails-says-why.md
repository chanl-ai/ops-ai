# An app that fails says why: an expired account, a run waiting for a person's account, an unknown host

Status: draft. Id: `uc-617`. Service: `tools-service` with agents-service. Layers: api, ui.

When an app's account stopped working, a run failed with a generic error and nobody was told. Now the app shows
Expired or Refused with Reconnect, an admin is told, and a run stops saying the app needs reconnecting. A run a person
started that needs their own account pauses on a "connect your account" task instead of failing, and an app's first
address on a host nobody has listed asks a Security admin instead of failing.

The stack is `docs/usecases/lib/apps_walk.py`: the test plugins and the fake system, whose sign-in server refuses a
wrong client secret with `invalid_client`, with agents-service and its workflow worker beside tools-service.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team account the app refuses shows Refused with Reconnect, and a run's call says the app needs reconnecting | api | 1-2 | 2 |
| S2 | A run a person started that needs their account waits for them instead of failing, shows in Human Tasks as a connect task, and goes on once they connect; Run as the team account is allowed only by role, on an app with a team account | api | 3 | 3 |
| S3 | An app's first address on a host nobody listed is held for a Security admin instead of failing; approving lists the host and the retry saves, refusing gives the reason against the run key | api | 4 | 4 |
| S4 | In the console, the save says it waits for Security; Human Tasks shows the host, the app and who asked with Approve and Refuse; the next save shows the refusal's reason or goes through | ui | 6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs mock-oauth2-server behind the fake's sign-in host |
| People | dev roles: admin Priya Shah and builder James Richardson (team_ops), security Sam Adeyemi |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns the client desk (`test.client`) on with a wrong client secret; a run calls its read tool; Priya reads `GET /v1/apps/plugin:test.client` | The call fails; the team account's state is refused, with the sign-in server's reason |
| 2 | The run's refusal is read | Its message says Client desk needs reconnecting, not a generic error, and names no secret |
| 3 | A workflow run James started reaches the person key desk's read tool before he connected; then he gives his key on My accounts | The run waits on `app_account.connected` titled "Connect your Person key desk account to continue", not failed; Human Tasks lists it as a `connect_account` task naming the desk and James, with no deadline (3b); `POST /reviews/{id}/team-account` is 403 for James (connections.run) and 409 `no_team_account` for Priya, and a decision is 409 `connect_wait` (3c); once he gives his key it goes on by itself and reads the record (3a). On the person desk with its team account signed in and backing its people, Priya's own waiting run runs as the team account and reads the record (3d) |
| 4 | James (builder, no Security role) adds a REST tool on `unlisted.multi.test` (`POST /v1/tool-modules`; its own custom app keeps the address), twice | 202 `{heldFor: "security", host, runKey}`, the same run key both times, nothing saved; Sam Adeyemi's Human Tasks lists the run key as an `egress_host` task, pending, naming the host and the app |
| 4a | Sam approves the task (`POST /reviews/{runKey}/decision`, approved); James adds the tool again | The host is on the tenant's allow-list, added by Sam; the add answers 201 |
| 4b | James adds a REST tool on `refused.multi.test`; Sam refuses it with a reason; James adds it again | The task keeps Sam's reason; the retry answers 422 `egress_host_refused` naming the reason and the run key |
| 4c | Sam, who holds the Security role, adds a custom app and a tool on `listed.multi.test` | 201 at once; the host is listed in Sam's name; no task opens (roles decide) |
| 6 | James saves a REST tool on `held.uc617.example` from Import operations | Before saving, the notice says saving asks a Security admin; after, the dialog reads "Waiting for Security to allow held.uc617.example", nothing is saved, and Sam has a pending task |
| 6a | Sam opens the task in Human Tasks and refuses it with a reason | The task shows the host, the app and who asked, with Approve and Refuse and no Return; the task keeps the reason |
| 6b | James saves the same tool again | The dialog shows Security's refusal with Sam's reason |
| 6c | James saves a tool on `allowed.uc617.example`; Sam approves its task; James saves again | The host is listed and the save opens the new tool's page |
| 8 | Priya turns the Pager plugin (`test.pager`) on, takes three of its five read tools out again, then on its app page's Tools tab ticks Select all and presses Add | Only the tools not added are picked: the bar reads "3 selected" and "Add (3)", each added tool's box is off and disabled; after Add every Pager tool is added (`GET /v1/apps/plugin:test.pager`) |
| 5 | The console steps: Expired with Reconnect on the app page, and the waiting run's Human Task with Connect my account and Run as the team account | Walked by uc-607 ui: step 21 (Expired, Reconnect) and step 13c (the task, Run as the team account, the run goes on); the run's reason and the Security task are not walked yet |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-617-api.py` | steps 1-4c pass |
| ui | `tools-service/scripts/test-uc-617-ui.mjs` | steps 6-6c and 8 |

## Non-vacuous check

Step 2 reads the refusal's message: the generic `AUTH_FAILED` text answered today fails it.
