# A builder adds an MCP server behind OAuth and its tools run through the same executor

Status: passing. Id: `uc-396`. Service: `tools-service`. Layers: api, ui.

An MCP server that needs sign-in answers 401 and names its protected resource metadata. `POST /v1/connections/mcp`
follows it to the authorization server, checks the issuer, registers a public client when the server offers
registration and no registered client is given, and makes an `oauth2_auth_code` connection with the server as its
`resource`. After one sign-in, the server's tools are listed with their inputs, and calls go through the one executor
with the connection's token, refreshed for the same resource after a 401.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder adds an MCP server by its address and its sign-in is found from the server, with a client registered once | api | 1-2 | 2 |
| S2 | After one sign-in the server's tools are listed with their inputs and a module keeps them | api | 3-4 | 4 |
| S3 | A tool call runs with the connection's token, and after the server refuses it one refresh lets the call succeed | api | 5 | 5 |
| S4 | A registered client the bank gave is used as given, with no second registration | api | 6 | 6 |
| S5 | An admin sets the server's app to each person's own account, signs in once through the pop-up from her row, and Test works with her account | ui | 7-8 | 8 |

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
| 7 | In the console as an Operations admin, open the app's page, turn on Settings › Everyone signs in with their own account, and press Connect my account on her row | The pop-up signs in and closes; her row says Connected as her |
| 8 | Press Test on Settings › Keys | Working, 200, with her own account |

The ui layer adds the server through the API, as the api layer does, and signs in with the person's own account.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-396-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-396 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-396-ui.mjs` | failing at step 8 (2026-11-03): an MCP app's base address is the server's own, path included (`connections/service.py:619`), so the test path `/auth/oauth` is read at `/mcp/screening/auth/oauth` and the stand-in answers 404; steps 7 pass |

## Non-vacuous check

Step 5 fails with the server's 401 when the MCP path does not sign in through the connection. The issuer check is `tests/test_mcp_signin.py`.
