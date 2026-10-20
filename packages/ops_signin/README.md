# ops_signin

Sign-in protocols with no service rules, used by platform-service. Each returns a `VerifiedIdentity` (subject, email,
name, when the person last entered credentials) or raises `SignInRefused`; which provider a workspace uses, its
secrets, and what happens to the person afterwards are the calling service's.

| Module | What it does |
|---|---|
| `password` | `PasswordHasher`: PBKDF2-SHA256, iterations from the caller's settings, rehash when they rise |
| `oidc` | `OidcClient`: authorization code with PKCE (S256), id_token checked against the issuer's keys |
| `saml` | `SamlServiceProvider`: SP-initiated sign-in, the response checked with `signxml` against the IdP certificate |
| `fake_idp` | A local OIDC and SAML identity provider for tests and the dev stack (`python -m ops_signin.fake_idp --port 8790`) |

```python
oidc = OidcClient(OidcConfig(issuer, client_id, secret), http)
start = await oidc.begin(redirect_uri=callback, login_hint=email)  # keep state, nonce, verifier server-side
who = await oidc.complete(code=code, verifier=start.verifier, nonce=start.nonce, redirect_uri=callback)
```

Docs: [docs/packages/ops_signin/overview.md](../../docs/packages/ops_signin/overview.md).
