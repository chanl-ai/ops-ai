# A builder imports tools from OpenAPI and MCP and calls them on allowed hosts only

Status: current. Id: `uc-012`. Service: `tools-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| A private network address on this machine | The script serves a fake bank on it (`docs/usecases/lib/fake_bank_https.py`): https with a certificate for `api.bank.test`, an OpenAPI document and an MCP server. tools-service trusts that certificate and maps the name to the fake (dev-only settings), so the URL is an ordinary `https://api.bank.test` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Discover the document before its host is on the egress allow-list | 400 |
| 2 | List the host, discover again (it resolves to an unlisted private address) | 400, and the bank received nothing |
| 3 | List the bank's range, discover again | the document is read; every operation is a write |
| 4 | Create a module from the document, sending a forged `DELETE /admin` for `get_account` | the module holds `GET /accounts/{accountId}` |
| 5 | Request a security review; someone else approves it | the module is published |
| 6 | Call `get_account` through `/v1/calls` | the bank's answer |
| 7 | Discover the MCP server, create and publish a module from it, call `lookup_case` | discovered as a write; the call runs through `tools/call` |
| 8 | The server renames the tool; import the new one | the module is drifted, and a call to it is refused (403) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-012-api.py` | passing |

## Non-vacuous check

`a listed host resolving to an unlisted private address is refused (400)` paired with step 3's success: with the
private-range check removed, discovery succeeds and the bank receives the request, so both step 2 checks fail.
