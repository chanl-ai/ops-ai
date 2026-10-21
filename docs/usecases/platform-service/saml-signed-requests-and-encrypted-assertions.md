# SAML with signed requests and encrypted assertions

Status: current. Id: `uc-215`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev with the dev seed (Sam Adeyemi, Security admin), sign-in URLs, a SAML
service provider key pair made for the run (`OPS_SAML_SP_KEY`, `OPS_SAML_SP_CERTIFICATE`), and the local fake identity
provider with its DNS. The fake is told the service provider's certificate through `PUT /saml/strict/sp`, as a bank's
identity team would import it. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam sets a SAML provider with `signRequests` and `requireEncryption`, its domain verified | 200 |
| 2 | Read `GET /v1/auth/saml/metadata` | 200; the certificate is listed for signing and encryption |
| 3 | The identity provider checks signed requests and encrypts with AES-256-CBC; a new person signs in | The request is accepted; the encrypted assertion signs them in by SAML |
| 4 | The identity provider holds another certificate | It refuses the request (400) |
| 5 | The identity provider wraps the key with `rsa-1_5` | Nobody is signed in |
| 6 | The identity provider sends a plain assertion | Nobody is signed in: encryption is required |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-215-api.py` | passing |

## Non-vacuous check

With the signature check after decryption, the encryption requirement and the key transport check removed, three
tests in `packages/ops_signin/tests/test_saml.py` fail.
