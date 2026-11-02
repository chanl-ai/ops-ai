# Turning an app off names its users, a leaver loses their accounts, and Replace rotates a key

Status: draft. Id: `uc-618`. Service: `tools-service` with platform-service and agents-service. Layers: api, ui.
Card: an earlier change (story group K of the planning repo `docs/plans/ops-ai/apps.html`).

Turning an app off named nothing, so a team found out from failing agents; a person who left a team kept their own
accounts on its apps; and a team key could only be changed by turning the app on again. Now turning an app off first
names the agents and workflows that use its tools, a person leaving a team loses their accounts on every app of that
team, and Replace changes the team's key on the same account.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin sees which agents use an app's tools before turning it off, and turns it off | api | 1-2 | 1 |
| S2 | A person removed from the team loses their own account on the team's apps | api | 3 | 3 |
| S3 | Replace puts a new key on the team account, which keeps its id and works at once | api | 4 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs mock-oauth2-server behind the fake's sign-in host |
| agents-service | beside tools-service, so an agent can hold the app's tool |
| People | dev roles: admin Priya Shah and builder James Richardson (team_ops) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns the header-key desk on; James makes an agent "Records helper" holding its read tool; Priya reads who uses the desk (`GET /v1/plugins/test.header-key/team/users`) | 200, naming Records helper and the tool it holds |
| 2 | She turns it off (`PUT /v1/plugins/test.header-key/team` with enabled false) | 200; the app reads off |
| 3 | Priya turns the person-key desk on for person sign-in; James saves his key; Priya removes James from team_ops | Within seconds (platform-service's `member.removed`, relayed to tools-service) his account on the desk is gone: the app page counts no people |
| 4 | Priya turns the header-key desk on with a wrong key; a run's call fails; she replaces the key (`PUT /v1/plugins/test.header-key/team` with the right key) | The account id is unchanged and the next call reads the record |
| 5 | The console steps (the turn-off dialog naming the agents, Replace on the app's Secrets) | Written by the console builder |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-618-api.py` | passes (steps 1-4) |
| ui | not written | console builder |

## Non-vacuous check

Step 1: the users answer must name the agent that holds the tool; an answer that names nothing fails it.
