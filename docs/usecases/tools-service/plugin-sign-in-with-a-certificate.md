# A team connects a system that allows only certificate sign-in, and its agents call it

Status: current on main behind the `OPS_PLUGINS` switch, which the layer turns on for its own services. Id: `uc-583`.
Service: `tools-service` with platform-service. Layers: api. Card: an earlier change. Guide: `docs/guide/plugins.md`.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team turns on a Microsoft Entra style app with its certificate and private key; Test connection passes, a run's call reads the system, and no token request carries a client secret | api | 1-2 | 2 |
| S2 | A Google service account and a DocuSign integration sign in with the signed JWT as their grant, and their calls act as the account and as the DocuSign user | api | 3 | 3 |
| S3 | An assertion the sign-in refuses (unsigned, too long-lived, replayed, or signed by a key the app was not registered with) fails the call AUTH_FAILED naming the host and reason, with no retry by secret, and the connection needs reconnecting | api | 4-5 | 5 |
| S4 | A key saved with another certificate is refused naming both; reads show the certificate's thumbprint and expiry, never the key; an expired certificate fails before any request and the connection says so; no answer or log carries a key or an assertion | api | 6-7 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | The layer starts tools-service with `OPS_PLUGINS=true` and `OPS_PLUGIN_PATHS` naming `services/tools-service/tests/plugin_signed`'s three plugins |
| A fake sign-in | `docs/usecases/lib/fake_token_endpoint.py`: Entra, Google and DocuSign style token endpoints that check each assertion as Entra does, an API that answers their tokens, the key pair each app is registered with and one no app is |
| People | Sam Adeyemi (Security admin), Priya Shah (team_ops admin), Wanjiru Kamau (team_platform admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The platform admin turns the three plugins on for the install; Security lists `login.certs.test`, `api.certs.test` and the fake's address | All three load and read as on |
| 2 | Priya turns on Entra records with the app's client id, `clientAuth` private_key_jwt, its certificate and key; tests it; a run calls `entra_get_record` | Test connection ok; the agreement comes back; every token request the fake saw carried `client_assertion` and no `client_secret` |
| 3 | Priya turns on Google records (scopes as a claim) and DocuSign agreements (acting as user-5c0e2a, audience `account-d.docusign.com`) with their keys; a run calls each | Each token request holds only `grant_type` and `assertion` (DocuSign also `scope`); the calls answer as the service account and as the DocuSign user |
| 4 | The use case sends the fake an unsigned assertion, one that lives an hour, and the same accepted assertion twice | Each refused with its reason: algorithm, ten minutes, replay |
| 5 | Wanjiru turns on Entra records with a pair the app was never registered with; a run calls it | AUTH_FAILED naming `login.certs.test` and `invalid_client`; one token request, no client secret; the connection needs reconnecting |
| 6 | Wanjiru turns on Google records with a key and another app's certificate; Priya reads her Entra connection; Wanjiru turns on DocuSign with an expired pair and a run calls it | The first is refused naming the Signing key and Signing certificate; the read shows the SHA-256 thumbprint and expiry, not the key; the expired call fails AUTH_FAILED "expired on" with no token request, and the connection needs reconnecting with that reason |
| 7 | Every answer read and the tools-service log are searched | No signing key and no assertion |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | The fake refuses any request with a client secret or without a valid assertion, so a fallback to the secret fails the call |
| 4 | Proves the fake's own checks refuse, so step 5's refusal is the fake's thumbprint check and not a missing endpoint |
| 5 | Counts the token requests made by this call: a retry with a secret would be a second one |
| 6 | Counts every token request before and after the expired call: one sent anyway fails the step |

## Results

| Layer | Script | Result |
|---|---|---|
| api | `tools-service/scripts/test-uc-583-api.py` | passing (2026-10-30), 10 checks; seen red with the assertion branch and the fake's replay check removed |
