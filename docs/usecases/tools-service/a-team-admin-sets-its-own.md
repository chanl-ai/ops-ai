# A team admin sets its own app credential and tests it with their account

Status: draft. Id: `uc-615`. Service: `tools-service`. Layers: api, sdk, cli, ui. Card: an earlier change (story group B of
the planning repo `docs/plans/ops-ai/apps.html`).

An app credential is how an app signs in: Ops AI's own app, or the team's own client id and secret. It was set in two
places (the platform's app secret, and a client typed into each connection's settings), and a key could sit either in
Secrets or on the connection. Now a team admin keeps Ops AI's app or sets the team's own once per app under Apps ›
Credentials, checks it with Test with my account, and Secrets holds only values tools reference, never a sign-in.

The stack is `docs/usecases/lib/apps_walk.py`: the test plugins of `services/tools-service/tests/plugin_kinds` and the
fake system of `docs/usecases/lib/fake_multi_auth.py`, whose sign-in server knows the clients `multi-zoom` (set up as
Ops AI's own app for the person desk, its secret sealed by the account admin) and `multi-app` (the team's own).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team admin sees the app on Ops AI's app, sets the team's own client id and secret, and reads it back with no secret | api | 1-2 | 2 |
| S2 | Test with my account signs the admin in through the team's own app and says it works | api | 3 | 3 |
| S3 | A builder may not set an app credential | api | 4 | 4 |
| S4 | A tool's secret is kept in Secrets, and no sign-in shows there | api | 5 | 5 |
| S5 | A developer reads and sets the app credential through the Python SDK | sdk | 6 | 6 |
| S6 | A team admin sets the app credential with `ops apps credential set`, giving the secret on standard input | cli | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA and Docker | `make db-up`; Docker runs mock-oauth2-server behind the fake's sign-in host |
| People | the dev roles of `services/platform-service/seed/dev-roles.json`: admin Priya Shah, builder James Richardson (team_ops) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns the person desk (`test.person`) on for the team account and reads its connection (`GET /v1/connections/{id}`) | Its production environment signs in with Ops AI's app (`platformApp` names the plugin) |
| 2 | She puts the team's own client on the environment (`PUT /v1/connections/{id}/environments/production`, client id `multi-app` and its secret) and reads it again | 200; Ops AI's app no longer used; client id `multi-app`; the secret in no answer |
| 3 | She presses Test with my account: `POST /v1/connections/{id}/test-credential` gives a sign-in address, she allows as harbor.ops, and posts the answer back to the same route | The address names client `multi-app`, not Ops AI's `multi-zoom`; the second call answers `ok` as harbor.ops |
| 4 | James sets the credential | 403 |
| 5 | Priya saves a secret `DESK_WEBHOOK` in Secrets and lists Secrets | The secret listed with no value; nothing named for the app's client or a person's sign-in |
| 6 | Through the SDK, Priya calls `ops.credentials.set(app, client_id=…, client_secret=…)` | The environment holds client `multi-app`, Ops AI's app no longer used; no secret in the answer |
| 7 | Priya runs `ops apps credential set plugin:test.person --client-id multi-app --client-secret -` with the secret on standard input | Exit 0; the environment holds client `multi-app`; the secret in no output |
| 8 | The console steps (Apps › Credentials: App credentials, Test with my account, Secrets) | Written by the console builder with task U4 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-615-api.py` | target: step 3 waits on P1 (test-credential) |
| sdk | `tools-service/scripts/test-uc-615-sdk.py` | target: waits on K1 |
| cli | `tools-service/scripts/test-uc-615-cli.py` | target: waits on L1 |
| ui | not written | console builder, U4 |

## Non-vacuous check

Step 4: the builder's 403 is paired with the admin's 200 in step 2, so a route that lets anyone set the credential
fails the use case. Step 2 also searches every answer for the client secret.
