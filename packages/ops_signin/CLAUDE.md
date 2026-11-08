# ops_signin: working rules

Status: current.

Sign-in protocols with no service rules: password hashing, OIDC authorization code with PKCE, SAML SP-initiated
sign-in (plain or encrypted assertions), domain proof by DNS TXT record, and a local fake identity provider. Each
protocol returns a `VerifiedIdentity` or raises `SignInRefused`; which provider a workspace uses, its secrets and what
happens to the person afterwards belong to platform-service, the only consumer. Package rules and test commands:
[../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides). Module table and a
usage example: [README.md](README.md).

## Contract with callers

- Nothing here stores state between the two halves of a flow: the caller keeps `state`, `nonce` and the PKCE
  `verifier` from `begin` server-side and passes them to `complete`.
- `SamlServiceProvider.complete` reads only the signed element, refuses a response with more than one assertion, and
  trusts a decrypted assertion only when a signature checked before decryption covers it (`src/ops_signin/saml.py:12`).
  `xmlenc` refuses any algorithm it does not name, `rsa-1_5` included, and raises one `DecryptionRefused` for every
  later failure so the error says nothing about the plaintext.
- A forced sign-in (step-up) sends the force flag and checks the login time against the flow, since an identity
  provider's own session cookie would otherwise pass it.
- `TxtResolver` asks only the DNS servers it is given; the caller names them from its settings.

Depends on nothing in the workspace. The `fake` extra (`pyproject.toml:11`) adds FastAPI and uvicorn for the fake
identity provider: `uv run python -m ops_signin.fake_idp --port 8790 [--dns-port 8791]`.

## Run and test

| Task | Command |
|---|---|
| The suite (no database, no network) | `make test PKG=packages/ops_signin` |
| Some files | `make test PKG=packages/ops_signin T="tests/test_password.py tests/test_oidc.py"` |
| Lint, format, types | `uv run ruff check packages/ops_signin`, `uv run ruff format --check packages/ops_signin`, `uv run pyright packages/ops_signin` |
| Sign-in end to end | platform-service's use cases, for example `make usecase-test UC=uc-021` |

Every protocol is tested against the fake identity provider only; no real identity provider has been tried
(**unverified**).

## Reference docs

- [docs/packages/ops_signin/overview.md](../../docs/packages/ops_signin/overview.md): each check and its gotchas.
  Its SAML row says an encrypted assertion is refused; the code decrypts one (`src/ops_signin/xmlenc.py`), so that row
  is out of date
- [docs/architecture/decisions/auth-provider-seam.md](../../docs/architecture/decisions/auth-provider-seam.md)
