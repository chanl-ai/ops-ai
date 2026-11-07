# Packages: working rules

Status: current.

`packages/` holds the shared libraries the services build on. Each Python package is a uv workspace member with its
own `pyproject.toml` and one importable module under `src/` (the folder `ops_store` holds `src/ops_store/`; the folder
`contracts` holds `src/ops_contracts/`). `usecase-runner` is the one TypeScript package. Each package folder has its
own `CLAUDE.md`; the rules that hold in every folder of the repo are in the root guide
([onion order](../CLAUDE.md#onion-order), [one local stack](../CLAUDE.md#one-local-stack),
[tests](../CLAUDE.md#tests), [commits](../CLAUDE.md#commits)).

## Rules a package follows

| Rule | What it means here | Enforced by |
|---|---|---|
| No service imports | A package never imports `ops_agents`, `ops_tools`, `ops_platform`, `ops_models`, `ops_kb`, `ops_files` or `ops_documents` | `.importlinter` contract "Libraries never import a service" (`uv run lint-imports --no-logo`) |
| No one service's rules | A package holds mechanism; which calls need an approval, which provider a workspace uses, what an event starts are the caller's. It receives what it needs as arguments, ports or run config | Review |
| Database code only in stores | SQLAlchemy, asyncpg and Alembic are imported only by `ops_store`, `ops_checkpointer` (`saver`, `tables`) and `ops_engine.store` | `.importlinter` contract "Database drivers, SQLAlchemy and Alembic only in store packages" |
| Portable SQL | Database-specific SQL (RETURNING, ON CONFLICT, SKIP LOCKED, advisory locks, JSONB, `with_for_update`) lives only in `ops_store.dialect` | `uv run python scripts/check_portable_store.py --strict` |
| Env read in one place | Only `ops_service_kit.settings` reads the environment; a package takes a `Settings` or plain values | `grep -rln "os.environ" packages/*/src` finds only `settings.py` |
| Names say what the library does | No `shared`, `common` or `utils` packages | Review |

Two packages sit outside the import contracts: `ops_pii` and `ops_plugin_sdk` are not in `.importlinter`'s
`root_packages`, so a service import added to either would not be caught.

## Run, test and lint one package

Run from the repo root. `make test` creates a throwaway database on the stack's PostgreSQL (`make db-up` is its
prerequisite and runs first), so a package suite never touches the stack's own database.

| Task | Command |
|---|---|
| One package's tests | `make test PKG=packages/ops_policy` |
| Some test files | `make test PKG=packages/ops_signin T="tests/test_password.py tests/test_oidc.py"` |
| What changed since `origin/main`, with every dependant | `make test` (`scripts/verify-changed.sh`) |
| Who depends on a package | `uv run python scripts/dependants.py packages/ops_store` (`--direct` for direct dependants only) |
| Lint and format | `uv run ruff check packages/<x>` and `uv run ruff format --check packages/<x>` |
| Types | `uv run pyright packages/<x>`; inside the folder use `uv run pyright .`, since a bare `uv run pyright` there checks the whole repo |
| Import contracts | `uv run lint-imports --no-logo` |
| The TypeScript package | `make usecase-runner-test` |

A change to a package runs its own tests and the suites of every package and service that depends on it, directly or
through another package (`scripts/dependants.py` reads each member's `pyproject.toml`). Changing `ops_store`,
`ops_identity` or `ops_service_kit` therefore runs almost every service suite.

## What `make verify` runs for packages

| Pool job (`make/python.mk`) | Packages |
|---|---|
| `pool-packages` | `ops_ingest`, `ops_policy`, `ops_identity`, `ops_access`, `ops_email`, `ops_signin`, `ops_service_kit`, plus `ops_store`'s `tests/test_schema_version.py` |
| `pool-store` | `ops_store`, on its own test database |
| `pool-engine` | `ops_engine`, on its own test database |
| `pool-pyright` | `uv run pyright packages` |

Gap: `ops_extract` and `ops_plugin_sdk` have test suites that no pool job runs, so a full `make verify` skips them.
They run when they change (`make test` with no `PKG`, and CI's per-package job). Packages with no tests of their own
are covered by the services that use them; each package's `CLAUDE.md` names where.

## Packages

| Folder | Module | Tests here |
|---|---|---|
| [contracts](contracts/CLAUDE.md) | `ops_contracts` | none |
| [ops_access](ops_access/CLAUDE.md) | `ops_access` | yes |
| [ops_agent_kernel](ops_agent_kernel/CLAUDE.md) | `ops_agent_kernel` | none (in agents-service) |
| [ops_checkpointer](ops_checkpointer/CLAUDE.md) | `ops_checkpointer` | none (in agents-service) |
| [ops_documents_client](ops_documents_client/CLAUDE.md) | `ops_documents_client` | none |
| [ops_email](ops_email/CLAUDE.md) | `ops_email` | yes |
| [ops_engine](ops_engine/CLAUDE.md) | `ops_engine` | yes |
| [ops_extract](ops_extract/CLAUDE.md) | `ops_extract` | yes |
| [ops_files_client](ops_files_client/CLAUDE.md) | `ops_files_client` | none |
| [ops_identity](ops_identity/CLAUDE.md) | `ops_identity` | yes |
| [ops_ingest](ops_ingest/CLAUDE.md) | `ops_ingest` | yes |
| [ops_metering](ops_metering/CLAUDE.md) | `ops_metering` | none |
| [ops_pii](ops_pii/CLAUDE.md) | `ops_pii` | none |
| [ops_plugin_sdk](ops_plugin_sdk/CLAUDE.md) | `ops_plugin_sdk` | yes |
| [ops_policy](ops_policy/CLAUDE.md) | `ops_policy` | yes |
| [ops_service_kit](ops_service_kit/CLAUDE.md) | `ops_service_kit` | yes (flags only) |
| [ops_signin](ops_signin/CLAUDE.md) | `ops_signin` | yes |
| [ops_storage](ops_storage/CLAUDE.md) | `ops_storage` | none (in files-service) |
| [ops_store](ops_store/CLAUDE.md) | `ops_store` | yes |
| [usecase-runner](usecase-runner/CLAUDE.md) | `@ops-ai/usecase-runner` | yes |

Design docs for packages live in `docs/packages/<folder>/` where they exist, and in
[docs/architecture/service-map.md](../docs/architecture/service-map.md) for how packages and services fit together.
