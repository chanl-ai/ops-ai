# A tool presents a client certificate from its connection

Status: passing. Id: `uc-395`. Service: `tools-service`. Layers: api. Card: c-330.

A client certificate is a section of any connection environment: the certificate and the CA that signed the system's
own certificate are plain settings, the private key a secret part. The egress transport presents it from a pool of
its own, so it never rides on another connection's calls.

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

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-395-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-395 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 2 fails `TLS_FAILED` with the certificate left out of the TLS context.
