# A tool signs in with an OAuth client ID and secret

Status: passing. Id: `uc-393`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

The client credentials strategy fetches a token from the connection's token address through the egress client, keeps
it encrypted, and reuses it until a minute before it expires. When the system answers a read with 401, the gateway
gets a new token and sends the read once more; a write answered 401 is not sent again (`AUTH_EXPIRED`). A secret the
system refuses marks the connection as needing attention.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Reads share one client-credentials token, and after the system revokes it one more is fetched | api | 1-2 | 2 |
| S2 | A write refused for an expired token is not sent again | api | 3 | 3 |
| S3 | A secret the system refuses fails the call and marks the connection as needing attention | api | 4 | 4 |
| S4 | A token address off the allow-list is refused, and no secret reaches the call log | api | 5-6 | 6 |
| S5 | An admin presses Test the team account and it works; a refused secret says Failed and invalid_client | ui | 7-8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in, also the OAuth server | `core_bank()`; `POST /oauth2/token`, `GET /auth/oauth`, `POST /auth/oauth/holds`, and the test controls `/oauth2/stats` and `/oauth2/revoke-access` |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Two reads | Both carry a client-credentials token; the bank issued one; the connection shows its permissions, never the token |
| 2 | The bank revokes its tokens; read again | The read succeeds; exactly one more token was fetched |
| 3 | A write runs; the bank revokes; the write again | `AUTH_EXPIRED` on our side; the bank received that write once |
| 4 | A connection with a secret the bank refuses | The call fails `AUTH_FAILED` on the system's side; the connection needs attention, says `invalid_client`, and its activity records it |
| 5 | A token address off the allow-list | `EGRESS_DENIED`; nothing is sent |
| 6 | Read the call log | No client secret in it |
| 7 | In the console as an Operations admin, open the connection's page and press Test the team account | Working, 200, production; the secret is not on the page |
| 8 | The same on a connection whose secret the bank refuses | Failed, naming `invalid_client` |

The console's connect dialog runs on the mock only, so the ui layer sets its connections up through the API and
tests them on the connection page (shown with the `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` switch on).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-393-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-393 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-393-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails with the strategy replaced by none, and steps 2
and 3 fail with the 401 retry removed.
