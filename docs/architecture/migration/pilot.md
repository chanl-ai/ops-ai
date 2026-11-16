# Phase 1: the pilot on the four small services

Status: current, 2026-11-15. documents-service, files-service, models-service and runner-service move onto every
component in one pull request before any other lane opens. The pilot proves the components on real services, sets the
pattern the four lanes copy, and measures the one risk this plan cannot count from the code: behaviour that no use
case or test covers, which a wholesale rewrite can break without a red check.

## Inputs

| Input | Where |
|---|---|
| The components, merged on `develop` | [components.md](components.md); C8 may still be open, the pilot does not need it |
| The four services today | `services/documents-service/src/ops_documents/` (store 7 files, 1,714 lines), `services/files-service/src/ops_files/` (store 5 files, 1,060 lines), `services/models-service/src/ops_models/` (store 7 files, 588 lines), `services/runner-service/src/ops_runner/` (no store) |
| Their use cases | documents `uc-243 uc-250 uc-672`; files `uc-093 uc-094 uc-331 uc-629`; models `uc-060 uc-532 uc-605 uc-720`; runner none. Eleven in all, over 35 GET routes and their writes |
| Their unit tests | `services/documents-service/tests` 18 files, `services/files-service/tests` 22, `services/models-service/tests` 16, `services/runner-service/tests` 4 |
| The sites, counted on `develop` | 80 `isolated_tx` and 2 raw engine sites; 7 caught database errors that carry on (documents `store/extractions.py`, `store/readings.py` three times; files `store/files.py` twice, `store/read_requests.py`); 2 streaming routes (files `app.py`, models `app.py`); 2 gather paths (documents `app.py`, files `app.py`); 11 clients and 11 literal timeouts in the services plus 2 and 2 in `packages/ops_documents_client` and `packages/ops_files_client`; 3 loopback fallbacks; two relay wirings, one with `enrich`; 33 store functions returning a dict (documents 18, models 12, files 3); 5 gather and 5 `create_task` sites; 6 access lines on the allowlist, all kept with their reason; models' 2 tables with no row policy; runner's 2 `time.sleep` calls in `wasm.py` |

## Why these four

They touch every component and every hard case (savepoints, streams, fan-out, a forwarded body, a relay with
`enrich`, unpoliced tables) with the smallest blast radius, and they share no store file with the two large lanes.
Their use-case coverage is thin (eleven use cases over four services; runner has none), which is why the pilot is where
the coverage gap is measured rather than assumed.

## What is replaced and what is kept

| Service | Replaced | Kept |
|---|---|---|
| documents | `store/document_types.py`, `store/extractions.py`, `store/metadata.py`, `store/readings.py`, `store/template_copies.py` rewritten onto `Store`, `rows()` and `attempt()`; `store/event_relay.py` deleted for `relay()`; route plumbing in `app.py`, `document_types.py`, `readings.py`, `templates.py` (signatures, bodies, replies, the gather path); `agents_client.py` and `tools_client.py` replaced by `ServiceClient.for_settings` | `extraction.py` (1,156 lines of extraction logic), `models.py` shapes that become `Out` models, `errors.py`, `files.py` |
| files | `store/files.py`, `store/read_requests.py`, `store/settings.py` onto the base; `store/event_relay.py` deleted (`enrich` passed to `relay()`); route plumbing in `app.py` and `tenant_files.py`, the streaming route onto `Tx`, the gather path onto `TaskGroup`; `settings.py` onto `Endpoint` fields | `service.py`, `scanning.py`, `sniffing.py`, `retention.py` (becomes a registered `retention()` process), `secrets.py` |
| models | `store/aliases.py`, `store/calls.py`, `store/keys.py`, `store/provider_keys.py`, `store/providers.py` onto the base; `store/tables.py` gains the two markings; route plumbing in `app.py`, the streaming route onto `Tx`, the forwarded provider body onto `Passthrough`; `schemas.py` bodies onto `In`, replies onto `Out` | `providers.py`, `key_check.py`, `connection_settings.py`, `seed.py` |
| runner | `wasm.py` two `time.sleep` calls onto `await asyncio.sleep` or a thread; its client and timeout onto `ServiceClient.for_settings`; a budgets row for its one GET | `domain.py`, `guest.py`, `fetch.py`, the wasm execution itself |
| `packages/ops_documents_client`, `packages/ops_files_client` | Their `httpx.AsyncClient` and timeouts onto `ServiceClient.for_settings`; their loopback fallbacks deleted | Their method surface |

## Target shapes

```python
# services/models-service/src/ops_models/store/aliases.py, after
class AliasOut(Out):
    id: str
    team_id: TeamId
    name: str
    provider: str
    model: str
    revision: int

class Aliases(Store):
    role = ROLE

    async def list(self, conn: AsyncConnection, team: str) -> list[AliasOut]:
        return await rows(conn, sa.select(*ALIAS_COLUMNS).where(aliases.c.team_id == team), AliasOut)

    async def claim_name(self, conn: AsyncConnection, team: str, name: str) -> bool:
        try:
            async with self.attempt(conn):
                await conn.execute(sa.insert(aliases).values(team_id=team, name=name))
        except IntegrityError:
            return False
        return True

# services/models-service/src/ops_models/app.py, after
@router.get("/v1/model-aliases", response_model=Envelope[ListResult[AliasOut]])
async def list_aliases(p: CurrentPrincipal, _: Tx, q: ListQuery, st: Stores) -> JSONResponse:
    async with st.aliases.tx() as conn:                       # re-enters the request transaction
        return ok(await list_page(conn, aliases_select(p.team), q, default_sort=aliases.c.name, search=[aliases.c.name]))

@router.post("/v1/model-calls", response_model=Envelope[CallOut])
async def call(p: CurrentPrincipal, _: Tx, body: ProviderRequest, st: Stores) -> StreamingResponse:
    call = await st.calls.start(p, body)                     # on the request transaction, which closes on return
    return StreamingResponse(frames(st, call.id))             # frames open their own transactions

class ProviderRequest(Passthrough): ...                      # forwarded whole to the provider: the reviewed exception

# services/files-service/src/ops_files/__main__.py, after
settings = Settings()
settings.require("platform_internal", "agents")
run_relay(relay(engine, outbox, routes={"*": ("agents",), "file.read_requested": ("agents", "platform")},
                targets=clients, role=SYSTEM_ROLE, enrich=add_read_request), key="files.relay", stop=stop)
```

## Step order

1. Inventory before touching anything. For each service, list every route (from its OpenAPI document) and every
   store function, and mark which ones a use case or a unit test reaches. Write the four counts into
   `coverage-before` in this page's results section when the pilot closes. For every uncovered route a console screen
   calls, write one api-layer test through the real app first (`TS1`, `TS3`); watch it pass on `develop`, so it is a
   characterisation test of today's behaviour.
2. Store layer, one service at a time, smallest first (models, files, documents): every class extends `Store` and sets
   `role`; every `isolated_tx(self.engine)` and raw engine call becomes `self.tx()` or takes `conn`; every function
   that returned a dict names its columns and returns an `Out` through `rows()` or `one()`; every caught database error
   runs inside `attempt()`; models' two tables are marked and their migration emits the policy DDL for both databases
   with a backfill-free down path.
3. Request layer, same order: every route takes `Tx`; list routes take `ListQuery` and call `list_page`; bodies extend
   `In` (models' provider body `Passthrough`), replies `Out`; the two streaming routes and the two gather paths take
   the shapes above; `create_task` sites become `background.start()` or a `TaskGroup` child.
4. Clients, settings and relay: `__main__` calls `settings.require(...)`; every `httpx.AsyncClient` to another service
   becomes `ServiceClient.for_settings`; the three loopback fallbacks and eleven literal timeouts go; both
   `event_relay.py` files are deleted and the lifespans call `run_relay(relay(...))`; files' retention becomes
   `retention()`; runner's two sleeps become `await asyncio.sleep`.
5. Budgets and loop tests: a `budgets.toml` row per GET route (35) with the two streaming routes and the two fan-out
   routes carrying their transaction allowance; one `loop_reports_failure` test per relay and sweep.
6. Shrink the baselines: each service's rows in the raw-site, savepoint, config-literal, typed-boundary and portable
   files go to zero; the six access lines keep their reason comments.
7. Measure after: run the service tests, the eleven use cases, `make verify`, then deploy the merge to staging, run the
   console walk, and open every screen the four services feed by hand (document types, extractions, files, model
   aliases, provider keys, a run that uses the runner). Every defect found that no test or use case caught is one
   gap. Write the counts into this page's results section.

## Commands

| Step | Command |
|---|---|
| Route and store inventory | `uv run python scripts/store_inventory.py --check`; each service's `check_openapi.py` under its folder; `make usecase-coverage SERVICE=documents-service` (and files, models) |
| Tests per service, both databases | `make -s test PKG=services/models-service`, `make -s test PKG=services/files-service`, `make -s test PKG=services/documents-service`, `make -s test PKG=services/runner-service`; the SQL Server run through the `store-mssql` job C6 adds, or `make uc-sql-server` by hand |
| The eleven use cases, in parallel | `make usecase-batch UCS="uc-243 uc-250 uc-672 uc-093 uc-094 uc-331 uc-629 uc-060 uc-532 uc-605 uc-720"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| The ratchets | `uv run python scripts/check_portable_store.py --strict`; `uv run python scripts/check_access_exceptions.py`; `uv run lint-imports --no-logo`; `uv run pytest -q deploy/database/tests`; `uv run python scripts/check_config_literals.py --strict` and `uv run python scripts/check_typed_boundaries.py --strict` (added by C3 and C5) |
| The gate | `make verify` |
| Regenerate the SDKs, on `develop`, after the merge | `make sdk`, then `make sdk-verify` |
| Staging | `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| Raw sites and savepoints | The four services' rows in the raw-site and savepoint lists are zero; the 7 caught errors run inside `attempt()` |
| Markings | models' two tables are off the `WAITING` list in `deploy/database/tests/test_isolation_markings.py`; the migration downgrades on both databases |
| Lists | No list slice under the four services' `api/` or `app` modules; files' pickers answer `ids=` |
| Clients and settings | Zero loopback fallbacks; zero literal timeouts; zero `httpx.AsyncClient` outside the listed clients; each `__main__` exits naming an unset required endpoint |
| Relay and loops | Both `event_relay.py` files gone; every key on `PROCESSES` has a `loop_reports_failure` test |
| Relay and loop baselines | `packages/ops_store/tests/relay_sites/documents-service.txt` and `files-service.txt` deleted; `packages/ops_store/tests/loop_health/documents.txt` and `files.txt` emptied (`document_reading`, `documents_relay`, `files_relay`, `files_retention`) |
| Typed boundaries | 33 store functions return models; `Passthrough` on the one forwarded body; zero `gather` and `create_task` outside `ops_store.background`; runner's sleeps gone |
| Budgets | The budget fixture is green for all 35 GET routes at 5 and 50 rows on both databases, with the streaming and fan-out routes listed |
| Behaviour | Service tests, the eleven use cases and `make verify` green on the merge commit; staging deployed with every process up and the console walk green; the screens opened by hand |
| Published numbers | This page's results section holds: statements and transactions per route at 5 and 50 rows on both databases; pool wait under 50 concurrent GETs; the longest transaction open time; builder hours per store line and per route; `coverage-before` and the defects no test caught |

## Results

Status: current, measured at the branch head on 2026-11-15, before the staging deploy and the by-hand screen walk of
step 7, which have not run. Every figure comes from a git command, a committed test or a committed budget file; a cell
reading "not measured" says what would measure it. The four lanes read this section before they size their own work.

### Counts before and after

"Before" is the first committed version of each baseline file, found with `git log --diff-filter=A -- <file>`, and
"after" is the file at the branch head. Typed-boundaries totals are the sum of the count column over all rows of the
baseline file, which equals the figure in each file's header line. A cell reading "none" means the file does not exist
for that service.

| Measure | documents | files | models | runner |
|---|---|---|---|---|
| Routes in the service at the branch head | 33 | 27 | 21 | 2 |
| Characterisation tests added in "pin" commits | 5 | 1 | 3 | 5 |
| Isolation sites: raw | 1 -> 0 | 1 -> 0 | 25 -> 0 | none |
| Isolation sites: caught | 5 -> 0 | 4 -> 0 | 0 -> 0 | none |
| Isolation sites: broad | not counted -> 0 | not counted -> 0 | not counted -> 0 | none |
| Isolation sites: install | not counted -> 0 | not counted -> 0 | not counted -> 23 | none |
| Typed boundaries, total | 346 -> 289 | 64 -> 58 | 97 -> 69 | 25 -> 25 |
| Config literals: timeouts | 7 -> 3 | 1 -> 0 | 2 -> 2 | 1 -> 2 |
| Config literals: clients | 7 -> 3 | 1 -> 0 | 2 -> 2 | 1 -> 0 |
| Relay sites | 1 -> 0 | 1 -> 0 | none | none |
| Loop-health rows | 2 -> 0 | 2 -> 0 | none | none |
| Routes on the request transaction (`Tx` parameter) | 16 of 33 | 16 of 27 | 16 of 21 | 0 of 2 |
| Statement budget file (`budgets.toml`), GET rows | 16 | 10 | 8 | none |
| Tests passing, as stated in the last commit body that gives a count | 163 | 129 | 130 (PostgreSQL) | not recorded |

- The broad and install columns were added to the isolation check after the baselines were first committed, so "not
  counted" means no figure existed before.
- Models' 23 install-scope sites touch five tables and none of them is the call log: `model_aliases` (5 sites),
  `model_keys` (9), `provider_connections` (7) and `model_key_spend` (2, one of which also inserts into
  `model_call_refusals`, the calls that name no tenant). Each table is marked install-wide in `store/tables.py`. The
  call log (`model_call_log`) holds tenants' runs and costs; since `f24a1143` it is read and written on tenant
  transactions, and a key's caps read `model_key_spend` instead. The 23 sites match
  `packages/ops_store/tests/isolation_sites/models-service.txt` (aliases 5, calls 2, keys 9, providers 7).
- Runner's timeouts rise from 1 to 2 while its clients fall from 1 to 0: the check was widened to count a timeout
  given by position, so the second timeout existed before and was not counted. The two literal timeouts remain in
  `fetch.py` and `wasm.py`.
- Typed boundaries for runner stay at 25 in total: one `dict-any` row became a `reply` row (the run route), so the
  total did not change.
- Runner has no store and no database, so it has no isolation, relay or loop-health baseline and no budget file.
- Route counts are the decorated routes in each service's `app.py` (and documents' `templates.py`), plus models'
  chat completions and embeddings, which are registered by a call (`app.post(...)(completions)`) and carry no
  decorator. Fourteen "pin" tests were added across the four services: they assert today's replies and body names, and
  some landed after that service's store move rather than before it.
- The three budget files hold 34 GET rows. The plan counted 35 GET routes; the 35th is runner's health route, which
  has no budget file.

### Hours per store line and per route

The spans are wall-clock time between commits. Several builders worked at once, and a span includes waiting for other
builders' shared commits, CI and review, so none of these is the hours of one person's work. A span starts at the
first commit whose subject names the service, so it leaves out the work inside that first commit. Times are local
commit times on 2026-11-15. Store lines are `git diff --numstat <first naming commit>^..HEAD` over each service's
`store` directory, added plus removed. The branch also carries the shared components and their checks, which are in no
service's span; its first commit is at 17:50.

| Service | First naming commit | Last commit | Span | Store lines changed (added, removed, files) | Hours per 1,000 store lines | Routes | Hours per 10 routes |
|---|---|---|---|---|---|---|---|
| models | 19:46 | 22:00 | 2 h 14 min | 551 (409, 142, 5) | 4.1 | 21 | 1.1 |
| documents | 21:01 | 23:13 | 2 h 12 min | 952 (465, 487, 9) | 2.3 | 33 | 0.7 |
| files | 21:10 | 22:04 | 0 h 54 min | 629 (331, 298, 5) | 1.4 | 27 | 0.3 |
| runner | 22:13 | 22:30 | 0 h 17 min | no store | not applicable | 2 | 1.4 |

Reading the rates:

- Models went first and built the install-wide scope, the table guard and the typed bodies for the OpenAI-shaped
  replies inside its span, so its rate carries work the other three reused. Read the files and documents rows as the
  rate for a service that copies the pattern, and the models row as the rate for the first one.
- Runner's rate per 10 routes divides 17 minutes by two routes and is not a basis for sizing a service with a store.
- Hours for the budgets file are not measured separately. The commits that added each file landed at 21:16 (models),
  22:01 (files) and 22:44 (documents), and no start time was recorded.

### Transactions per route

"Before" figures come from a count a commit body states as seen on the old code, in a test that failed there. Where no
before figure is stated, the cell says so rather than estimating. "After" figures are held by a committed test or by a
`budgets.toml` row.

| Service | Route | Before | After | Held by |
|---|---|---|---|---|
| models | chat completion, stream, embedding | 4 transactions for the gate alone | 2: one gate, one settle; none open at the provider call or at a stream frame | `test_request_transactions.py`, `budgets.toml` |
| models | each GET | not stated | 1 transaction on 1 connection, 0 to 3 statements at 5 and 50 rows | `test_statement_budget.py` |
| documents | type reads (list, get, versions) | 1 to 6 | 1 | `test_request_transactions.py` |
| documents | create a type | 4 | 1 | `test_request_transactions.py` |
| documents | add a sample | 3 | 2 | `test_request_transactions.py` |
| documents | list examples; template offers | 2; 4 | 1; 1 | `test_request_transactions.py` |
| documents | typed extraction | 10 | 7 | `test_extract_transactions.py` |
| documents | template suggestion over two reads | 8 | 5 | `test_request_transactions.py` |
| documents | delete a type; reading or layout read now | not stated | 2; 2 (a stored one is 1) | `test_request_transactions.py` |
| files | each route on `Tx` | one per store call, count not stated | 1 | `budgets.toml` |
| files | read-request GET | 2 transactions and 2 connection checkouts with the route off `Tx` | 1 and 1 | `test_statement_budget.py` |
| files | download content | not stated | rows in 1 transaction, closed before the first byte; 0 open at every chunk read | `test_request_transactions.py` |
| runner | both routes | no database | no database | not applicable |

Statements per GET at 5 and 50 rows, from the budget files: documents 0 to 12 (template offers is the 12, over 2
transactions), files 0 to 13 (the file list is the 13), models 0 to 3. All three files were measured on PostgreSQL.

### Defects no test caught

Seventeen defects on this branch were not caught by a test that existed when they were written. The basis is each
fix's commit body: the new test was red on the old code, which means the suite that ran before it was green. Fixes to
the standards checks and hooks themselves, flaky tests and CI environment setup are not counted. The commit bodies do
not always say who found the defect, so the "found by" column says "not stated" where they do not.

| Commit | Cause in one line | Found by |
|---|---|---|
| `5898f44e` | The install-scope guard judged `count(*)` as a column and refused it, so every models completion failed | not stated |
| `2491d7ef` | The use-case stack started files-service with no agents address, which it now requires | use case (uc-672 failed) |
| `fb22c97a` | A worker a use case started took the shared stack's platform address, so acting-for calls failed | use case (passed before the components, failed after) |
| `6fdbf335` | A worker started outside the harness helper ran with sign-in on beside an API with dev auth | not stated |
| `e72a5ce1` | `make run` started services without the addresses they now require, so they exited at boot | not stated |
| `efc2d5d2` | A request answered after a swallowed database error, keeping lost or half-kept writes | not stated |
| `fa547000` | An install-scope block read every tenant's rows of a table with no row policy | not stated |
| `f24a1143` | The model call log was marked install-wide though it holds tenants' runs and costs | not stated |
| `ff8f54be` | A statement cancelled mid-flight made the rollback raise a second error in its place | not stated |
| `c3e6a401` | A failed `BEGIN` on a request left its connection checked out | not stated |
| `7a69c38c` | A late older event rewrote a deleted copy row, and a resync held a transaction across the owner call | not stated |
| `727d2c13` | A delete in a second table left a live row beside its tombstone, and an equal-revision edit was never repaired | not stated |
| `a53b62af` | A row raced by an event kept the older revision until the next resync pass | not stated |
| `548603f0` | A type error in a new documents test failed `make typecheck` | type check |
| `a6fa1e31` | A partly unknown type in the isolation-scan test failed `pyright packages` | type check |
| `165c66e5` | Partly unknown names in the openapi gate test's helper failed `pyright packages` | type check |
| `dc281681` | The store tests could not import the baseline history helper, so CI's type check failed | type check |

By finder: 2 by a use case, 4 by the type check, 11 not stated. By place: 4 in the use-case stack and `make run`, 6 in
the store scope and request transaction, 3 in the local-copy resync, 4 type errors in new tests.

Defects found on staging or by hand are not measured: the staging deploy and the screen walk have not run.

### Routes not on the request transaction

A route takes `Tx` when it reads or writes only rows, or asks another service before its first row. Every other route
falls into one of four groups, and a later service copies the group rather than the count:

| Group | Rule |
|---|---|
| Read, call, then settle | A route that reads a row and then asks another service, a model or a provider opens a gate transaction, closes it, makes the call with none open, then opens a settle transaction. Holding one transaction across the call holds a pooled connection for as long as the other party takes. |
| Moves bytes or streams | A route that reads or writes object bytes closes its rows' transaction before the first byte moves. |
| Row committed before a task | A route that saves a row a background task then reads commits the row before the task starts, so the task finds it. |
| No database | Health routes with no request transaction, and a service with no database. |

Documents, 17 of 33 routes not on `Tx` (the reasoning is in the comment above `docs` in `app.py`):

| Group | Routes | Reason |
|---|---|---|
| No database transaction | `GET /health`, `GET /health/background` | The probe is owned by `ops_store`; background state is read from process heartbeats |
| Read, call, settle | `POST /extractions`, `/classifications`, `/readings`, `/layout` | Each reads the file from files-service or asks the model between rows |
| Read, call, settle | `POST /document-types`, `DELETE /document-types/{id}`, `POST .../samples`, `DELETE .../samples/{id}` | The type commits before a sample asks files-service; agents-service is asked which workflows read a type before the delete; files-service keeps or releases the sample's file |
| Read, call, settle | `POST .../templates/suggest`, `GET .../template-offers`, `GET .../examples`, `GET .../test-estimate` | Layouts are read from files-service, platform-service says whether the team masks examples, models-service prices the estimate |
| Read, call, settle | `GET /v1/templates` | The team's copies are read, then tools-service is asked for the team's templates |
| Moves bytes | `GET .../readings/{id}/pages/{n}/image` | Reads the file's bytes from files-service and draws a page; reads no row |
| Row committed before a task | `POST .../test-runs` | The run's row commits before the task that runs it starts |

Files, 11 of 27 routes not on `Tx`:

| Group | Routes | Reason |
|---|---|---|
| No database transaction | `GET /health`, `GET /health/background` | As in documents |
| Moves bytes | `PUT /uploads/{id}/content`, `POST /uploads/{id}/complete`, `POST /v1/files` | The body streams into storage; completing reads the stored bytes to check size, signature and hash |
| Moves bytes, streams | `GET /{id}/content` | The rows are read in one transaction closed before the first byte leaves storage; the test reads 0 open at every chunk |
| Read, call, settle | `DELETE /{id}`, `POST /bulk-delete`, `POST /legal-hold` | Each changes the stored object or its storage-level hold between row changes |
| Read, call, settle | `PUT /settings/storage`, `POST /settings/storage/test` | Each writes, reads and deletes a small object on the target before anything is saved |

Models, 5 of 21 routes not on `Tx`:

| Group | Routes | Reason |
|---|---|---|
| No database transaction | `GET /health` | As in documents |
| Read, call, settle; streams | `POST /v1/models/chat/completions`, `POST /v1/models/embeddings` | One gate, the provider call with none open, one settle; stream frames go out with none open. They are registered by a call, so they carry no `Tx` parameter |
| Read, call, settle | `POST /v1/provider-keys/{name}/check`, `GET /v1/provider-keys/{name}/models` | The saved key is read in a transaction closed before the provider is asked what it reaches |

Runner, 2 of 2 routes not on `Tx`: `GET /health` and `POST /v1/runs` have no database. The run route runs the guest and
calls tools-service.

### Not measured

| Measure | Status | What would measure it |
|---|---|---|
| Routes and store functions reached by a use case or test (`coverage-before`) | not measured on `develop` before the rewrite | `make usecase-coverage SERVICE=<service>` and `uv run python scripts/store_inventory.py --check` on `origin/develop` |
| Statements and transactions per route on SQL Server | not measured: every budget row was measured on PostgreSQL, and the `store-mssql` job runs the store, kit and identity suites and a few store and isolation test files of models, documents and files, not their budget tests | Run each service's `tests/test_statement_budget.py` with `OPS_MSSQL_SERVER` and `MSSQL_SA_PASSWORD` set; the service conftest then installs the golden schema |
| Pool wait under 50 concurrent GETs | not measured: no load run exists; the request line carries `db.pool.wait_ms`, `db.pool.in_use` and `db.pool.limit` | 50 concurrent GETs against one running service, reading `db.pool.wait_ms` from its `http.request` lines |
| Longest `db.tx_open_ms` | not measured: committed tests assert that it is positive and that no transaction is open at an outside call, and record no maximum | The same load run, taking the maximum of `db.tx_open_ms` |
| Hours for the budgets file | not measured separately | A recorded start time for the budgets commit |
| Defects found on staging or by hand | not measured: step 7 has not run | `make stg-deploy REF=<merge commit>`, `make stg-health`, then open each screen the four services feed |

## What the pilot found

The shared components needed these changes before the services could move onto them:

- Install-wide scope with a table guard: a store method for tables that hold no tenant, refused on any table not
  marked install-wide, with the count of such blocks held in a falling baseline.
- Bases for bodies and replies that keep an outside wire format, needed for the OpenAI-shaped replies models returns.
- One database probe for `/health`, owned by `ops_store` instead of each service.
- A store method for cross-tenant reads that runs as the store's system role, used by documents' restart reads.
- Custom loop passes: a listed process can have its own pass for the sweep runner.
- Type checking of the packages and each service on the one list of checks.

These stay unconverted because converting them would change an API document:

- Replies with untyped fields: `reply` and `dict-any` rows remain in all four typed-boundaries baselines.
- List routes on the shared list contract: no route in documents, files or models calls `list_page` or takes `ListQuery`.
- Health replies: `health_health` remains a `reply` row in documents, files and models.

## Branch and pull request

Branch `refactor/pilot-services-on-shared-layers` from `origin/develop`, one pull request into `develop`. Commit
subject at most 72 characters, body at most three lines. A reviewer who did not write it approves against this page,
[components.md](components.md) and the standards. Merge order: the pilot merges before any lane opens its pull
request.

## What not to touch

- `services/documents-service/src/ops_documents/extraction.py`, `services/files-service/src/ops_files/service.py`,
  `services/models-service/src/ops_models/providers.py`, runner's guest and wasm execution: domain logic, retyped
  inputs only.
- Any other service's files. The six access lines stay as they are with their reason.
- The console. Its data layer moves in [lane-console.md](lane-console.md).
- The generated SDK layer inside the pull request; regeneration happens on `develop` after the merge.
