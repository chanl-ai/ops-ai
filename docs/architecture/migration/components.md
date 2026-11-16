# Phase 0: the eight components

Status: current, 2026-11-15. Built once in the kit and its packages before any service moves. Up to three builders,
in the three tracks below. Each component lands with its check at today's count, so no lane can add a new breach while
the lanes run. Nothing in a service changes in this phase except where a component's test needs one adopter.

## Inputs

| Input | Where |
|---|---|
| The rules each component serves | [engineering-standards.md](../engineering-standards.md) and the pages under [standards/](../standards/) |
| What a service does today at each seam | `packages/ops_store/src/ops_store/isolation.py`, `packages/ops_service_kit/src/ops_service_kit/settings.py`, `packages/ops_store/src/ops_store/outbox.py`, the five `store/event_relay.py` files, `access-exceptions-allowlist.txt` |
| The counts the checks start from | Raw `engine.begin()` or `engine.connect()` sites 197; caught database errors that carry on 28; list slices in `api/` or `app/` 10; literal `timeout=` 58; `httpx.AsyncClient(` outside `ops_identity` 47; loopback fallbacks 13; `Relay(` constructions 5; store functions returning `dict[str, Any]` 194; `asyncio.gather(` 13 and `asyncio.create_task(` 32; `extra="allow"` 4; access decisions on the allowlist 78 |

## The components

| Id | Component | Lives in | Removes | Track | Size |
|---|---|---|---|---|---|
| C1 | Request transaction and store base | `packages/ops_store/src/ops_store/isolation.py`, new `packages/ops_store/src/ops_store/store.py`, `packages/ops_identity/src/ops_identity/fastapi.py`, `packages/ops_store/src/ops_store/database.py`, `packages/ops_service_kit/src/ops_service_kit/request_timing.py`, `packages/ops_store/tests/test_isolation_sites.py`, `packages/ops_service_kit/src/ops_service_kit/testing.py` | Stores opening their own connection as the owner; one transaction per store call; the same owner lookup in five stores; no statement budget; the pool as a library default | A | L, 3.5 to 4.5 days |
| C2 | List contract | new `packages/ops_service_kit/src/ops_service_kit/listing.py`, new `packages/ops_store/src/ops_store/listing.py`, `packages/ops_service_kit/src/ops_service_kit/http.py`, new `deploy/database/tests/test_indexes.py`, `apps/console/src/lib/api/contract.ts`, `apps/console/src/hooks/options-queries.ts` | Lists sliced in Python, paging written six ways, missing indexes, browser-side joins | A | M, 1.5 to 2 days |
| C3 | Settings and service clients | `packages/ops_service_kit/src/ops_service_kit/settings.py`, `packages/ops_identity/src/ops_identity/client.py`, `packages/ops_identity/src/ops_identity/resolve.py`, new `scripts/check_config_literals.py`, `.importlinter` | Loopback fallbacks, clients and timeouts built where used, unsafe defaults, a missing URL noticed at first call | B | M, 1.5 days |
| C4 | Relay and loop health | `packages/ops_store/src/ops_store/outbox.py`, `packages/ops_store/src/ops_store/background.py`, new `packages/ops_store/src/ops_store/testing.py` | Five copies of the relay wiring; no test that a failing loop shows as unhealthy; an audit row per idle poll | C | S, 1 day |
| C5 | Typed boundaries | `packages/ops_service_kit/src/ops_service_kit/http.py`, new `packages/ops_store/src/ops_store/rows.py`, `packages/ops_store/src/ops_store/outbox.py`, `packages/ops_store/src/ops_store/background.py`, `packages/ops_service_kit/src/ops_service_kit/contract.py`, new `scripts/check_typed_boundaries.py`, `pyproject.toml` | Bodies accepting unknown fields, eight local body bases, SQL from strings, blocking sleeps, untyped rows, bare tasks | B | M, 2 days |
| C6 | One gate | `.github/workflows/ci.yml`, new `make/checks.mk`, new `packages/ops_service_kit/src/ops_service_kit/standards.py` | Checks that never run on a pull request; a staging job that never ran; no SQL Server run; three standards checks living in one service | B, last | M, 2.5 days |
| C7 | Access decisions | `scripts/check_access_exceptions.py`, `access-exceptions-allowlist.txt`, `docs/architecture/roles-and-permissions.md`, `packages/ops_access/src/ops_access/policies.py` | Seventy-five decisions outside `can()` with no owner or outcome | C | M, 1.5 days |
| C8 | Local copies | new `packages/ops_store/src/ops_store/copies.py`, agents-service's registry migration chain, tools-service and kb-service outboxes | Screens assembled from other services' answers inside the request | C, after C1, C2 and C4 | L, 3 to 5 days |

## Target interfaces

### C1: one transaction per request

```python
# packages/ops_store/src/ops_store/isolation.py
@asynccontextmanager
async def request_transaction() -> AsyncGenerator[None]:
    """Held for one request by the Tx dependency. Opens nothing. The first isolated_tx in this asyncio task opens
    the request's connection and begins; every later isolated_tx in the same task re-enters it. Exit clears SQL
    Server's session context, then commits once, or rolls back once on an exception."""

@asynccontextmanager
async def isolated_tx(engine: AsyncEngine, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """Inside a request: re-enters the request's connection; a different role or a wider scope re-runs the context
    statement on the same connection and restores it on exit. In another task (gather branch, created task, loop,
    seed, test): its own transaction, as today. Only system_tx takes a second connection."""

# packages/ops_store/src/ops_store/store.py
class Store:
    role: ClassVar[str | None] = None

    def tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        return isolation.isolated_tx(self.engine, role=self.role)

    def attempt(self, conn: AsyncConnection) -> AbstractAsyncContextManager[None]:
        """A savepoint around a statement that may fail and be caught, so the request's connection stays usable."""

    async def owner_teams(self, conn: AsyncConnection, table: sa.Table, ids: set[str], reason: str) -> dict[str, str]:
        """The owning team of each id in one query, for deciding a refusal; never for showing the rows."""

# packages/ops_identity/src/ops_identity/fastapi.py
Tx = Annotated[None, Depends(request_tx, scope="function")]   # closes when the route function returns
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

# packages/ops_store/src/ops_store/database.py
def open_database(url: str, *, pool: PoolSettings) -> Database: ...   # OPS_DB__POOL_SIZE, __POOL_OVERFLOW, __POOL_WAIT_S

# packages/ops_service_kit/src/ops_service_kit/testing.py (no pytest import: a service's conftest makes the fixture,
# statement_budget = pytest.fixture(budget_check))
def budget_check(app, client, seed_team):
    """Seeds a team at 5 and 50 rows per list, calls every GET through the real middleware, reads db.query_count,
    db.tx_count, db.connection_count, http.client.calls_in_tx and db.tx_open_ms from the request line, and fails on a
    count that grows with rows, exceeds the budget in budgets.toml, opens more than one transaction or checks out more
    than one connection (unless listed), holds a transaction across a service hop (unless listed), or keeps it open
    longer than 2 s. Runs on both databases."""
```

Design points: a caught database error runs its statement inside `attempt()`, because PostgreSQL aborts the whole
transaction on a failed statement. A streaming route takes `Tx` and its generator's store calls open their own
transactions, so the request transaction closes before the first frame. A gather branch or a created task is its own
asyncio task and so opens its own transaction. Audit rows are written on the request connection, never inside a
savepoint, so they commit or roll back with the change (`SC2`). `system_tx` and the workers keep today's behaviour.

### C2: one way to ask for a list

```python
# packages/ops_service_kit/src/ops_service_kit/listing.py
@cache
def page_sizes() -> tuple[int, int]: ...   # Settings read once, when install_error_handlers builds the app

class ListParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(default_factory=lambda: page_sizes()[0], ge=1)   # capped at page_sizes()[1]
    search: str | None = None
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "desc"
    ids: list[str] | None = None            # exact rows, for pickers and labels
    filters: dict[str, list[str]] = {}      # every other query key

ListQuery = Annotated[ListParams, Depends(list_params)]

# packages/ops_store/src/ops_store/listing.py
async def list_page(conn, query: sa.Select, params: ListParams, *, search=(), sortable={}, default_sort,
                    filters={}, facets={}, labels={}) -> ListPage:
    """count(*), ORDER BY, LIMIT and OFFSET, one GROUP BY per facet, all on `query`; `labels` maps each facet value to
    its label in the same transaction. default_sort is required: SQL Server's OFFSET needs an ORDER BY."""

# a route, after
@router.get("", response_model=Envelope[ListResult[RunOut]])
async def list_runs(p: CurrentPrincipal, _: Tx, q: ListQuery, rt: Rt) -> JSONResponse:
    return ok(await runs.list(rt, q))
```

The response is `{data, pagination, facets}`; `apps/console/src/lib/api/contract.ts` already carries `facets` on
`ListResult`, and `ids` joins its `ListParams`. A label another service owns comes from a local copy (C8), never from
a hop while the transaction is open.

### C3: every other service is a setting

```python
# packages/ops_service_kit/src/ops_service_kit/settings.py
class Endpoint(BaseModel):
    url: HttpUrl
    timeout_s: float = 10.0
    retries: int = Field(2, ge=0)

class PoolSettings(BaseModel):
    size: int = 5
    overflow: int = 10
    wait_s: float = 30.0

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPS_", env_nested_delimiter="__")
    auth_mode: Literal["dev", "platform"] = "platform"
    db: PoolSettings = PoolSettings()
    agents: Endpoint | None = None        # None: this install does not run that service
    tools: Endpoint | None = None
    kb: Endpoint | None = None
    platform_internal: Endpoint | None = None
    page_size_default: int = 20
    page_size_max: int = 50

    def require(self, *names: str) -> None:
        """First call in every __main__: exits naming each endpoint that is unset, before anything opens."""

# packages/ops_identity/src/ops_identity/client.py
class ServiceClient:
    @classmethod
    def for_settings(cls, settings: Settings, *, service: str, audience: str, scopes: Sequence[str] = ()) -> ServiceClient:
        """Owns its httpx.AsyncClient with the endpoint's timeout and retries. No other code builds one."""
```

Sixteen files set `auth_mode` today (compose, the Fly files, the staging toml files, the k8s settings, the stack
script), so the deployed stacks do not change when the default flips. The component lists each one and proves `make
verify` green with the new default before it merges.

### C4: one relay, one loop test

```python
# packages/ops_store/src/ops_store/outbox.py
class Poster(Protocol):
    async def post(self, path: str, body: Any, *, tenant: str, team: str) -> Any: ...

Routes = Mapping[str, tuple[str, ...]]      # event name (or "*") -> the services that hear it

def relay(engine, table, *, routes: Routes, targets: Mapping[str, Poster], role: str | None,
          path: str = "/v1/events", team_in_token: frozenset[str] = frozenset(), enrich=None) -> Relay: ...
async def run_relay(r: Relay, *, key: str, stop: asyncio.Event, store: Heartbeats = background.LOCAL) -> None: ...

# packages/ops_store/src/ops_store/background.py
def retention(table: sa.Table, at: sa.Column[float], keep_s: float, *, key: str, service: str) -> Process: ...

# packages/ops_store/src/ops_store/testing.py
async def loop_reports_failure(client: AsyncClient, key: str, trip: Callable[[], None]) -> None:
    """Makes one pass raise, waits one interval, asserts /health/background shows the key with last_error set."""
```

### C5: a model at every boundary

`In` is not `strict`: FastAPI validates the parsed JSON in Python mode, where strict refuses an ISO date string, an
enum's value and a UUID string. `Out` does have `extra="forbid"`: its schema says `additionalProperties: false`, and a
row with a column the model lacks fails in `ops_store.rows`. Dropping it changed every API document.

```python
# packages/ops_service_kit/src/ops_service_kit/http.py
class In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

class Out(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True, from_attributes=True
    )

class Passthrough(In):
    """A body forwarded whole to an outside system: the one reviewed exception to extra="forbid"."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

# packages/ops_store/src/ops_store/rows.py
async def rows(conn: AsyncConnection, stmt: sa.Select[Any], model: type[M]) -> list[M]:
    """The only way a row leaves a store: the mapping validated through TypeAdapter(list[model]). A column the model
    does not name is an error, so the statement and the model cannot drift apart."""
async def one(conn: AsyncConnection, stmt: sa.Select[Any], model: type[M]) -> M | None: ...

# packages/ops_store/src/ops_store/outbox.py
class Event(Out):
    name: str
    tenant_id: TeamId
    team_id: TeamId | None
    revision: int
    payload: Step | ToolPublished | KbChanged      # discriminated on the event's kind

# packages/ops_store/src/ops_store/background.py
async def start(coro: Coroutine[Any, Any, None], *, key: str) -> None:
    """A task that outlives the request: on the lifespan's TaskGroup, cancelled at shutdown, its failure on
    /health/background under key. Its own asyncio task, so its own transaction."""

# a request that fans out, after
async with asyncio.TaskGroup() as tg:
    cards = tg.create_task(copies.app_cards(rt, team))
    health = tg.create_task(client.get("/health"))

# pyproject.toml
# [tool.ruff.lint] select gains "S608" and "ASYNC"; [tool.pyright] reportDeprecated = "error"
```

A frozen dataclass stays the right tool for a value that lives inside one layer; a dataclass that reaches a route or
an outbox becomes a model.

### C6: one list of checks

```makefile
# make/checks.mk: ci.yml's checks job and make verify both run `make checks`; pre-commit runs `make checks STAGED=1`.
# A check is a name in CHECKS with its command (check-run.<name>) and the staged paths that can change it
# (check-paths.<name>); `make checks-list` prints each name with its command.
CHECKS = \
  access-exceptions access-exceptions-commits access-exceptions-self-test \
  portable-store portable-store-commits config-literals config-literals-commits typed-boundaries \
  isolation-markings isolation-sites store-inventory roles-matrix sbom k8s-base \
  lint-imports sdk-drift changelog-entries console-standards
```

```yaml
# .github/workflows/ci.yml
staging:        if: ${{ !cancelled() && github.ref == 'refs/heads/develop' && needs.ci-ok.result == 'success' }}
store-mssql:    # every pull request: the store, kit and identity suites against a SQL Server container, required by ci-ok
release-proof:  # pull requests into main: make db-scripts-proof FROM=<last tag>; make install-proof
```

Also in C6: the api-layer use-case harness takes a base URL (`OPS_USECASE_BASE_URL`) so the same scripts can run
against a deployed stack instead of starting one; unset, they start their own services on free ports. This is what lets
"green on staging" be the use cases rather than the console walk alone.

### C7: every decision through `can()`

`scripts/check_access_exceptions.py` exits 1 on an allowlist line whose register row reads "no decision" (two today);
`is_admin`, `role in (...)` and owner compares become shapes with a ceiling of zero; the role-name kind gets a
shrink-only baseline file per lane; `--self-test` plants one of each shape and expects exit 1. Each of the 78 lines on
`access-exceptions-allowlist.txt` gains its outcome and lane as a comment: 60 kept with a reason, 16 converted onto
`can()` or `policy()`, 2 deleted with their code. `policy(p, key)` in `packages/ops_access/src/ops_access/policies.py`
becomes the one reader of a policy value. The two undecided register rows are decided on the page the register lives
on: team roles are no longer mapped to a three-valued session role in the console, and the Chat user role is given like
any other role, through an invite or a role change.

### C8: a copy, kept by events

```python
# packages/ops_store/src/ops_store/copies.py
def copy_table(metadata: sa.MetaData, name: str, *columns: sa.Column, marking: Marking = TENANT_SCOPED) -> sa.Table:
    """A local copy of another service's records: the owner's id, its revision, and the columns a screen lists or
    filters on. Policed like any tenant table. Never the source of truth for a decision."""
async def apply(conn: AsyncConnection, table: sa.Table, event: Event) -> None:
    """Upsert or delete by id and revision; an older revision is ignored, so a replayed event is harmless."""
def resync(table: sa.Table, source: Callable[[], Awaitable[list[Out]]], *, key: str, every_s: float) -> Process:
    """Reads the owner's full list at start and every every_s and reconciles the copy."""

# agents-service, after
@router.get("/v1/tools", response_model=Envelope[ListResult[ToolOut]])
async def list_tools(p: CurrentPrincipal, _: Tx, q: ListQuery, rt: Rt) -> JSONResponse:
    return ok(await tools.list(rt, q))   # list_page over tool_catalog joined to tool_team_state and tool_uses
```

The tool catalogue is the first copy (`tool_catalog`, `tool_team_state` in agents-service's registry chain, fed by
`tool.module.published`, `tool.module.changed` and `tool.team_state.changed` from tools-service's outbox); knowledge-base
labels are the second (`kb_labels`, fed by `kb.changed`). Agents-service already receives both services' events on
`POST /v1/events`, so no new transport is added.

## Step order

| Track | Builder | Order | Waits on |
|---|---|---|---|
| A | store builder | C1, then C2 | nothing; the longest track, 5 to 6.5 days |
| B | service and CI builder | C3, then C5, then C6 | C6 waits for the check files of C1, C2, C4 and C7 to exist, since it lists them; it lands last of the components and before the pilot opens its pull request |
| C | events and access builder | C4, then C7, then C8 | C8 waits on C1, C2 and C4; it runs beside the pilot and lands before the agents lane opens |

Inside a component: write the check first and watch it fail at today's count (`TS3`, `DL9`); build the interface;
add the component's own tests, one per failure mode (C1 has six: re-entry, widening on one connection, savepoint then
read, stream closed before the first frame, gather and child task, pool wait under 50 concurrent GETs); prove the
check green; open the pull request.

## Commands

| Step | Command |
|---|---|
| Package tests on a throwaway database | `make -s test PKG=packages/ops_store`, `make -s test PKG=packages/ops_service_kit`, `make -s test PKG=packages/ops_identity`, `make -s test PKG=packages/ops_access` |
| The isolation markings and the new index test | `uv run pytest -q deploy/database/tests` |
| The ratchets, before and after | `make checks` (the list in `make/checks.mk`; `make checks-list` prints each command) |
| The gate | `make verify` |
| C6's own proof | A script test that the plan for a one-file service change runs every line of `CHECKS`; `make stg-deploy` from a develop merge once the staging job is fixed |
| Both SDKs still match the documents | `make sdk-verify` |

## Acceptance

| Component | Green when |
|---|---|
| C1 | `test_isolation_sites.py` fails on a new `engine.begin(` or `engine.connect(` under `services/*/src` outside a per-service list starting at 197, and on a caught database error with no savepoint outside a list starting at 28; the six tests pass on both databases; the request line carries `db.tx_count`, `db.tx_open_ms` and the pool numbers; pool settings are read from `OPS_DB__*` |
| C2 | `check_portable_store.py` fails on a list slice in `api/` or `app/` (red at 10 today); `test_indexes.py` fails on an unindexed foreign key or filter column outside a waiting list starting at the 17 known; the console's `check-standards.mjs` gains three rules: `pageSize` above 50 outside `options-queries.ts`, `.reduce(` or `.filter(...).length` in components and app, `fetch(` outside `lib/api` |
| C3 | `check_config_literals.py` is at zero for loopback fallbacks and on per-service baselines starting at 58 and 47 for timeouts and clients; the import-linter contract allows `httpx` only in tools-service, models-service, `ops_identity.client` and the listed client packages; one boot test per service that an unset required endpoint exits naming it; `make verify` green with `auth_mode` defaulting to `platform` |
| C4 | A test that `Relay(` is constructed only in `ops_store.outbox` (red at 5 today); a test that every key on `PROCESSES` has a `loop_reports_failure` test |
| C5 | `check_typed_boundaries.py --strict` with a baseline file per service: `dict[str, Any]` per layer starting at 4,308; dict-returning store functions at 194; bare tasks at 13 and 32; `logging.getLogger(` and `print(` outside the kit at zero; the contract walk asserts every body is an `In` and every reply an `Out`; ruff `S608` and `ASYNC` and pyright `reportDeprecated` on |
| C6 | The checks job runs `make checks`; the staging job's `if:` carries `!cancelled()`; `store-mssql` and `release-proof` exist with the right triggers; no production deploy workflow exists until the owner's set-up (`docs/deploy/fly-staging.md`); `ops_service_kit.standards.check(app, settings_module=...)` replaces rules 4 to 6 of `services/agents-service/scripts/check_standards.py`; the api harness accepts `OPS_USECASE_BASE_URL` |
| C7 | The checker exits 1 on a "no decision" row and on each planted shape; the allowlist carries an outcome per line; the two register rows are decided; a per-lane baseline file exists for role names |
| C8 | A published module appears in the copy after one relay pass and in `/v1/tools` with its facets; `resync` repairs a deleted copy row; the budget fixture's row for `/v1/tools` is one transaction and no hop; both SDKs regenerated on `develop` afterwards |

## Branches and pull requests

Every component and every service lands on the single branch `refactor/services-onto-shared-components`, in one pull
request, in this order: the components, the small services (documents, files, models, runner), platform, kb, tools,
agents, console. Each component is one or more commits on that branch, committed by path.

Commit subject at most 72 characters, body at most three lines: what was wrong and what ran to prove the fix. A
reviewer who did not write the component approves it against this page and the standards before merge.

## What not to touch

- Any `services/<x>/src/<pkg>/store/` file, except the one adopter a component's test needs (C1 may convert one small
  store in models-service to prove the base; the pilot takes the rest).
- Any console page or component; C2 touches `contract.ts`, `options-queries.ts` and `check-standards.mjs` only.
- The generated SDK layer; `sdk/generate.py --check` must stay green, and regeneration happens on `develop` after a merge.
- The owner's items: the staging GitHub environment's secrets, a production environment with required reviewers, branch
  protection on `develop` requiring one review and the scan workflows. C6 lists them; it does not need them to merge.
