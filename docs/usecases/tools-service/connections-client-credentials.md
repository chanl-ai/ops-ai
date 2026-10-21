# A tool signs in with an OAuth client ID and secret

Status: passing. Id: `uc-393`. Service: `tools-service`. Layers: api. Card: c-330.

The client credentials strategy fetches a token from the connection's token address through the egress client, keeps
it encrypted, and reuses it until a minute before it expires. When the system answers a read with 401, the gateway
gets a new token and sends the read once more; a write answered 401 is not sent again (`AUTH_EXPIRED`). A secret the
system refuses marks the connection as needing attention.

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

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-393-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-393 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 1 fails with the strategy replaced by none, and steps 2
and 3 fail with the 401 retry removed.
