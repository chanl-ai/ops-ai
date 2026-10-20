# Sign-in library

Status: current. The protocols behind password, OIDC and SAML sign-in (c-188); platform-service is the one consumer.
Tested against the local fake identity provider only; no real identity provider has been tried (**unverified**).

| Part | Where | What it checks |
|---|---|---|
| `PasswordHasher` | `packages/ops_signin/src/ops_signin/password.py` | PBKDF2-HMAC-SHA256 with a 16-byte salt; the iteration count is stored in the hash, so a raised count still verifies old hashes and `needs_rehash` names them |
| `OidcClient.begin` | `oidc.py` | Builds the authorization URL with state, nonce and an S256 code challenge; `force` adds `prompt=login` and `max_age=0` |
| `OidcClient.complete` | `oidc.py` | Exchanges the code with the verifier; the id_token must be signed by a key from the issuer's key set with an asymmetric algorithm, name the configured issuer and client, carry the flow's nonce, be unexpired, carry an email not marked unverified, and for a forced sign-in an `auth_time` no older than the flow |
| `SamlServiceProvider.begin` | `saml.py` | An AuthnRequest on the redirect binding naming the consumer URL; `force` sets `ForceAuthn` |
| `SamlServiceProvider.complete` | `saml.py` | One assertion, none encrypted, status success; the signature verified against the configured certificate; issuer, audience, bearer confirmation (recipient, request id, expiry) and the time window read from the signed element only |
| Fake identity provider | `fake_idp/app.py` | Named providers at `/oidc/<name>` and `/saml/<name>`, each with its own key; the person is named by `user=` on the authorize or SSO URL |

## Gotchas

- A SAML check that reads the posted document instead of the signed element accepts an unsigned assertion placed
  beside a signed one. `complete` refuses a response with more than one assertion and reads only `signed_xml`.
- A SAML text read with `.text` stops at a comment inside the NameID; `complete` joins every text node.
- An IdP keeps its own session, so a step-up that does not force a new login passes on that cookie. Both protocols
  send the force flag and check the time of the login against the flow.

## Tests

`packages/ops_signin/tests/` (`make verify`). Each refusal row was seen failing with its check removed:
`.codeloop/evidence/188/t001-red-checks-removed.txt`.
