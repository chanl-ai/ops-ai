# platform-service: working rules

Status: current.

The platform service (`ops_platform`) is the identity issuer. It owns tenants, teams, users, members, roles and
custom roles, sessions, invites, API keys, sign-in settings (password, OIDC, SAML, domain proof) and the audit log,
and it is the only service that mints identity tokens. It routes no other service's traffic: every other service
verifies callers locally with `packages/ops_identity` against this service's published key set
(`GET /.well-known/jwks.json`).

One process serves two apps (`src/ops_platform/__main__.py`): the public app on :8710 (`create_public_app`,
`api/app.py:195`) and the internal app on :8711 (`create_internal_app`, `api/app.py:1209`), which is never published
and answers only service tokens: API-key introspection (`/v1/auth/introspect`), acting-for tokens and the permission
version. Shared service rules: [services/CLAUDE.md](../CLAUDE.md). Cross-folder rules:
[root guide](../../CLAUDE.md#folder-guides).

## Code

| Path | Holds |
|---|---|
| `src/ops_platform/api/app.py`, `api/schemas.py` | Both apps' routes and their models |
| `src/ops_platform/auth.py`, `passwords.py`, `sso.py`, `signin_*.py` | Sign-in, step-up, lockout; protocols from `packages/ops_signin` |
| `src/ops_platform/keys.py`, `api_keys.py`, `acting_for.py` | Token signing (Ed25519), API keys, acting-for tokens |
| `src/ops_platform/roles.py`, `policies.py`, `access_check.py` | Roles grid, team policies, the "why can I" answer |
| `src/ops_platform/teams.py`, `tenants.py`, `team_admin.py`, `workspace_lifecycle.py` | Teams and workspaces |
| `src/ops_platform/bootstrap.py`, `seed.py` | The first admin (`scripts/dev_admin.py` calls it during `make up`) and the dev seed |
| `src/ops_platform/store/` | All database code; `store/tenancy.py:27` names the tenant role `ops_platform_tenant` |
| `seed/people.json`, `seed/dev-roles.json` | The seeded people and the role → person map that `make api AS=<role>` signs in as |
| `migrations/` | Its own chain, version table `alembic_version_platform`; row security in the chain |
| `tests/` | Sign-in, sessions, roles, members, API keys, audit, RLS (`test_rls.py`), SAML security, migrations |

## Run, test, lint

From this folder (`make help` lists every target):

| Task | Command |
|---|---|
| Serve in the foreground on :8710 and :8711 | `make stop`, then `make run` (in dev it seeds `team_ops` and signs with the dev key) |
| Its tests | `make test`, or from the root `make test PKG=services/platform-service` |
| One test file | `PYTEST_ADDOPTS=tests/test_auth.py make test`: this Makefile ignores `T=` |
| Lint, types, OpenAPI | `make lint`, `make typecheck`, `make openapi-check` |
| Regenerate `openapi.json` | `uv run python scripts/check_openapi.py --write`, or `make openapi` at the root (this Makefile has no `openapi` target) |
| Apply the chain | `make migrate` |
| Background process | `make logs FOLLOW=0`, `make health` |

## Try it as a person

```bash
make api GET /v1/me AS=viewer SVC=platform
make api GET /v1/me/permissions AS=viewer SVC=platform
make api GET /v1/audit AS=admin SVC=platform Q='pageSize=5'
make sdk-call CALL='ops.raw.platform.me_me()' AS=builder
```

`make api` signs in through `POST /v1/auth/sign-in` with the dev password, so these calls exercise this service's
real sign-in path. Reference: [make/CLAUDE.md](../../make/CLAUDE.md).

## Rules for this service

| Rule | Detail |
|---|---|
| One issuer | No other service mints a platform, refresh, step-up or acting-for token; they verify |
| Short tokens | Platform tokens live 15 minutes, service tokens 60 seconds, step-up tokens 5 minutes; refresh tokens rotate and a reused one ends the session |
| Secrets at rest | API key secrets are shown once and stored as SHA-256; sign-in secrets are sealed |
| Internal port | `:8711` stays on localhost or the private network; a new internal route goes on the internal app and depends on `CurrentService` |
| Audit | Every change to identity, roles, keys and sign-in settings writes an audit row; tests assert it |
| People in tests | Use the seeded roles (`seed/dev-roles.json`); never a real address |

## Reference docs

| Doc | Covers |
|---|---|
| [docs/services/platform-service/overview.md](../../docs/services/platform-service/overview.md) | Credentials, routes, sign-in providers, operations |
| [docs/architecture/identity-and-tenancy.md](../../docs/architecture/identity-and-tenancy.md) | Trust rules every service follows |
| [docs/architecture/roles-and-permissions.md](../../docs/architecture/roles-and-permissions.md) | The roles grid behind `can()` |
| [docs/usecases/platform-service/](../../docs/usecases/README.md) | 22 use cases (sign-in, members and roles, audit, boundary) |
| [openapi.json](openapi.json) | Both apps' operations |
