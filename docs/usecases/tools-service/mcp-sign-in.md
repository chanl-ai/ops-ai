# A builder adds an MCP server behind OAuth and its tools run through the same executor

Status: passing. Id: `uc-396`. Service: `tools-service`. Layers: api. Card: c-331.

An MCP server that needs sign-in answers 401 and names its protected resource metadata. `POST /v1/connections/mcp`
follows it to the authorization server, checks the issuer, registers a public client when the server offers
registration and no registered client is given, and makes an `oauth2_auth_code` connection with the server as its
`resource`. After one sign-in, the server's tools are listed with their inputs, and calls go through the one executor
with the connection's token, refreshed for the same resource after a 401.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in's MCP server at `https://api.bank.test/mcp/screening`, its metadata and registration | `core_bank()` (`services/tools-service/scripts/fake_bank/bank_auth.py`) |
| tools-service knows the console's address | `OPS_CONSOLE_URL=https://console.bank.test` |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | List the server's tools with no connection | 400 `sign_in_required` |
| 2 | Add the server by its address | An `oauth2_auth_code` connection at the server's authorization server, `resource` the server, a client registered once |
| 3 | Sign in once as the browser | The sign-in names the server as its resource; it finishes |
| 4 | List the tools with the connection; create a module | Both tools with the inputs the server declares; the operation keeps them |
| 5 | Call a tool; the server stops honouring the token; call again | Runs with the registered client's token; one refresh, and the call succeeds |
| 6 | Add the server with the bank's registered client | Used as given, its secret a secret part, no second registration |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-396-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-396 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 5 fails with the server's 401 when the MCP path does not sign in through the connection. The issuer check is `tests/test_mcp_signin.py`.
