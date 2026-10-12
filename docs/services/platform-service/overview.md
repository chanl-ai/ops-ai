# platform-service

Status: first slice built. `services/platform-service` (`ops_platform`), public app on :8710 and internal app on
:8711 (localhost only), with its own migration chain (`alembic_version_platform`). `make up` starts it and lists it in
`make health`. Tests: `services/platform-service/tests`; use cases uc-021, uc-023, uc-025, uc-026. Design:
`docs/specs/platform-service.md`, service map row `platform-service`.

## What it does

It is the identity issuer and nothing else: it owns tenants, teams, users, members, sessions, invites, API keys and
the audit log, and it is the only service that mints identity tokens. It routes no other service's traffic. Every
other service verifies callers locally with `packages/ops_identity`: platform tokens against the published key set,
API keys through introspection on the internal app, service tokens on internal routes only.

| Credential | Shape | Verified by |
|---|---|---|
| Platform token | EdDSA JWT, 15 minutes, `aud` listing every user-facing service, claims per spec section 4 | Each service, against `GET /.well-known/jwks.json` |
| Refresh token | `<session id>.<secret>`, rotated on every refresh; a reused one ends the session | platform-service |
| API key | `ok_<id>.<secret>`, secret shown once, SHA-256 at rest, optional expiry | platform-service, via `POST /v1/auth/introspect` |
| Service token | EdDSA JWT, 60 seconds, signed with the calling service's own key, `sub` bound to that key | The callee's `ServiceAuth` |

## Routes

| Mount | Operations |
|---|---|
| Public :8710 | `GET /v1/health`, `GET /.well-known/jwks.json`, `POST /v1/auth/sign-in`, `GET /v1/auth/session`, `POST /v1/auth/refresh`, `POST /v1/auth/sign-out`, `GET /v1/me`, `GET /v1/teams`, `GET /v1/settings/members`, `POST /v1/settings/members/invite`, `.../role`, `.../delete`, `GET /v1/api-keys`, `POST /v1/api-keys`, `POST /v1/api-keys/{id}/revoke`, `GET /v1/audit`, `GET /v1/invites/{token}`, `POST /v1/invites/{token}/accept` |
| Internal :8711 | `POST /v1/auth/introspect` (service token, no tenant claim) |

Every operation is typed in `services/platform-service/openapi.json`; `make -C services/platform-service
openapi-check` fails on drift.

## Settings

| Setting | Default | Notes |
|---|---|---|
| `OPS_PLATFORM_PORT`, `OPS_PLATFORM_INTERNAL_PORT` | 8710, 8711 | `make/env.mk`; ISOLATED=1 adds 1000 |
| `OPS_PLATFORM_URL` | `http://127.0.0.1:$(OPS_PLATFORM_PORT)` | Where other services fetch the key set |
| `OPS_PLATFORM_SIGNING_KEY`, `OPS_PLATFORM_SIGNING_KID` | unset, `platform-1` | Required outside dev; dev derives a key from a public seed under kid `platform-dev` |
| `OPS_PLATFORM_AUDIENCES` | every user-facing service | The `aud` of a person's token |
| `OPS_PLATFORM_TOKEN_TTL_SECONDS` | 900 | Use cases shorten it to watch a token expire |
| `OPS_PLATFORM_DEMO_PASSWORD` | `northfield-demo` | Dev only; password sign-in is closed outside dev |
| `OPS_PLATFORM_SEED_FILE` | `services/platform-service/tests/fixtures/people.json` | Dev seed: `team_ops` with an admin, a builder and an approver |
| `OPS_SERVICE_SIGNING_KEY`, `OPS_SERVICE_SIGNING_KID` | unset, `svc-dev` | A calling service's own key; required outside dev |
| `OPS_SERVICE_PUBLIC_KEYS` | `{}` | `{kid: {"service", "x"}}`: the services the internal app trusts |

## Operations

| Topic | Detail |
|---|---|
| Database role | The service connects as a login role that owns no table and is a member of `ops_platform_tenant`. Every transaction switches to that role; row-level security is forced on every table |
| Pre-tenant lookups | Sign-in by email, a session by id, a key by prefix and an invite by token hash are SECURITY DEFINER functions (migration 0004) owned by the NOLOGIN role `ops_platform_lookup`, whose only right is SELECT through SELECT-only policies |
| Migrator rights | Migration 0004 runs `ALTER FUNCTION … OWNER TO ops_platform_lookup`. The migrating role must be a superuser, or have CREATE on the schema and be a member of `ops_platform_lookup`. Compose's user is a superuser; a managed database usually needs the grant first |
| Key rotation | Publish the new public key beside the old one in the key set, switch `OPS_PLATFORM_SIGNING_KEY` and its kid, and drop the old key after the token TTL. Verifiers refetch once on an unknown kid |
| Sign-out reach | platform-service refuses a signed-out session at once; other services accept its token until it expires (15 minutes) |

## Gotchas

| Topic | Detail |
|---|---|
| Superuser hides RLS faults | The compose user bypasses row-level security, so `tests/test_least_privilege.py` runs the flows as a role that owns nothing; without migration 0004 they fail there and pass everywhere else |
| Definer functions and temp tables | Postgres searches a session's temporary schema first unless a function names `pg_temp` in its search_path, so a temp `users` table could shadow what a lookup reads. The lookups pin `pg_catalog, public, pg_temp` and qualify every table (migration 0005) |
| Foreign keys ignore RLS | A single-column reference let a tenant's row point at another tenant's team; every reference carries `tenant_id` (migration 0002) |
| String annotations and FastAPI | `api/app.py` has no `from __future__ import annotations`: its routes depend on functions local to the factory |
| Test teams | Fixtures create teams with scope `owned`; a scope `all` team reads the whole tenant and would hide team scoping |

## Not built yet

| Item | Where it goes |
|---|---|
| agents-service and tools-service resolving callers through `ops_identity`, with RLS on their tables (uc-022, uc-024) | The adoption card |
| SSO and OIDC sign-in, MFA, step-up moving here | Later slices of `docs/specs/sign-in-and-sessions.md` |
| Sending invitations by mail | The notifications slice; today the admin shares the link from the invite response |
| A pushed revocation list | Only if 15 minutes of reach after sign-out proves too long |
