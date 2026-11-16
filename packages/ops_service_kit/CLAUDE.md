# ops_service_kit: working rules

Status: current.

What every service shares at its edges: the settings class (the only code in the repo that reads the environment),
the response envelope and its error handlers, the error classes, ids, logging, request timing, feature flags, the
OpenAPI gate, and the test-only helpers that keep a suite off the stack's database and OPA. Package rules and test
commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is | Used by |
|---|---|---|
| `settings` | `Settings` (pydantic-settings, prefix `OPS_`, secrets as files from `/run/secrets` or `OPS_SECRETS_DIR`, empty values unset); `Endpoint` (another service's address, timeout and retries), `PoolSettings` (`OPS_DB__*`), `Settings.require(...)` and `Settings.endpoint(name)` | every service and most packages |
| `http` | `In` (every request body: refuses unknown fields), `Out` (every reply and store row: frozen, refuses unknown fields), `Passthrough` (a body forwarded whole), `Envelope`, `ErrorEnvelope`, `ListResult`, `LabelledListResult`, `Pagination`, `ok()`, `paged()`, `pagination()`, `page_window()`, `options_page()`, `install_error_handlers()`, `mark_public()`, `operation_id()` | every service's routes |
| `listing` | `ListQuery` (`ListParams`, `list_params`): the query every list route takes; page size capped at `OPS_PAGE_SIZE_MAX`, every other query key a filter | every list route, with `ops_store.listing.list_page` |
| `errors` | `ApiError` and its subclasses (`ValidationFailed`, `Unauthorized`, `Forbidden`, `NotFound`, `Conflict`, `Unprocessable`, `TooManyRequests`, `ServiceUnavailable`, `StepUpRequired`), turned into `{success: false, error: {code, message, status}}` | services and packages |
| `ids` | `new_id`, `now_iso`, `canonical_json`, `input_hash`, `action_id` | kernel and services |
| `logging` | `get_logger`, `configure_logging(service=)`, `add_context`, `json_formatter`, `redact`: one JSON line per event on stdout ([docs/packages/ops_service_kit/logging.md](../../docs/packages/ops_service_kit/logging.md)) | services |
| `request_timing` | The request id that follows a call across services, one `http.request` line per request (with `db.query_count`, `db.tx_count`, `db.tx_open_ms`, `db.connection_count`, the pool's `db.pool.wait_ms`, `in_use` and `limit`, and `http.client.call_count` and `http.client.calls_in_tx` from `ServiceClient`), `note_caller` for its tenant and team; with `OPS_REQUEST_TIMING` also `Server-Timing` | installed by `install_error_handlers` |
| `testing` | `budget_check`: the statement budget fixture, undecorated (a service's conftest wraps it with `pytest.fixture`, since the kit does not depend on pytest); it calls every GET at 5 and 50 rows and names the routes over their `budgets.toml` row (statements, transactions, connections, service calls inside a transaction); `logging.captured_logging` reads the lines | a service's tests |
| `flags` | Feature flags: off unless `OPS_FLAGS` names them; read through `Settings.feature_flags` | services |
| `credentials` | `credential_store(settings)`: picks the `ops_policy` credential store from settings | services that keep secrets |
| `model_calls` | `ModelCalls`: one structured model call through models-service for a service that is not an agent | documents-service |
| `background` | The `/health/background` answer shape | services |
| `contract` | `response_checker(app)`: an httpx hook that checks every test response against the app's own OpenAPI document; `boundaries(app)`: each route whose body is not an `In` or reply not an `Out` (`scripts/check_typed_boundaries.py`) | service tests (`testing` extra) |
| `openapi` | `report(...)`: the OpenAPI gate each `services/<x>/scripts/check_openapi.py` runs | service scripts (`testing` extra) |
| `testdb` | `refusal` and `isolate_from_stack`: a test refuses any PostgreSQL database except `OPS_TEST_DATABASE_URL` | service conftests |
| `opa_server`, `harness_containers` | A private OPA container per test session, and container cleanup for killed runs | tests and use cases only |
| `testapps` | Frees the FastAPI app a test built | tests |
| `template_merge` | `merge(base, yours, template, fields)` and `apply(...)`: the field-by-field rule a team's copy of a template takes an update by (kept, taken, conflict); pure, no input or output | agents-service, documents-service |

## Contract with callers

- Read configuration only through `Settings`; add a new setting there with a default and a validator, never an
  `os.environ` read elsewhere. `grep -rln "os.environ" packages/*/src` lists only `settings.py`.
- `Settings` refuses unsafe combinations at start: `auth_mode` `dev` outside `environment=dev`, and the in-memory
  credential store outside dev and test (`_refuse_dev_auth_outside_dev` in `src/ops_service_kit/settings.py`).
- `auth_mode` defaults to `platform`. The fixed dev user is asked for by name: `scripts/stack.sh` and the use-case
  harnesses set `OPS_AUTH_MODE=dev`, and a test run gets it from `isolate_from_stack()` in its conftest.
- Another service is an `Endpoint` on `Settings` (`agents`, `tools`, `kb`, `files`, `documents`,
  `platform_internal`), set by its address alone (`OPS_AGENTS_URL`) or whole (`OPS_AGENTS__URL`,
  `OPS_AGENTS__TIMEOUT_S`, `OPS_AGENTS__RETRIES`). A process names the ones it cannot run without in
  `settings.require(...)`, first in its `__main__`, and exits naming each unset one; `settings.endpoint(name)` raises
  the same name later. No address falls back to this machine (`scripts/check_config_literals.py`).
- Routes return hand-built JSON through `ok()`, which FastAPI does not validate. `contract.response_checker` closes the
  gap in each service's tests, and `openapi.report` keeps every operation typed, named `<tag>_<handler>` and marked
  `x-ops-public`.
- `contract`, `openapi`, `opa_server`, `harness_containers` and `testdb` are for scripts and tests; the `testing` extra
  (`pyproject.toml:10`) installs their dependencies, and a running service never imports them.

Depends on `ops_policy`, `ops_pii` and structlog, and lists `ops_contracts`, though no module here imports it. Every Python service and seven
packages depend on it, so a change here runs nearly every suite under `make test` with no `PKG`.

## Run and test

| Task | Command |
|---|---|
| Its own tests (flags, embedding and endpoint settings, logging) | `make test PKG=packages/ops_service_kit` |
| The configuration ratchet and the boot test of every service process | `uv run python scripts/check_config_literals.py --strict`, `uv run pytest -q scripts/tests/test_boot_requires_endpoints.py` |
| One file | `make test PKG=packages/ops_service_kit T=tests/test_flags.py` |
| Lint, format, types | `uv run ruff check packages/ops_service_kit`, `uv run ruff format --check packages/ops_service_kit`, `uv run pyright packages/ops_service_kit` |
| The OpenAPI gate on one service | `make -C services/files-service openapi-check` (each service with a committed `openapi.json` has the target) |

Most of this package is tested through the services; `flags`, embedding settings and `logging` have tests here.

## Gotchas

| Gotcha | Rule |
|---|---|
| `Settings.seed_dir` defaults to `services/agents-service/seed` (`src/ops_service_kit/settings.py:26`), a service path inside a package; outside dev it is cleared unless set | Known departure in `docs/architecture/service-map.md`, "Steps left" |
| A model key keeps its provider's name (`OPENAI_API_KEY`), unlike every other setting | The same secrets serve every service |

## Reference docs

- [docs/architecture/api.md](../../docs/architecture/api.md): the envelope, pagination and errors
- [docs/architecture/make.md](../../docs/architecture/make.md), "Environment": the `OPS_*` values make sets
- [docs/architecture/service-map.md](../../docs/architecture/service-map.md): what moves into this package next

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [configuration](../../docs/architecture/standards/configuration.md) (`CF1` to `CF6`), [API contracts and models](../../docs/architecture/standards/api-and-models.md) (`AP1` to `AP7`, `MD1` to `MD4`), [errors, logging and observability](../../docs/architecture/standards/observability.md) (`OB1` to `OB6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
