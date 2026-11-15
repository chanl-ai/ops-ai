# Engineering standards

Status: target state. Every rule below is the bar code must meet; code that misses one is a defect to fix, and a
review cites the rule id. This page decides how code is written. What the system does is decided by the rest of this
folder ([overview](overview.md), [service map](service-map.md), [data](data.md), [identity and
tenancy](identity-and-tenancy.md), [roles and permissions](roles-and-permissions.md), [logging and data
writes](logging-and-data-writes.md), [ADR-0017 database support](decisions/database-support.md)); where this page and
one of those disagree, that page wins and this one is corrected. Gaps between today's code and these rules are tracked
outside this page.

Each rule has an id, the rule, and the reason. The table at the end names the check that enforces each rule and
whether that check exists in the repository today.

## How to read a rule

| Term | Meaning |
|---|---|
| Must | A merge is blocked when the rule's check fails |
| Exception | Allowed only when the list the rule names records it, with a reason; the list may only shrink |
| Ratchet | A check with a committed baseline: a new finding fails, a fixed one must be removed from the baseline in the same change |
| Kit | `packages/ops_service_kit`, the one place a service gets settings, logging, the envelope, paging and errors |

## 1. Layers

The stack inside a service is `api` (routes) → `app` (use cases, the brief's "service" layer) → `store` (repositories)
→ `ops_store` (the database door). `domain` sits below `app` and imports nothing with input or output. Across the
product the order is services → OpenAPI document → SDKs → console and CLI.

```
console, CLI ──► SDK (generated + hand-written nouns) ──► HTTP ──► api ──► app ──► store ──► ops_store ──► database
                                                                      └──► domain (pure rules)
                                         adapters (HTTP clients, gateways) ◄── app, through a port
```

| Id | Rule | Reason |
|---|---|---|
| L1 | Inside a service, a module imports only its own layer or a lower one: `api` → `app` → `domain`; `app` → `store` and `adapters` through ports; `store` imports no other layer of its service | One direction keeps each layer testable alone (cosmic-python repository and service-layer patterns) |
| L2 | A route does no work beyond parsing input, resolving the caller, calling one `app` function and wrapping its result with `ok()` or `paged()` | Business rules in routes cannot be reused by the worker, the CLI or a workflow step |
| L3 | SQLAlchemy, Alembic and database drivers are imported only in a service's `store/` package, `ops_store`, `ops_engine.store` and the checkpointer | Database code in one place is what makes two databases and tenant isolation possible (ADR-0017) |
| L4 | A service never imports another service's code or reads another service's tables; it calls the other service through `ops_identity.ServiceClient` or a client package | Services must deploy alone or in one host process without hidden coupling ([service map](service-map.md)) |
| L5 | A package never imports a service. Packages hold mechanism; the rule a service applies arrives as an argument, a port or settings | A package that knows one service's rules cannot be reused by the next one |
| L6 | The console and CLI call the platform only through the SDK; the SDK calls only routes marked `x-ops-public` `sdk` or `both` | One client means one place for auth headers, the envelope, paging and errors |
| L7 | Code goes into a package when a second service needs it, and not before. Before adding a package, client, queue, scheduler or store, list what already does that job (file:line) and use it | One owner per job; a second owner needs a written reason ([root guide](../../CLAUDE.md), "Four rules") |
| L8 | Packages carry names that say what they do; no `shared`, `common`, `utils`, `helpers` or `manager` | A vague name hides that a module has more than one job |
| L9 | Anything that may later live outside us (a vault, a model provider, search, object storage) sits behind a port in `app`, with our implementation as one adapter | A bank replaces the adapter and keeps the use case |

One owner per job:

| Job | Owner |
|---|---|
| Settings | `ops_service_kit.settings` |
| Log setup and redaction | `ops_service_kit.logging` |
| Envelope, errors, paging | `ops_service_kit.http`, `ops_service_kit.errors` |
| Caller and token checks | `ops_identity` |
| Access decisions | `ops_access.can` |
| Tenant and team context, isolated transactions | `ops_store.isolation`, `ops_store.team_scope` |
| Database differences | `ops_store.dialect` |
| Audit entries and events | `ops_store.audit`, `ops_store.outbox` |
| Calls to another service | `ops_identity.ServiceClient` |
| Model calls | models-service, through `ops_service_kit.model_calls` or the agent kernel |
| Tool and outside-system calls | tools-service |
| Secret values | `ops_service_kit.credentials` over `ops_policy.CredentialStore` |

## 2. Configuration

| Id | Rule | Reason |
|---|---|---|
| C1 | Each process builds one typed settings object from `ops_service_kit.settings.Settings` (pydantic-settings, `OPS_` prefix) once at start and passes it down; no other module reads `os.environ` or `process.env` | Config in the environment, read once (twelve-factor, III) |
| C2 | No literal host, port, URL, model name, model alias, timeout, retry count, page size or limit in code outside the settings class and named constants | A value in code changes only with a release and differs silently between copies |
| C3 | A required setting with no value stops the process at start with the setting named; a missing value is never discovered by the first request | Fail fast; a half-configured service in production is worse than one that will not start |
| C4 | Secrets reach code only from the deployment's secret store, through the settings class or `ops_service_kit.credentials`; no secret in code, fixtures, seeds, `openapi.json`, logs or test output; `.env.example` is the only env file in git | OWASP ASVS V13 (configuration) and V8 (data protection) |
| C5 | A setting's default is the safe production value; a development shortcut is on only when the environment names development | A forgotten setting must not open a door in production |
| C6 | The console reads environment only in its API entry module | One switch between mock and services, in one file |

## 3. Data access

The stores use SQLAlchemy 2.x Core on `AsyncEngine` and `AsyncConnection`; there are no ORM sessions. "Session" in the
rules below means the connection and transaction `isolation.isolated_tx` opens.

| Id | Rule | Reason |
|---|---|---|
| D1 | One unit of work opens one `isolated_tx`, from the `app` layer (or one store method that is the whole unit); helpers and repository functions take the connection as an argument and never open, commit or roll back | Writes that belong together commit together; a helper that commits breaks the caller's transaction (SQLAlchemy 2.0, "Managing transactions"; cosmic-python unit of work) |
| D2 | Every read and write of a tenant-scoped table runs inside `isolated_tx`, `tenant_wide` or `system_tx`; the two widening calls take a reason that is a named constant | Row-level security and the query filter read the same context; no context raises before a connection opens |
| D3 | Every query of a team-owned table carries `team_visible(table)`; no store writes its own tenant or team `WHERE` | One filter helper, tested once, instead of a filter per query |
| D4 | Every table is marked tenant-scoped (and team-owned where it is) or `system(reason)` in its metadata | An unmarked table has no isolation policy on either database |
| D5 | Statements are built with Core (`select`, `insert`, `update`, `delete`); `text()` appears only inside `ops_store.dialect`, and never with values joined into the string | Bound parameters stop SQL injection (OWASP ASVS V5.3); Core renders for both databases |
| D6 | Database-specific SQL (upsert, row lock, queue claim, app lock, clock, JSON operators, full text) is called only through `ops_store.dialect` | Two databases, one place for their differences (ADR-0017) |
| D7 | No query inside a loop over rows; a list loads related rows with a join or one `IN` query per relation | N+1 queries grow with the page size and hide in tests with three rows |
| D8 | Each route has a statement budget: a list route runs a fixed number of statements whatever the page size, and a test fails when a route exceeds its budget | A budget turns N+1 from a review opinion into a failing test |
| D9 | Every list is paged on the server and returns `paged()`'s `{data, pagination, facets}`; page size has a maximum from settings; totals and facet counts come from the database | An unbounded list fails at the first large team, and counts computed in a browser are wrong past page one |
| D10 | Every foreign key column and every column a list filters or sorts on has an index, declared in the store metadata and the migration | Unindexed filters turn into full scans as tables grow |
| D11 | Each service has one Alembic chain with its own version table; revisions are numbered `NNNN_<what_it_changes>.py` in order; a chain has exactly one head, and two branches that both add a revision are joined by a merge revision before merge | Two heads stop `alembic upgrade head` on every database |
| D12 | Every migration has a working downgrade and uses Alembic operations that run on PostgreSQL and SQL Server | Rollbacks and the parity check need both directions on both databases |
| D13 | A column or table is dropped one release after the code stops using it | The previous build keeps running while the new one starts ([enterprise architecture](enterprise-architecture.md), "Deploy") |
| D14 | Request paths are async end to end on `AsyncEngine`; synchronous database access appears only in migrations and `scripts/` | A sync call inside the event loop stalls every request on that process |
| D15 | Time written to the database comes from the database clock (`db_now()`); a person's edit to a team-owned row goes through `ops_store.change`, `create` or `remove` with the expected revision | One clock across processes; a stale save answers `409 stale_revision` instead of overwriting ([logging and data writes](logging-and-data-writes.md)) |
| D16 | Updates use `update().where(...)` with the expected state in the `WHERE`; never read, change in Python and write back the whole row | A read-modify-write loses the other writer's change |

## 4. API and models

| Id | Rule | Reason |
|---|---|---|
| A1 | Every request body model sets `extra="forbid"`; unknown fields answer `400 validation_failed` | A misspelled field silently ignored is a lost instruction (Pydantic v2, "Extra attributes"; OWASP ASVS V5.1) |
| A2 | Every route declares its success response model and the error envelope for each status it returns; the committed `openapi.json` matches the app | The SDKs are generated from the documents, so an undeclared response is an untyped SDK method |
| A3 | Each contract has one model, in the service that owns it; the SDKs and console get it through `make openapi` and the generator; no model is copied by hand into another service, the SDK or the console | Copies drift, and the drift shows up in production |
| A4 | `model_construct` and `model_validate(..., strict=False)` shortcuts are never applied to input from a caller, a tool or a model | `model_construct` skips validation (Pydantic v2 docs) |
| A5 | Success is `{success: true, data}` through `ok()` or `paged()`; failure is an `ApiError` subclass rendered as `{success: false, error: {code, message, status, requestId, details?}}`; codes are named constants | One shape lets every client handle errors once ([API](api.md), "Request conventions") |
| A6 | An error message never carries a stack trace, SQL, a secret, a token or another team's data; the request id ties it to the log line | OWASP ASVS V7.4 (error handling) |
| A7 | Every route depends on a caller from `ops_identity`; only health and the OpenAPI document are open | No anonymous path into data |
| A8 | Every write route accepts an idempotency key or a natural key (`runId`, `externalKey`) and returns the first result for a repeat | Clients and relays retry; a repeat must not act twice |
| A9 | Route ids, tags and `x-ops-public` come from the kit's helpers; a route breaking its contract ships as a new route or a backwards-compatible field, never an in-place change | Generated clients in the field still call the old shape |

## 5. Console and SDKs

| Id | Rule | Reason |
|---|---|---|
| U1 | A screen gets every join, total, count and filtered list it shows from one API call; the browser never joins two lists, filters a fetched list, counts or sums over it | Client-side joins are wrong past the first page and cost a request per list |
| U2 | Pages read through hooks; hooks call the API contract; the contract's HTTP implementation calls the SDK; components take props only | Each layer swaps without touching the others |
| U3 | Sample data lives only in the console mock (`apps/console/src/lib/api/mock/`) and test fixtures; a screen on real services never shows sample data or falls back to it on error | Sample data on a real screen reads as real data |
| U4 | Every list screen pages on the server through the shared list parameters and the data table | Matches D9; one table component handles paging, sorting and selection |
| U5 | Every screen has loading, empty and error states; an error shows the API's message and request id | People need to know whether there is nothing or something failed |
| U6 | The SDKs' generated layer is never edited by hand; the hand-written nouns match one for one in Python and TypeScript | The documents are the source; both languages move together ([SDK guide](../../sdk/CLAUDE.md)) |
| U7 | The CLI calls client methods only, never HTTP directly | Same reason as L6 |

## 6. Security

| Id | Rule | Reason |
|---|---|---|
| S1 | Every access decision goes through `ops_access.can()` over the roles grid and team policies; no check on a role name, an owner, an id prefix or a flag | One decision point is what an access review can audit (SOC 2 CC6.1; OWASP ASVS V4.1) |
| S2 | A refusal outside `can()` exists only when the [exceptions register](roles-and-permissions.md#exceptions-register) records it, and the allowlist names its row | A reviewer finds every exception, with its decision, in one list |
| S3 | A new permission cell, policy or approval is written in [roles and permissions](roles-and-permissions.md) in the same change, with its default and who changes it | The grid on the page is the grid in the code |
| S4 | The tenant comes from the verified token and the team from `X-Team-Id` checked against it, never from a body, path or query; another team's record answers 404 | A caller cannot name their way into another tenant (OWASP ASVS V4.2, insecure direct object reference) |
| S5 | Model calls leave only through models-service and tool or outside-system calls only through tools-service; no service other than those two opens an outbound connection to an outside host | The gateways hold the keys, check policy and log every call |
| S6 | Every write that changes what a person or system can see or do records an audit entry through `ops_store.audit` in the same transaction as the change | A change with no entry cannot be reviewed (SOC 2 CC7.2, CC8.1) |
| S7 | Logs go through `ops_service_kit.logging` only: no `print`, no `logging.basicConfig`, event names are string literals and values are keywords; `redact` runs last | Secrets and personal data are removed in one place (OWASP ASVS V7.1) |
| S8 | A secret value is written once and never returned by any route; reads return whether it is set | A secret that comes back can leak through a screen, a log or a cache |
| S9 | No dependency is added without a licence and network-behaviour entry in [dependencies](dependencies.md); a critical advisory fails the build | Banks review every package that ships |
| S10 | No committed file carries a credential, private path, tracker id or real customer data | The repository is public |

## 7. Reliability and operations

| Id | Rule | Reason |
|---|---|---|
| R1 | Every outbound HTTP call goes through `ServiceClient`, the gateways' clients or `model_calls`, with a timeout and a bounded retry from settings; no bare `httpx.AsyncClient()` in a service | A call with no timeout holds a worker forever; retries in one place stay bounded |
| R2 | A retried operation is idempotent: writes carry a key (A8), tool writes carry an approval bound to the input hash, and an outbox entry has an id the receiver dedupes on | At-least-once delivery is safe only when a repeat does nothing |
| R3 | Each log line is one JSON object with `request_id`, `tenant_id` and `team_id`; each request writes one `http.request` line naming the route template | An operator follows one request across services by id |
| R4 | Each service answers `GET /health` (process up) and `GET /ready` (database reachable, its chain at head, required settings present); a deployment routes traffic only on ready | Liveness and readiness are separate questions for a load balancer |
| R5 | Background loops report through `/health/background` in the kit's shape, and a loop that fails stops reporting healthy | A stuck sweeper is invisible without it |
| R6 | CI builds every service and the console from a clean checkout, migrates every chain on an empty PostgreSQL and an empty SQL Server, then downgrades and upgrades again | A migration that only works on a database with history fails the first install |
| R7 | Every service starts embedded in one host process or alone, chosen by settings, on one virtual machine with PostgreSQL as the only infrastructure | Every release must run on the smallest target ([service map](service-map.md#deployment-targets)) |

## 8. Testing

| Id | Rule | Reason |
|---|---|---|
| T1 | Before writing tests, list the ways the change can break; write one test per failure mode and stop | A named failure mode is what a test protects against; coverage counts lines run and misses wrong answers |
| T2 | A change adds at most 5 tests when small, 10 when medium and 15 when large; more needs a written reason | Every test costs run time and upkeep on every later change |
| T3 | Each new test is seen failing once, with the code reverted, and the failure is stated in the evidence | A test that has never failed may test nothing |
| T4 | Tests assert what a caller sees through the public seam (a route, an SDK call, a screen); fakes sit only at the edge (network, clock, model, outside APIs) | Tests on private helpers break on every refactor and miss the wiring |
| T5 | Each user-visible behaviour has a use case per layer it touches (`api`, `sdk`, `cli`, `ui`) that passes through `make usecase-test` | A unit test proves one function; the use case proves the behaviour a person sees |
| T6 | Tests and use cases run on the scripted model on a throwaway database; store tests run on PostgreSQL and SQL Server | Same answer every run, at no cost, on both supported databases |
| T7 | Tests are written by a different agent or person from the code; the coder does not edit a test after the tests commit | A second author tests the cases the coder did not think of |
| T8 | Every check on this page is shown to fail once on a planted breach before it is trusted | A check never seen failing may not detect the breach it names |
| T9 | No test of a third-party library's behaviour | Upgrading a library should not mean repairing tests that never protected us |

## 9. Delivery

| Id | Rule | Reason |
|---|---|---|
| V1 | Work lands on a branch named for its change, through a pull request into the trunk; nobody pushes to the trunk or `main`, force-pushes, stashes on a shared tree or skips hooks | Every change is reviewed and attributable (SOC 2 CC8.1) |
| V2 | A merge is blocked unless `ci-ok` passed for that commit: lint and format, strict types, import contracts, the standards checks on this page, the affected test suites on both databases, `make sdk-verify`, `pnpm verify`, the docs checks and the leak scan | One gate, the same locally (`make verify`) and in CI |
| V3 | A merge needs approval from a reviewer who did not write the change | Separation of duties for change management (SOC 2 CC8.1) |
| V4 | Each merge to the trunk deploys to staging, which migrates, checks every process and walks the console headless; a failed smoke stops promotion | Staging tests the real combination before people do |
| V5 | Production gets only a tagged commit (`vYYYY-MM-DD.N`) that staging ran; migrations apply before new processes start; rollback redeploys the previous image, and migrations only add | Promotion is repeatable and reversible |
| V6 | Commits follow `type(scope): subject` with a short body saying why the old behaviour was wrong and what ran; a user-visible `feat` or `fix` carries a What's new entry | The history explains itself to a reader with only this repository |
| V7 | A change that alters a rule on this page, a contract or a data model updates the page that owns it in the same change | Docs that lag the code stop people checking |

## Checks

"Exists" is yes only where the check is a file in this repository today. A "no" names the kind of check the rule needs.

| Id | Area | Enforcing check | Exists |
|---|---|---|---|
| L1 | Layers | `services/agents-service/scripts/check_standards.py` rule 1 (agents-service order); an import-linter `layers` contract per service | yes |
| L2 | Layers | AST rule: a route body calls one `app` function and no store | no |
| L3 | Layers | `.importlinter` contract `drivers-only-in-stores` and the `*-store-is-bottom` contracts | yes |
| L4 | Layers | `.importlinter` contract `services-independent` | yes |
| L5 | Layers | `.importlinter` contract `libraries-below-services` | yes |
| L6 | Layers | Console standards rules 2 and 3 (`apps/console/scripts/check-standards.mjs`); a rule that only `ops-sdk.ts` sends HTTP | no |
| L7 | Layers | Review, with `scripts/agents/review_context.py` listing new public surface | yes |
| L8 | Layers | Script ratchet on package and module names | no |
| L9 | Layers | Review | no |
| C1 | Config | `check_standards.py` rule 4 (env read only in `settings.py`); console standards rule 4 | yes |
| C2 | Config | Ruff custom rule or script ratchet for literal URLs, ports, hosts, model names and timeouts | no |
| C3 | Config | Boot test per service with each required setting removed | no |
| C4 | Config | `scripts/leak_scan.py` with `.github/workflows/leak-scan.yml` | yes |
| C5 | Config | Test that the settings defaults equal the production profile | no |
| C6 | Config | Console standards rule 4 | yes |
| D1 | Data | AST rule: no `commit`, `begin` or `isolated_tx` in a function that takes a connection | no |
| D2 | Data | `packages/ops_store/tests/test_isolation_sites.py`; `NoTenantError` in `isolation.py` | yes |
| D3 | Data | `scripts/team_isolation_probe.py`; `packages/ops_store/tests/test_team_visible.py` | yes |
| D4 | Data | `deploy/database/tests/test_isolation_markings.py` | yes |
| D5 | Data | `scripts/check_portable_store.py --strict`; a rule against string-built `text()` | yes |
| D6 | Data | `scripts/check_portable_store.py --strict` with `portable-baseline.txt` | yes |
| D7 | Data | Statement-count test (D8) | no |
| D8 | Data | Test fixture counting statements per request from the listener in `packages/ops_store/src/ops_store/database.py`, with a budget per route | no |
| D9 | Data | OpenAPI rule: every list operation returns the paged shape; maximum page size test | no |
| D10 | Data | Metadata test: every foreign key and filter column has an index | no |
| D11 | Data | CI test: one Alembic head per chain | no |
| D12 | Data | `scripts/check_downgrades.py`; `deploy/database/tests/test_model_parity.py` | yes |
| D13 | Data | Review of drop migrations against the previous release | no |
| D14 | Data | `.importlinter` contract forbidding sync engines in service code | no |
| D15 | Data | Write rules in `scripts/check_portable_store.py` (designed in [logging and data writes](logging-and-data-writes.md)) | no |
| D16 | Data | Same write rules as D15 | no |
| A1 | API | Test that walks every route's request model and asserts `extra="forbid"` | no |
| A2 | API | `services/<x>/scripts/check_openapi.py` with `openapi-untyped.txt`; `ops_service_kit.contract.response_checker` | yes |
| A3 | API | `uv run python sdk/generate.py --check` (`make sdk-verify`); a duplicate-model scan across services and console | yes |
| A4 | API | Ruff banned-API rule on `model_construct` outside `domain` | no |
| A5 | API | `response_checker` against the documented error envelope | yes |
| A6 | API | Test that a forced 500 carries no traceback or SQL | no |
| A7 | API | `check_standards.py` rule 5 (agents-service app); the same check per service | yes |
| A8 | API | OpenAPI rule: every write operation declares an idempotency key | no |
| A9 | API | OpenAPI diff against the last release tag | no |
| U1 | Console | Console standards rule against `.filter`, `.reduce` and multi-hook joins over fetched lists | no |
| U2 | Console | Console standards rules 2, 3 and 17 | yes |
| U3 | Console | Console standards rule 1 (fixtures only in the mock) | yes |
| U4 | Console | Console standards rules 6 and 22 | yes |
| U5 | Console | `scripts/agents/ui_walk.mjs` states walk | yes |
| U6 | Console | `sdk/generate.py --check`; `make sdk-verify` | yes |
| U7 | Console | Import rule on `sdk/python/src/ops_ai/_cli/` | no |
| S1 | Security | `scripts/check_access_exceptions.py` (role-name and refusal shapes) | yes |
| S2 | Security | `scripts/check_access_exceptions.py` with `access-exceptions-allowlist.txt` | yes |
| S3 | Security | `scripts/roles_matrix.py --check` | yes |
| S4 | Security | `scripts/team_isolation_probe.py`; `packages/ops_store/tests/test_team_reads.py` | yes |
| S5 | Security | `.importlinter` contract limiting `httpx` to the clients and gateways; socket guard in tests | no |
| S6 | Security | Test over every write route asserting one audit entry per write | no |
| S7 | Security | Ruff `T20`, `G`, `LOG` (`pyproject.toml`); `packages/ops_service_kit/tests/test_logging.py`; `check_standards.py` rule 6b | yes |
| S8 | Security | `response_checker` plus a test that secret fields never appear in a response schema | no |
| S9 | Security | `.github/workflows/dependency-check.yml` (`scripts/deps_audit.py`); `.github/workflows/codeql.yml` | yes |
| S10 | Security | `scripts/leak_scan.py`; `scripts/check-public-paths.mjs` | yes |
| R1 | Reliability | `.importlinter` contract: `httpx` only in `ops_identity.client`, the gateways and `model_calls` | no |
| R2 | Reliability | `packages/ops_store/tests/test_outbox.py`; use cases for repeated writes | yes |
| R3 | Reliability | `packages/ops_service_kit/tests/test_logging.py` | yes |
| R4 | Reliability | Use case calling `/ready` with the database down and a chain behind | no |
| R5 | Reliability | Test per loop that a failure turns `/health/background` unhealthy | no |
| R6 | Reliability | `deploy/database/tests/test_runtime_logins.py` (down and up per chain); `test_mssql_ddl.py`; a CI job from an empty database | yes |
| R7 | Reliability | `deploy/host/ops_host.py --check` in `make stg-health` | yes |
| T1 | Testing | `scripts/agents/test_audit.py` (failure modes with no test) | yes |
| T2 | Testing | Script counting new tests per change against the budget | no |
| T3 | Testing | `scripts/agents/test_audit.py` mutation score on changed lines | yes |
| T4 | Testing | Review, with `test_audit.py` smells | no |
| T5 | Testing | `make usecase-test`; `scripts/agents/affected_usecases.py` | yes |
| T6 | Testing | `make/python.mk` unsets model keys; `scripts/test_db.py`; a SQL Server run of every store suite | yes |
| T7 | Testing | `scripts/agents/tests_untouched.py` | yes |
| T8 | Testing | `scripts/agents/seed_canaries.py` | yes |
| T9 | Testing | Review | no |
| V1 | Delivery | `scripts/git-rules.py`; `.githooks/`; branch protection | yes |
| V2 | Delivery | `.github/workflows/ci.yml` job `ci-ok`; `scripts/verify-staged.sh` | yes |
| V3 | Delivery | Branch protection requiring one approving review | no |
| V4 | Delivery | `.github/actions/stg-deploy` running `make stg-deploy` | yes |
| V5 | Delivery | `.github/workflows/release-tag.yml`; `make stg-rollback` | yes |
| V6 | Delivery | `scripts/commit-message-check.mjs`; `scripts/changelog-check.mjs` | yes |
| V7 | Delivery | `scripts/check-docs.mjs`; `scripts/check-guides.mjs` | yes |

## Sources

| Source | Used for |
|---|---|
| The Twelve-Factor App, III "Config" (12factor.net/config) | C1 to C3 |
| OWASP Application Security Verification Standard 4.0.3 (owasp.org/www-project-application-security-verification-standard) | V4 access, V5 input, V7 errors and logging, V8 data, V13 configuration |
| AICPA SOC 2 Trust Services Criteria, CC6 (logical access), CC7 (operations), CC8 (change management) | S1, S6, V1 to V3 |
| SQLAlchemy 2.0 docs, "Working with transactions and the DBAPI" and "Using SELECT statements" (docs.sqlalchemy.org/en/20) | D1, D5, D14 |
| Pydantic v2 docs, "Models" and "Configuration: extra" (docs.pydantic.dev) | A1, A4 |
| Percival and Gregory, *Architecture Patterns with Python*, repository, service layer and unit of work (cosmicpython.com) | L1, L2, D1 |
| Alembic docs, "Branches" and merge revisions (alembic.sqlalchemy.org) | D11 |
