# A tool presents a client certificate from its connection

Status: passing. Id: `uc-395`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

A client certificate is a section of any connection environment: the certificate and the CA that signed the system's
own certificate are plain settings, the private key a secret part. The egress transport presents it from a pool of
its own, so it never rides on another connection's calls.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A connection that trusts the system's CA but holds no client certificate fails the handshake on our side | api | 1 | 1 |
| S2 | A connection holding the certificate and its key reaches the system, and the key is never shown | api | 2 | 2 |
| S3 | The certificate is presented only on its own connection's calls, and no key reaches the call log | api | 3-4 | 4 |
| S4 | An admin presses Test the team account on the certificate connection's page and it works | ui | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in's certificate-only listener, `mtls.bank.test`, TLS 1.2 | `core_bank()`; its CA and a client certificate it signed are in the JSON line `fake_bank_serve.py` prints (`docs/usecases/lib/bank_certificates.py`) |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A connection trusting the system's CA, with no client certificate | `TLS_FAILED` on our side |
| 2 | A connection with the certificate and its key | The key is set and never shown; the system answers |
| 3 | The first module again | Still fails: the certificate is presented only on its own connection's calls |
| 4 | Read the call log | No private key in it |
| 5 | In the console as an Operations admin, open the certificate connection's page and press Test the team account | Working, 200; the key is not on the page |

The ui harness's bank stand-in does not hand back its certificate-only listener or client certificate; card an earlier change
adds them. Until then the ui layer fails at step 5 before it opens the page.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-395-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-395 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-395-ui.mjs` | failing at step 5 (2026-10-30): the ui harness's bank does not hand back its certificate-only host or client certificate |

## Non-vacuous check

Step 2 fails `TLS_FAILED` with the certificate left out of the TLS context.
