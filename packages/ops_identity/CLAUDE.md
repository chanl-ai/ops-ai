# ops_identity: working rules

Status: current.

Who is calling a service. It turns a request's platform token, API key or service token into a `Principal`, enters the
request's tenant and team isolation context from it, and is the one way a service calls another service's API.
platform-service issues the tokens; every other service verifies them locally through this package. Package rules and
test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `principal` | `Principal`: kind (`person`, `api_key`, `service`), tenant, the one acting team, roles, access grids, scopes, policies, security team |
| `resolve` | `Identity` (resolution order: platform token, API key, service token, dev caller), `ServiceAuth`, `mint_service_token` |
| `fastapi` | `Auth`, `install_auth`, and the route dependencies `CurrentPrincipal`, `CurrentService`, `CurrentCaller`, `CurrentTenantCaller`, `ActingPerson` |
| `client` | `ServiceClient` (`get`, `post`, `delete`, `pages`), `ServiceCallError`, `ServiceUnreachable`: service-to-service calls with token minting, envelope reading and retry |
| `acting_for` | `ActingForTokens`, `ActingForPerson`, header `X-Acting-For`: whom a service's call acts for, proven by a token platform-service signs |
| `jwks` | `JwksCache`: platform-service's public keys by `kid`, refetched once on an unknown `kid`, rate-limited |
| `service_keys` | `service_signer`, `service_verifiers`, `dev_service_signer`: the Ed25519 keys services sign each other's tokens with |
| `http` | `http_jwks`, `http_introspect`, `http_current_version`: the calls `Identity` makes to platform-service |
| `testing` | Long-lived person and service tokens for tests that mint their own |

## Contract with callers

- A service builds `Auth.from_settings(settings, audience="<service>")`, installs it with `install_auth(app, ...)`, and
  each route depends on `CurrentPrincipal` (people and API keys) or `CurrentService` (internal routes). No service
  resolves tokens, keys or dev headers itself (`src/ops_identity/fastapi.py:1`).
- The tenant comes from the verified credential and the team from `X-Team-Id` checked against it, never from a body,
  query or path. After resolution `ops_store.isolation.enter_caller` runs (`src/ops_identity/fastapi.py:161`), so
  every store call in the request is isolated.
- `OPS_AUTH_MODE=dev` makes every request the fixed dev user in tenant `local`, with `X-Dev-User` naming another seeded
  person and `X-Team-Id` the team; `Settings` refuses dev mode outside `environment=dev`.
- A person's token older than the tenant's permission version is refused, so a role change applies on the next
  request after the client refreshes.
- Calls to another service go through `ServiceClient`; a new client never mints its own token or reads the envelope by
  hand. `ops_files_client` and `ops_documents_client` are built on it.

Depends on `ops_policy`, `ops_service_kit` and `ops_store`. Depended on by `ops_access`, `ops_documents_client`,
`ops_extract`, `ops_files_client` and every Python service. platform-service, the issuer, resolves its own sessions
without this module.

## Run and test

| Task | Command |
|---|---|
| The suite (46 tests, under 10 s) | `make test PKG=packages/ops_identity` |
| One file | `make test PKG=packages/ops_identity T=tests/test_service_scopes.py` |
| Lint, format, types | `uv run ruff check packages/ops_identity`, `uv run ruff format --check packages/ops_identity`, `uv run pyright packages/ops_identity` |
| Sign in for real and call a route the console calls | `make api GET /v1/me AS=viewer` ([calling the API as a person](../../CLAUDE.md#calling-the-api-as-a-person)) |

## Gotchas

| Gotcha | Rule |
|---|---|
| The introspection token names the service by its audience, so in production each service's key must be bound to that name in platform-service's `OPS_SERVICE_PUBLIC_KEYS` | A key shared between services is refused for every name but its own; the dev key `svc-dev` works for any name, in dev only |
| A test that mints tokens at import outlives a short token lifetime and turns into 401s | Use `ops_identity.testing`; a test about expiry passes its own `ttl_s` and `now` |

## Reference docs

- [docs/architecture/identity-and-tenancy.md](../../docs/architecture/identity-and-tenancy.md)
- [docs/architecture/decisions/identity-and-entitlement.md](../../docs/architecture/decisions/identity-and-entitlement.md)
- [docs/architecture/decisions/auth-provider-seam.md](../../docs/architecture/decisions/auth-provider-seam.md)
