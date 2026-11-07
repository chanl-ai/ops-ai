# ops_service_kit: working rules

Status: current.

What every service shares at its edges: the settings class (the only code in the repo that reads the environment),
the response envelope and its error handlers, the error classes, ids, logging, request timing, feature flags, the
OpenAPI gate, and the test-only helpers that keep a suite off the stack's database and OPA. Package rules and test
commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

## What it owns

| Module | What it is | Used by |
|---|---|---|
| `settings` | `Settings` (pydantic-settings, prefix `OPS_`, secrets as files from `/run/secrets` or `OPS_SECRETS_DIR`, empty values unset) | every service and most packages |
| `http` | `Envelope`, `ErrorEnvelope`, `ListResult`, `Pagination`, `ok()`, `paged()`, `page_window()`, `options_page()`, `install_error_handlers()`, `mark_public()`, `operation_id()` | every service's routes |
| `errors` | `ApiError` and its subclasses (`ValidationFailed`, `Unauthorized`, `Forbidden`, `NotFound`, `Conflict`, `Unprocessable`, `TooManyRequests`, `ServiceUnavailable`, `StepUpRequired`), turned into `{success: false, error: {code, message, status}}` | services and packages |
| `ids` | `new_id`, `now_iso`, `canonical_json`, `input_hash`, `action_id` | kernel and services |
| `logging` | `get_logger` (bound context fields), `configure_logging`, `request_logger` | services |
| `request_timing` | The request id that follows a call across services; with `OPS_REQUEST_TIMING` a JSON line per request and `Server-Timing` | installed by `install_error_handlers` |
| `flags` | Feature flags: off unless `OPS_FLAGS` names them; read through `Settings.feature_flags` | services |
| `credentials` | `credential_store(settings)`: picks the `ops_policy` credential store from settings | services that keep secrets |
| `model_calls` | `StructuredCalls`: one structured model call through models-service for a service that is not an agent | documents-service |
| `background` | The `/health/background` answer shape | services |
| `contract` | `response_checker(app)`: an httpx hook that checks every test response against the app's own OpenAPI document | service tests (`testing` extra) |
| `openapi` | `report(...)`: the OpenAPI gate each service's `scripts/check_openapi.py` runs | service scripts (`testing` extra) |
| `testdb` | `refusal` and `isolate_from_stack`: a test refuses any PostgreSQL database except `OPS_TEST_DATABASE_URL` | service conftests |
| `opa_server`, `harness_containers` | A private OPA container per test session, and container cleanup for killed runs | tests and use cases only |
| `testapps` | Frees the FastAPI app a test built | tests |

## Contract with callers

- Read configuration only through `Settings`; add a new setting there with a default and a validator, never an
  `os.environ` read elsewhere. `grep -rln "os.environ" packages/*/src` lists only `settings.py`.
- `Settings` refuses unsafe combinations at start: `auth_mode` `dev` outside `environment=dev`, and the in-memory
  credential store outside dev and test (`src/ops_service_kit/settings.py:454`).
- Routes return hand-built JSON through `ok()`, which FastAPI does not validate. `contract.response_checker` closes the
  gap in each service's tests, and `openapi.report` keeps every operation typed, named `<tag>_<handler>` and marked
  `x-ops-public`.
- `contract`, `openapi`, `opa_server`, `harness_containers` and `testdb` are for scripts and tests; the `testing` extra
  (`pyproject.toml:10`) installs their dependencies, and a running service never imports them.

Depends on `ops_policy` and lists `ops_contracts`, though no module here imports it. Every Python service and seven
packages depend on it, so a change here runs nearly every suite under `make test` with no `PKG`.

## Run and test

| Task | Command |
|---|---|
| Its own tests (flags only, 11 tests) | `make test PKG=packages/ops_service_kit` |
| One file | `make test PKG=packages/ops_service_kit T=tests/test_flags.py` |
| Lint, format, types | `uv run ruff check packages/ops_service_kit`, `uv run ruff format --check packages/ops_service_kit`, `uv run pyright packages/ops_service_kit` |
| The OpenAPI gate on one service | `make -C services/files-service openapi-check` (each service with a committed `openapi.json` has the target) |

Most of this package is tested through the services: only `flags` has tests here.

## Gotchas

| Gotcha | Rule |
|---|---|
| `Settings.seed_dir` defaults to `services/agents-service/seed` (`src/ops_service_kit/settings.py:26`), a service path inside a package; outside dev it is cleared unless set | Known departure in `docs/architecture/service-map.md`, "Steps left" |
| A model key keeps its provider's name (`OPENAI_API_KEY`), unlike every other setting | The same secrets serve every service |

## Reference docs

- [docs/architecture/api.md](../../docs/architecture/api.md): the envelope, pagination and errors
- [docs/architecture/make.md](../../docs/architecture/make.md), "Environment": the `OPS_*` values make sets
- [docs/architecture/service-map.md](../../docs/architecture/service-map.md): what moves into this package next
