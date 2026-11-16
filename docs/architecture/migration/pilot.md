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

Filled in when the pilot closes. The four lanes read these before they size their own work.

| Measure | Value |
|---|---|
| Routes, store functions; of which reached by a use case or test (`coverage-before`) | |
| Characterisation tests added before the rewrite | |
| Defects found on staging or by hand that no test or use case caught | |
| Hours per 1,000 store lines; hours per 10 routes; hours for the budgets file | |
| Statements and transactions per route at 5 and 50 rows, PostgreSQL and SQL Server | |
| Pool wait under 50 concurrent GETs; longest `db.tx_open_ms` | |

## Measured results

Status: current, measured at the branch head on 2026-11-15. Every figure comes from a git command: "before" is the
first committed version of each baseline file, found with `git log --diff-filter=A -- <file>`, and "after" is the file
at the branch head. Typed-boundaries totals are the sum of the count column over all rows of the baseline file, which
equals the figure in each file's header line. A cell reading "none" means the file does not exist for that service.

| Measure | documents | files | models | runner |
|---|---|---|---|---|
| Isolation sites: raw | 1 -> 0 | 1 -> 0 | 25 -> 0 | none |
| Isolation sites: caught | 5 -> 0 | 4 -> 0 | 0 -> 0 | none |
| Isolation sites: broad | not counted -> 0 | not counted -> 0 | not counted -> 0 | none |
| Isolation sites: install | not counted -> 0 | not counted -> 0 | not counted -> 23 | none |
| Typed boundaries, total | 346 -> 289 | 64 -> 58 | 97 -> 69 | 25 -> 25 |
| Config literals: timeouts | 7 -> 3 | 1 -> 0 | 2 -> 2 | 1 -> 2 |
| Config literals: clients | 7 -> 3 | 1 -> 0 | 2 -> 2 | 1 -> 0 |
| Relay sites | 1 -> 0 | 1 -> 0 | none | none |
| Loop-health rows | 2 -> 0 | 2 -> 0 | none | none |
| Routes on the request transaction (`Tx` parameters) | 16 of 33 | 16 of 27 | 16 of 19 | 0 of 2 |
| Statement budget file (`budgets.toml`) | present | present | present | none |
| Tests passing, as stated in the last commit body that gives a count | 163 | 129 | 130 (PostgreSQL) | not recorded |

Reading the table:

- The broad and install columns were added to the isolation check after the baselines were first committed, so "not
  counted" means no figure existed before. Models' 23 install sites are the model aliases and call log, which hold
  no tenant and are marked install-wide; they replaced the 25 raw transactions.
- Runner's timeouts rise from 1 to 2 while its clients fall from 1 to 0: the check was widened to count a timeout
  given by position, so the second timeout existed before and was not counted. The two literal timeouts remain in
  `fetch.py` and `wasm.py`.
- Typed boundaries for runner stay at 25 in total: one `dict-any` row became a `reply` row (the run route), so the
  total did not change.
- Runner has no store and no database, so it has no isolation, relay or loop-health baseline and no budget file. Its
  health route and its one run route are not on `Tx`.
- Route counts are decorated routes in each service's source; `Tx` parameters are counted in the same files. The
  routes that are not on `Tx` are health, streaming and fan-out routes that open their own transactions.

## Measured rates

Observed on this branch, with the caveat that several builders worked at once, so the spans are not hours of one
person's work and cannot be divided by lines to give a rate per builder. All four services were first touched by the
same shared commit (the endpoint settings and owned client), which is why the first column is the same for each. The
second column starts at the first commit whose subject names the service.

| Service | First commit touching the service | First commit naming the service | Last commit | Span from first touch | Span from first naming | Store lines changed |
|---|---|---|---|---|---|---|
| models | 17:59 | 19:46 | 22:00 | 4 h 1 min | 2 h 14 min | 418 added, 149 removed (6 files) |
| documents | 17:59 | 21:01 | 22:44 | 4 h 45 min | 1 h 43 min | 465 added, 487 removed (9 files) |
| files | 17:59 | 21:10 | 22:04 | 4 h 5 min | 0 h 54 min | 331 added, 298 removed (5 files) |
| runner | 17:59 | 22:13 | 22:30 | 4 h 31 min | 0 h 17 min | no store |

Times are local commit times on 2026-11-15. Store lines are `git diff --stat` from the parent of the first commit to
the branch head over each service's `store` directory. The branch also carries the shared components, the checks and
their tests, which are not part of any service's span.

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
