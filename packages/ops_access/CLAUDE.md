# ops_access: working rules

Status: current.

What a caller may do. It holds the fixed catalogue of areas and actions, the built-in roles as data, the workspace
policies an admin may switch on, and `can()`, the one permission check every service calls. The repo's rule "No hard
coding" lands here: who may do what is decided only by `can()` over the roles grid and the policies, with open
defaults. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is |
|---|---|
| `catalogue` | `AREAS`, `ACTIONS`, `BUILTIN_ROLES`, `Grant`, `Assignment`, `effective`, `scope_in`, `encode_grid`, `decode_grid`, `SECURITY_TEAM_ACTIONS`, `ANY_TEAM` |
| `check` | `can(principal, area, action, *, team, owner, not_by, requested_by, ...)` returning a `Scope`, `Access`, `Grids` (cached by tenant and permission version), `who_can`, `granted_by`, `require_provisioner`, `KEY_GRANTS` |
| `policies` | `POLICIES` with open defaults, `policy(principal, key)`, `check_value`, publish modes |
| `platform_events` | `platform_events_router(handlers)`: the one `POST /v1/platform-events` route a service serves for platform-service's outbox events |

## Contract with callers

| Caller kind | What `can()` reads (`src/ops_access/check.py:1`) |
|---|---|
| Person | Role ids per team from the token's `access` claim, and the role grids the token carries |
| API key | `KEY_GRANTS`, in its own team only |
| Service | The `area:action` scopes its service token lists, nothing else |
| Dev header caller | Every role rule, in dev only |

- A person acts in the team the record belongs to, which must be the request's team (403 `team_forbidden`), except the
  Security team's actions. `not_by` and `requested_by` enforce separation of duties and bind the dev caller too.
- A refusal says who can, in words (`who_can`: "a Builder or Admin"); never write a role name into a refusal by hand.
- Never check a role name, an owner, an id prefix or a flag in service code. A shape that decides access outside
  `can()` must be listed in `access-exceptions-allowlist.txt`, or `scripts/check_access_exceptions.py` fails.
- The built-in grid in `docs/architecture/roles-and-permissions.md` is generated from this package; change the code,
  then rewrite the table.

Depends on `ops_identity` and `ops_service_kit`. Depended on by agents-service, documents-service, files-service,
models-service and platform-service.

## Run and test

| Task | Command |
|---|---|
| The suite (24 tests, under 10 s) | `make test PKG=packages/ops_access` |
| One file | `make test PKG=packages/ops_access T=tests/test_can.py` |
| Roles table in the docs | `uv run python scripts/roles_matrix.py --check` (rewrite without `--check`) |
| Access decisions outside `can()` | `uv run python scripts/check_access_exceptions.py` |
| Built-in roles match the checks | `uv run pytest -q scripts/tests/test_builtin_roles_match_checks.py` |
| Lint, format, types | `uv run ruff check packages/ops_access`, `uv run ruff format --check packages/ops_access`, `uv run pyright packages/ops_access` |
| A refusal as a real person | `make api GET /v1/<route> AS=viewer` ([calling the API as a person](../../CLAUDE.md#calling-the-api-as-a-person)) |

## Gotchas

| Gotcha | Rule |
|---|---|
| A token issued before the `access` claim existed carries only `roles` | `can()` maps them through the membership mapping; keep that mapping when roles change |
| Grids are cached by (tenant, permission version) | The version rises with every role, assignment or membership change, so a grid change needs no cache flush |
| Platform events are delivered at least once | Every handler passed to `platform_events_router` is idempotent |

## Reference docs

- [docs/architecture/roles-and-permissions.md](../../docs/architecture/roles-and-permissions.md): the grid, the policies and the exceptions register
- [docs/architecture/identity-and-tenancy.md](../../docs/architecture/identity-and-tenancy.md)
