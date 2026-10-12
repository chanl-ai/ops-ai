# A tool's credential is a secret that never comes back

Status: current. Id: `uc-013`. Service: `tools-service`. Layers: api.

## Preconditions

As uc-012: PostgreSQL :5477 and a private network address for the fake bank. The fake's `latest_statement`
answers 401 without an `X-Api-Key`, returns a fingerprint of the key it received, and repeats the request's headers
in its answer, as a careless API might.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a module with `latest_statement`, whose header is `{{STATEMENTS_KEY}}`; call it | refused with `SECRET_MISSING`; nothing is sent |
| 2 | Create the secret; list secrets | 201; the value is in neither answer |
| 3 | Call again | the bank received the key; its echo of the header comes back as `[secret]` |
| 4 | Rotate the secret; call again | the bank received the new key |
| 5 | Read `/v1/executions` for the tool | neither value appears |
| 6 | Delete the secret | 204 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-013-api.py` | passing |

## Non-vacuous check

`the bank echoing the header back does not return the value`: with scrubbing removed, the echoed header carries
the key and the check fails.
