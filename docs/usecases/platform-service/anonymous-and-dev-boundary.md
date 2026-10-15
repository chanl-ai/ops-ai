# Anonymous and dev boundary

Status: current. Id: `uc-026`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; or set the OPS_USECASE_* ports and OPS_USECASE_DB |

The script starts platform-service in dev on the run's database: its own migration chain, the dev seed (tenant
`local` (the tenant dev auth and every service seed use), team `team_ops` with Priya Shah admin, James Richardson builder, Maya Okafor approver, all on the demo
password `northfield-demo`), the public app and the internal one. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call every operation in the served `/openapi.json` except health, the key set, sign-in, refresh and the invite routes, with no credentials | 401 on each |
| 2 | Call `/v1/me` with only `X-Dev-User` | 401 |
| 3 | Present a token signed with platform's own key but issued for `tools` | 401, where James's real token is 200 |
| 4 | Present a service token on the public mount | 401 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-026-api.py` | passing |

## Non-vacuous check

`all non-public operations are 401 without credentials`: an added route with no authentication answers 200 and the
check fails, naming the route.
