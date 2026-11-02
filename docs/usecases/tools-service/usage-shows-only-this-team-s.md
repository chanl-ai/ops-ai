# Usage shows only this team's tool calls and whom each ran as

Status: draft. Id: `uc-616`. Service: `tools-service`. Layers: api, sdk, ui. Card: an earlier change (story group G of
the planning repo `docs/plans/ops-ai/apps.html`).

Usage listed every team's tool calls, and its "By" column showed the calling service's id. A team now sees only its
own calls, each saying whom it ran as (`runAs`): the person a run acted for, or the team account. The list is
`GET /v1/executions`, filtered on the server by the caller's team (the call log keeps the team of every call, task D1).

The stack is `docs/usecases/lib/apps_walk.py`: the test plugins and the fake system; the runs' calls are made as
agents-service makes them, with platform-service's acting-for token when a person started the run.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team's Usage lists its own calls and never another team's, though both teams use the same app | api | 1-2 | 2 |
| S2 | Each call says whom it ran as: Team account, or the person a run acted for | api | 3 | 3 |
| S3 | Usage narrows to one app | api | 4 | 4 |
| S4 | A developer reads the team's Usage through the Python SDK and gets what the API gives | sdk | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs mock-oauth2-server behind the fake's sign-in host |
| People | dev roles: admin Priya Shah and builder James Richardson (team_ops), platform Wanjiru Kamau (team_platform) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns the header-key desk on for team_ops and Wanjiru for team_platform, each with the fake's key; a run in each team reads a record | Both calls 200 |
| 2 | Priya lists `GET /v1/executions`; Wanjiru lists it | Priya sees team_ops's call and not team_platform's; Wanjiru the reverse |
| 3 | Priya turns the person-key desk on for person sign-in; James saves his key; a run James started reads a record; Priya lists Usage | The header-key call's runAs is the team; the person-key call's is James, by his email |
| 4 | Priya lists `GET /v1/executions?moduleId=<the desk's module>` | Only the header-key desk's calls |
| 5 | Through the SDK Priya calls `ops.usage.list()` | The same rows as the API |
| 6 | The console steps (Usage under Apps and on the app page, the As column) | Written by the console builder with tasks U1 and U6 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-616-api.py` | passing on today's routes (D1 and S6 landed) |
| sdk | `tools-service/scripts/test-uc-616-sdk.py` | target: waits on K1 |
| ui | not written | console builder, U1 and U6 |

## Non-vacuous check

Step 2 runs a call in a second team on the same app; a list that is not filtered by team shows it to Priya and fails.
