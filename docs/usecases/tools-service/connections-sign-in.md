# A person signs a connection in once with the team's account

Status: passing. Id: `uc-394`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

A connection that signs in with an account uses the OAuth authorization code flow with PKCE (S256). Someone who
manages connections starts the sign-in; the browser goes to the system and comes back to the console's return page,
which hands the code and state to tools-service under the same person's token. The state is used once, within ten
minutes, by that person. Tools then use the account's token; every refresh stores the rotated refresh token in the
same transaction that spent the old one.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A call before anyone signs in is refused, and the connection names the address to register | api | 1 | 1 |
| S2 | The person who started the sign-in finishes it once; anyone else, or a second time, is refused | api | 2-3 | 3 |
| S3 | Calls run on the account's token and each refresh is stored with the rotated refresh token | api | 4 | 4 |
| S4 | After sign-out calls are refused again, and the activity records both | api | 5 | 5 |
| S5 | An admin signs the team account in once from the connection page, and Test the team account works | ui | 6-7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in, also the OAuth server | `core_bank()` with `FAKE_BANK_TOKEN_TTL=30`, so every call refreshes |
| tools-service knows the console's address | `OPS_CONSOLE_URL=https://console.bank.test` |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call before anyone signs in | Refused `NOT_SIGNED_IN`; the connection names the redirect address to register |
| 2 | Start sign-in; follow the address as a browser | S256 challenge, state and the console's return address; the system sends back a code |
| 3 | Another person hands the code back; then the person who started; then again | `sign_in_expired`; 200 with "signed in as svc-lending@bank.test" and no token shown; `sign_in_expired` |
| 4 | Two calls | Both run on the account's token; each refreshed it and both refreshes were accepted |
| 5 | Sign out, call | `NOT_SIGNED_IN`; the activity records the sign-in and the sign-out |
| 6 | In the console as an Operations admin, open the connection's page and sign the team account in through the pop-up | The pop-up signs in and closes |
| 7 | Press Test the team account | Working, 200 |

Step 6 uses the page's Connect the team account button, shown on a kind that signs in when the team's account is
used (`apps/console/src/app/tools/connections/[id]/page.tsx`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-394-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-394 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-394-ui.mjs` | passing (2026-10-30) |

## Non-vacuous check

Steps 1, 4 and 5 fail with the strategy replaced by none;
step 4 would fail with `invalid_grant` on the second refresh if the rotated refresh token were not stored.
