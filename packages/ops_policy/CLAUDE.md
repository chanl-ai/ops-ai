# ops_policy: working rules

Status: current.

Trust primitives with no rules in them: canonical JSON and input hashes, signed tokens with expiry and audience,
approval tokens bound to one tool call's input, step-up tokens, the secrets-at-rest cipher and the credential store
port. Which calls need an approval, a step-up or two approvers is decided by the caller. Package rules and test
commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `jcs` | `canonicalize` (RFC 8785 plus NFC on strings), `input_hash`, `CanonicalJsonError` |
| `tokens` | `mint`, `verify`, `claims_of`, `header_of`, `Signer`, `HmacSigner`, `Ed25519Signer`, `Ed25519Verifier`, `TokenError`: compact JWTs behind a `Signer` a KMS adapter can replace |
| `approval` | Approval tokens: HS256 JWTs the review service signs, bound to one tool call's exact input |
| `step_up` | `mint_step_up`, `verify_step_up`, `StepUp`, `STEP_UP_TTL_S`: proof a named person re-authenticated recently |
| `cipher` | `Cipher` port and `AesGcmCipher`: AES-256-GCM, tenant and secret name as associated data |
| `credentials` | `CredentialStore` port, `InMemoryVault`, `RowSealed`, `CredentialUnreadable`: every secret value is put and read through it, and the row that uses it keeps only a reference |

## Contract with callers

- An approval token's binding names the thread, the step's idempotency key, the tool and `inputHash`, the hash of
  the call's canonical input (`src/ops_policy/approval.py:18`). The review side mints it; tools-service's OPA policy
  verifies it with the same key and refuses it for any other input. Signing is HMAC today, behind a `Signer` an
  asymmetric KMS signer would replace so only the review side can mint.
- Change `jcs` only with every caller's tests: a different byte form changes every input hash, so every token
  already issued stops matching.
- Secrets never sit in a service's own rows: they go through `CredentialStore`, and `ops_service_kit.credentials`
  picks the store from settings. The in-memory store is refused outside dev and test.
- No module here reads settings or the environment; keys and lifetimes are arguments.

Depends on nothing in the workspace. Depended on by `ops_identity`, `ops_service_kit`, agents-service,
models-service, platform-service and tools-service.

## Run and test

| Task | Command |
|---|---|
| The suite (60 tests, under 10 s; no database) | `make test PKG=packages/ops_policy` |
| One file | `make test PKG=packages/ops_policy T=tests/test_jcs.py` |
| Lint, format, types | `uv run ruff check packages/ops_policy`, `uv run ruff format --check packages/ops_policy`, `uv run pyright packages/ops_policy` |

## Reference docs

- [docs/architecture/human-in-the-loop.md](../../docs/architecture/human-in-the-loop.md): reviews, step-up and two-person decisions
- [docs/architecture/decisions/identity-and-entitlement.md](../../docs/architecture/decisions/identity-and-entitlement.md) (ADR-0005)
