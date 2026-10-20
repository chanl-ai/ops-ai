# An assistant lists and runs a team's read tools over MCP with an API key

Status: passing. Id: `uc-410`. Service: `tools-service`. Layers: api. Card: c-356.

An outside assistant (Claude Code, Cursor) connects to `/mcp/test/{team}` with an API key of that team and uses the
official MCP Python SDK client to list and call the team's tools. Listing shows the team's published read operations
only. A call runs through the same gateway function as `POST /v1/calls`, so the registry, schema, OPA, rate window,
executor and call log all apply. Writes, other teams' tools, other teams' URLs, production and callers without
`tools.run` are refused.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service issuing keys and tokens; tools and agents verifying them | `platform()`, `tools()` and `agents()` with `OPS_AUTH_MODE=platform` |
| The bank stand-in | `core_bank()`; `GET /accounts/{account_id}` and `POST /accounts/{account_id}/holds` behind its API key |
| A team_ops key and a team_fraud key | Priya (team_ops admin) and Wanjiru (admin in every team) create them at `POST /v1/api-keys` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| setup | Priya connects the bank and publishes `uc410_get_account` (read) and `uc410_place_hold` (a write declared to run at once); Nadia approves both reviews | Both published |
| 1 | The team_ops key lists tools at `/mcp/test/team_ops` | The read is listed with its input schema and `readOnlyHint`; the write is not |
| 2 | It calls `uc410_get_account` for `CHQ-2219` | The bank's own account; the call log row says `channel` mcp, the client's name and test |
| 3 | It calls `uc410_place_hold` by name | Refused (`write needs an approval token`) and logged as an mcp call; the account still has no hold |
| 4 | The team_fraud key lists and calls at `/mcp/test/team_fraud`, then tries `/mcp/test/team_ops` | Not listed; the call is 403 `team_forbidden`; the other team's URL is 403 `team_forbidden` |
| 5 | The production URL; no credential; a viewer's token | 403 `production_off`; 401 `unauthorized` with `WWW-Authenticate`; 403 `role_required` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-410-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-410 LAYER=api` (2026-10-19) |

## Non-vacuous check

The write in step 3 is declared to run at once, so only the MCP rule holds it. When `gateway_calls.py` stops making
an MCP write wait, step 3 fails: the write reaches the bank and the log shows an allowed call
(`.codeloop/evidence/356/uc-410-red-without-mcp-write-wait.txt`). `services/tools-service/tests/test_mcp_server.py`
also fails without that rule. It fails as well when the team check is removed from the call path: a Card Services key
then runs Lending Ops' read (`.codeloop/evidence/356/unit-red-without.txt`).
