# An assistant lists and runs a team's read tools over MCP with an API key

Status: blocked by a product bug (steps 2 to 4 fail: the call has no tenant); steps 1 and 5 pass. Id: `uc-410`. Service: `tools-service`. Layers: api.

An outside assistant (Claude Code, Cursor) connects to `/mcp/{team}` with an API key of that team and uses the
official MCP Python SDK client to list and call the team's tools. Listing shows the team's published read operations
only. A call runs through the same gateway function as `POST /v1/calls`, so the registry, schema, OPA, rate window,
executor and call log all apply. Writes, other teams' tools, other teams' URLs, callers without
`tools.run` are refused.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| platform-service issuing keys and tokens; tools and agents verifying them | `platform()`, `tools()` and `agents()` with `OPS_AUTH_MODE=platform` |
| The bank stand-in | `core_bank()`; `GET /accounts/{account_id}` and `POST /accounts/{account_id}/holds` behind its API key |
| A team_ops key and a team_platform key | Priya (team_ops admin) and Wanjiru (admin in every team) create them at `POST /v1/api-keys` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| setup | Priya connects the bank and publishes `uc410_get_account` (read) and `uc410_place_hold` (a write declared to run at once); Nadia approves both reviews | Both published |
| 1 | The team_ops key lists tools at `/mcp/team_ops` | The read is listed with its input schema and `readOnlyHint`; the write is not |
| 2 | It calls `uc410_get_account` for `CHQ-2219` | The bank's own account; the call log row says `channel` mcp, the client's name and test |
| 3 | It calls `uc410_place_hold` by name | Refused (`write needs an approval token`) and logged as an mcp call; the account still has no hold |
| 4 | The team_platform key lists and calls at `/mcp/team_platform`, then tries `/mcp/team_ops` | Not listed; the call is 403 `team_forbidden`; the other team's URL is 403 `team_forbidden` |
| 5 | `/mcp/production/team_ops` (there is no environment segment); no credential; a person's console token | 404 `not_found`; 401 `unauthorized` with `WWW-Authenticate`; 401 `unauthorized`, since the address takes only a token issued for it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-410-api.py` | passing, `make usecase-test UC=uc-410 LAYER=api` (2026-10-19) |

In the console: none; an assistant reaches these tools over MCP with an API key, so the use case stays at the api layer.

## Non-vacuous check

The write in step 3 is declared to run at once, so only the MCP rule holds it. When `gateway_calls.py` stops making
an MCP write wait, step 3 fails: the write reaches the bank and the log shows an allowed call. `services/tools-service/tests/test_mcp_server.py`
also fails without that rule. It fails as well when the team check is removed from the call path: a Card Services key
then runs Lending Ops' read.
