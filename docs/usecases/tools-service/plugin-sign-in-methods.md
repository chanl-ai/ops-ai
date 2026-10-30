# A developer's plugin signs in every way a system asks, and its agents call it

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-588`.
Service: `tools-service` with platform-service. Layers: api, cli, ui. Card: an earlier change. Guide: `docs/guide/plugins.md`.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team turns on a plugin for a system that takes no sign-in, an API key in a header or a query, a username and password, or a fixed token; Test connection passes and a run's call reaches the system signed in where the plugin said | api | 1-6 | 6 |
| S2 | A plugin whose system issues tokens to a client fetches its token, and after it expires the next call gets a new one | api | 7 | 7 |
| S3 | Each person signs in with their own account and acts as themselves, a call with nobody behind it uses no one's account, and a token is renewed with its refresh token | api | 8-9 | 8 |
| S4 | A team gives a client certificate beside the sign-in; Test connection and the call present it | api | 10 | 10 |
| S5 | A wrong key, client secret or missing certificate fails clearly, and no secret appears in any answer, call log or log line, even from a plugin tool that echoes what it sent | api | 11-13 | 13 |
| S6 | A developer validates each plugin, and validate refuses person sign-in on a team-only method and an API key it does not say how to send | cli | 14-15 | 15 |
| S7 | In chat, a person asked to connect their own account signs in from the card and the agent reads as them; each plugin connection's page shows how it signs in and no key | ui | 16-18 | 17 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs mock-oauth2-server for the OAuth methods |
| Plugins on | The api layer starts tools-service with `OPS_PLUGINS=true` and every folder under `services/tools-service/tests/plugin_kinds` in `OPS_PLUGIN_PATHS` |
| The fake system | `docs/usecases/lib/fake_multi_auth.py`: `api.multi.test` with one endpoint per method, `login.multi.test` in front of mock-oauth2-server checking each client's secret, and `mtls.bank.test`, which refuses a handshake without a client certificate its CA signed |
| People | Sam Adeyemi (Security admin, the platform admin of this install), Priya Shah (team_ops admin), James Richardson and Maya Okafor (team_ops), Wanjiru Kamau (team_platform admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | tools-service starts with the eight test plugins; Sam turns them on and lists the system's hosts | All eight load, none failed; 200 |
| 2-6 | For each of none, header key, query key, basic and bearer: Priya turns it on giving its credential, tests the connection, and a run calls its read tool | 200; Test connection ok; the record comes back and the system received the expected credential in the expected place |
| 7 | Priya turns on the client-credentials plugin with the client's id and secret; a run calls it; every token expires; a run calls it again | Test connection ok; both calls answer as the client; at least two client-credentials token requests |
| 8 | Priya turns on the person plugin for person sign-in; James and Maya each sign in with their own account and test the connection; a run with nobody behind it calls the tool | Each test reaches the system as that person; the call answers `CONNECTION_NOT_LINKED` |
| 9 | Every token expires; James tests again | ok, as James, after a refresh-token request |
| 10 | Priya turns on the certificate plugin with a client certificate, its private key and the system's CA | Test connection ok; the call reaches the certificate listener |
| 11 | Wanjiru turns on the header-key plugin with a wrong key, the client plugin with a wrong secret, and the certificate plugin with only the CA | Test connection fails naming the 401 and the call `UPSTREAM_ERROR` 401; the call `AUTH_FAILED` and the connection `needs_reconnect`; Test connection and the call `TLS_FAILED` |
| 12 | A run calls the bearer plugin's Python tool, which returns what the system says it was sent | 200, with no token in it |
| 13 | Every answer read, both teams' plugins, connections and call logs, and the tools-service log are searched for every secret given | None found |
| 14 | `ops plugin validate` on each test plugin | Each OK |
| 15 | `ops plugin validate` on copies offering person sign-in with only an API key, and listing `api_key` without saying how it is sent | Each refused, naming `connection.sign_in` or `connection.api_key` |
| 16 | James asks the agent holding the person plugin's read tool for record rec-1042 in chat | A Connect card; the system received no read |
| 17 | He connects through the pop-up as james.person | The chat goes on and answers with the record, read as james.person |
| 18 | Priya opens the header-key and person plugins' connection pages | Each opens with its name and sign-in method, the header-key one tested and working; neither key nor client secret is on either page |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-588-api.py` | draft |
| cli | `tools-service/scripts/test-uc-588-cli.py` | draft |
| ui | `tools-service/scripts/test-uc-588-ui.mjs` | draft |

Evidence only, not in the nightly run: `tools-service/scripts/evidence-uc-588-stripe.py` runs the bearer plugin against
Stripe's API in test mode with a test key read from the secrets store.

## Non-vacuous check

The unit tests behind this use case (`services/tools-service/tests/test_plugin_sign_in.py`) were each seen failing
before their fix: every non-OAuth turn-on answered 400, the client-credentials turn-on failed without the token
address, Test connection answered `UNREACHABLE` for a refused certificate, and the echo tool returned the token.
