# Services: working rules

Status: current.

`services/` holds the deployable Python services. Each is a FastAPI app in its own uv workspace member, named after
the console section it serves, with its own tables, migration chain and OpenAPI document. Reusable libraries live in
`packages/`; the rules every folder shares (onion order, the one stack, testing as a person, targeted tests, commit
gates) are in the root guide and are not repeated here:
[onion order](../CLAUDE.md#onion-order), [one local stack](../CLAUDE.md#one-local-stack),
[calling the API as a person](../CLAUDE.md#calling-the-api-as-a-person), [tests](../CLAUDE.md#tests),
[commits](../CLAUDE.md#commits). Every make target is described in [make/CLAUDE.md](../make/CLAUDE.md) and
[docs/architecture/make.md](../docs/architecture/make.md).

## Services

| Folder | Module | Port | Owns | Guide |
|---|---|---|---|---|
| `agents-service/` | `ops_agents` | 8700 (and the worker) | Agents, workflows, versions, chat, runs, cases, Reviews, channels | [CLAUDE.md](agents-service/CLAUDE.md) |
| `tools-service/` | `ops_tools` | 8720 | Tool egress: modules, apps and accounts, secrets, OPA decisions, the call log, plugins | [CLAUDE.md](tools-service/CLAUDE.md) |
| `platform-service/` | `ops_platform` | 8710, internal 8711 | Tenants, teams, members, sessions, API keys, audit; the only token issuer | [CLAUDE.md](platform-service/CLAUDE.md) |
| `models-service/` | `ops_models` | 8730 | Model egress: provider connections, aliases, model keys and budgets, call log | [CLAUDE.md](models-service/CLAUDE.md) |
| `kb-service/` | `ops_kb` | 8740 | Knowledge bases, sources, sync and cited retrieval | [CLAUDE.md](kb-service/CLAUDE.md) |
| `files-service/` | `ops_files` | 8750 | File bytes, versions, references, legal holds, storage settings | [CLAUDE.md](files-service/CLAUDE.md) |
| `documents-service/` | `ops_documents` | 8760 | Extractions, document types, layouts, templates; never bytes | [CLAUDE.md](documents-service/CLAUDE.md) |
| `runner-service/` | `ops_runner` | 8770 | Code tools' Python on WASM; no database | [CLAUDE.md](runner-service/CLAUDE.md) |
| `hitl-service/` | none | none | Stub folder; Reviews live in agents-service | [CLAUDE.md](hitl-service/CLAUDE.md) |

`make up` runs all of them except hitl-service; `make health` lists each with its port and pid.

## The verb set

Every service Makefile answers the verbs in `make/services.mk` (`install run stop test lint typecheck verify migrate
logs health clean`), so these work from a service folder or from the root as `<verb>-<svc>` (`make test-kb`):

| Verb | What it runs |
|---|---|
| `make run` | The service in the foreground on its port. Stop the `make up` copy first (`make stop`) or the port is taken |
| `make test` | pytest on a throwaway database made by `scripts/test_db.py` (`OPS_TEST_DATABASE_URL`, never the stack's) |
| `make lint` | `ruff format --check` and `ruff check` over the service's Python folders |
| `make typecheck` | strict pyright |
| `make verify` | lint, typecheck, test and the OpenAPI gate (agents-service also runs its standards check) |
| `make migrate` | `alembic upgrade head` on the service's own chain |
| `make openapi` / `make openapi-check` | `scripts/check_openapi.py --write` / the check |

Run one file from the root with `make test PKG=services/<x> T=tests/<file>.py`. Only agents-service and
tools-service pass `T=` to pytest today; the other Makefiles ignore it and run the whole suite. For those, name the
files in `PYTEST_ADDOPTS` instead: `PYTEST_ADDOPTS=tests/test_health.py make test PKG=services/kb-service`.

On the live stack, exercise a service through the root's make targets (`api`, `chat`, `kb-*`, `apps-*`, `tools-*`,
`runs-*`, `tasks-*`, `memories-*`), with `AS=` to act as a person, instead of ad-hoc scripts or SQL; read the database
only to diagnose, and clear what the targets made with `make test-data-clean`
([make/CLAUDE.md](../make/CLAUDE.md)).

kb-service, models-service and runner-service include `make/service-stub.mk`, so their `stop`, `logs` and `health`
answer "not started" even though `make up` runs them; use the root `make logs SVC=kb` and `make health`.

## How a service is built

| Concern | Rule | Where |
|---|---|---|
| Settings | Read once from the environment by the settings class; no service reads `os.environ` | `packages/ops_service_kit/src/ops_service_kit/settings.py` |
| Envelope | Routes return `ok(data)`, which wraps `{success: true, data}`; errors raise an `ApiError` subclass (`NotFound`, `Forbidden`, `Conflict`, `ValidationFailed`, ...) and `install_error_handlers(app)` turns it into `{success: false, error: {code, message, status, requestId}}` | `packages/ops_service_kit/src/ops_service_kit/http.py:179`, `:219`; `errors.py:8` |
| Lists | Paged on the server: `paged(rows, total, page, page_size)` gives `{data, pagination, facets}`; counts and totals come from the store, never from a client | `http.py:172` |
| Caller | Every route depends on a caller from `ops_identity` (`CurrentPrincipal` for people and API keys, `CurrentService` for service tokens, `CurrentCaller` for both); only health and the OpenAPI document are open | `packages/ops_identity/src/ops_identity/fastapi.py:214` |
| Permission | `can(principal, area, action, ...)` over the roles grid decides; never a check on a role name or an id | `packages/ops_access/src/ops_access/check.py:299` |
| Tenant and team | The tenant comes from the verified token and the team from `X-Team-Id`, never from a body or path. Every isolated read and write runs in `isolation.isolated_tx(engine, role=<service>_tenant)`, which sets `app.tenant_id` and `app.team_id` for the row-level security policies in the service's migrations; team-owned tables are filtered with `team_visible(table)`. Another team's record answers 404 | `packages/ops_store/src/ops_store/isolation.py`, `team_scope.py:67` |
| Database code | Only in the service's `store/` package and in `packages/ops_store`; `.importlinter` refuses SQLAlchemy and drivers anywhere else | `.importlinter` at the root |
| Migrations | One Alembic chain per service, with its own version table (`alembic_version_<svc>`; agents-service uses the default `alembic_version`). Row security, roles and grants live in the chain | `services/<x>/migrations/versions/` |
| OpenAPI | `openapi.json` is committed and must match the app; every route named, tagged and typed, except those on `openapi-untyped.txt`, which may only shrink. Tests attach `ops_service_kit.contract.response_checker(app)` so each response is checked against the document | `scripts/check_openapi.py` in each service |
| Fixtures | Only under `tests/fixtures/`; source code never names a `tests/` path | `services/agents-service/scripts/check_standards.py` |
| Seeds | Dev records are files under `seed/`, loaded at start in dev; never definitions in code | `services/<x>/seed/` |
| Model calls in tests | Scripted model or the fake OpenAI only; `make verify` unsets the model keys | `make/python.mk` |

Adding a route: write it in the service, run its test, then `make openapi` from the root (writes every service's
document and regenerates both SDKs), then `make sdk-verify`. A new migration: `cd services/<x> && uv run alembic
revision -m "<what it changes>"`; the root `make migration NAME=...` makes an agents-service revision only.

## Cross-service rules

- A service never imports another service's code and never reads another service's tables; it calls the other
  service over HTTP with a service token (`ops_identity.ServiceClient`) or through a client package
  (`ops_files_client`, `ops_documents_client`).
- Tool calls leave only through tools-service and model calls only through models-service.
- Known departure: tools-service imports `ops_agents.activities` (`ops_tools/registry.py:14`, `tools.py:11`,
  `__main__.py:16`), and its gateway tests still live in `agents-service/tests/gateway`
  ([service map, steps left](../docs/architecture/service-map.md)).

Design for every service: [docs/architecture/service-map.md](../docs/architecture/service-map.md),
[identity and tenancy](../docs/architecture/identity-and-tenancy.md), [API conventions](../docs/architecture/api.md).
Use cases per service: [docs/usecases/](../docs/usecases/README.md).
