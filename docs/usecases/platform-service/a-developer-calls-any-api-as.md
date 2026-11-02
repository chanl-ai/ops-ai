# A developer calls any API as a standard dev user

Status: passing. Id: `uc-614`. Service: `platform-service`. Layers: api. Card: an earlier change.

A developer runs `make api <METHOD> <PATH> AS=<role>` or `make sdk-call CALL='…' AS=<role>` as one of the standard
dev users in `services/platform-service/seed/dev-roles.json` (admin, builder, approver, viewer, security, platform).
The command signs the role's seeded person in through `POST /v1/auth/sign-in`, keeps the token until it expires, finds
the service from the path and prints the answer. Developer guide: `docs/guide/skills/ops-run.md`, "Call an API as a dev
user". The script runs the make commands themselves against its own platform-service and tools-service, whose seed
gives each person only their own role.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A developer calls a route as each standard role and sees the answer as that person, in that person's team | api | 1 | 1 |
| S2 | A developer calling as the viewer is refused what a viewer may not do, and the admin is allowed it | api | 2 | 2 |
| S3 | A developer names only the path and the command finds the service, or asks which one when two hold it | api | 3, 5 | 3 |
| S4 | A developer's cached token that stopped working, or a broken cache file, is replaced by a fresh sign-in | api | 4 | 4 |
| S5 | A developer makes one Python SDK call as a role, and the password is never printed or kept | api | 6, 7 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service and tools-service on the use-case database, platform sign-in | the harness's `platform()` and `tools()`; the make commands reach them through `OPS_PLATFORM_PORT` and `OPS_TOOLS_PORT`, with tokens in a folder of the run's (`OPS_API_TOKENS`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `make api GET /v1/me AS=<role>` for each of the six roles | Exit 0; the line names the role's person and team (team_ops, or team_security for security, team_platform for platform) and the answer is that person |
| 2 | `make api POST /v1/settings/members/invite AS=viewer BODY=…`, then the same as admin | The viewer gets 403 and exit 1; the admin's invite is accepted |
| 3 | `make api GET /v1/tool-modules Q=pageSize=1 AS=builder` | Sent to tools-service, `GET tools/v1/tool-modules?pageSize=1 as builder …` |
| 4 | The builder's cached token is replaced with a bad one, then the file with text that is not JSON; `make api GET /v1/me AS=builder` each time | 200 both times; the bad token is replaced |
| 5 | `make api GET /v1/templates AS=builder`, then with `SVC=agents` | Refused naming agents and documents; with `SVC=agents` sent to agents-service |
| 6 | `make sdk-call CALL='ops.raw.platform.me_me()["user"]["email"]' AS=approver` | Prints Maya Okafor's email |
| 7 | Every output and cached token file | None holds the demo password |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-614-api.py` | passing, `make usecase-test UC=uc-614 LAYER=api` (2026-11-01) |

## Non-vacuous check

With the 401 retry removed from `scripts/api_as.py` (`for attempt in (0,)`), step 4 failed:
`GET platform/v1/me as builder (j.richardson@harborpine.example, team_ops): 401`, 11 passed and 1 failed.
