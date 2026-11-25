# Standards: data access

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `DA1` to `DA13` are frozen.
The design is in [data](../data.md), [logging and data writes](../logging-and-data-writes.md) and
[ADR-0017 database support](../decisions/database-support.md).

The stores use SQLAlchemy 2.x Core on `AsyncEngine`; there are no ORM sessions. A request opens one transaction, every
list is paged and joined in SQL, and every statement runs on PostgreSQL and SQL Server. The database audit measured 200
to 600 statements per screen with a transaction per query; these rules are what brings that down and keeps it down.

## DA1 One transaction per unit of work

Rule: the `app` layer (or one store method that is the whole unit) opens one `tenant_tx`; helpers and repository
functions take the connection as an argument and never open, commit or roll back.
Why: writes that belong together commit together, and a request with twenty reads costs one transaction and one pool
checkout instead of twenty. Each transaction costs `BEGIN`, `set_config`, the query and `COMMIT`: four round trips for
one read.

Today (`services/agents-service/src/ops_agents/api/publish_reviews.py:166`): `subject_team()` calls a store's
`owner_team()` once per request row, and each call opens its own transaction (`store/agent_registry.py:191`). The
overview route ran 53 queries in 34 transactions.

Pattern (`services/platform-service/src/ops_platform/store/members.py:461` and
`services/agents-service/src/ops_agents/store/batches.py:141`): the helper takes the connection; two updates share one
transaction.

```python
async def _audit(c: AsyncConnection, actor: Actor, action: str, member_id: str, detail: dict[str, Any]) -> None:
    await record(c, tenant_id=actor.tenant_id, ...)
```

Check: `packages/ops_store/tests/test_isolation_sites.py` fails on a new `engine.begin()` or `engine.connect()` in a
service and on a caught database error with no savepoint, against one shrink-only list per service
(`packages/ops_store/tests/isolation_sites/`); `packages/ops_identity/tests/test_request_transaction.py` proves the
request transaction (`ops_identity.fastapi.Tx`) through the real middleware, and the request line carries
`db.tx_count`. Needed: a test fixture that reads `db.tx_count` for every `GET` and fails above the route's budget.

## DA2 Statements are built with Core, never with strings

Rule: every statement is `select`, `insert`, `update` or `delete` from SQLAlchemy Core; `text()` appears only inside
`ops_store.dialect`, and never with a value joined into the string.
Why: bound parameters stop SQL injection (OWASP ASVS V5.3), and Core renders the same statement for both databases.

Today (`services/platform-service/src/ops_platform/store/signin.py:669`): a function name formatted into SQL.

```python
row = (await c.execute(sa.text(f"SELECT id, tenant_id FROM {function}(:v)"), {"v": value})).first()
```

Also `packages/ops_store/src/ops_store/schema_version.py:38`. Both format a constant from code, so the risk today is
low; both belong on a reviewed `noqa` list, not in the open.

Pattern (`services/agents-service/src/ops_agents/store/cases.py:176`):

```python
q = sa.select(cases).where(cases.c.id == case_id, cases.c.team_id.in_(teams), team_visible(cases))
```

Check: `uv run python scripts/check_portable_store.py --strict` refuses database-specific text in stores. Needed: ruff
rule `S608` in `pyproject.toml`, with the two sites on a reviewed `noqa`.

## DA3 Database differences live in one module

Rule: upsert, row lock, queue claim, app lock, clock, JSON reads and full-text search are called only through
`ops_store.dialect`.
Why: two databases, one place for their differences (ADR-0017); a store never knows which one it runs on.

Today: 73 findings in `portable-baseline.txt`, which may only fall.

Pattern (`packages/ops_store/src/ops_store/dialect.py:83`):

```python
def upsert(bind: Bind, table: sa.Table, values: Mapping[str, Any], *, keys: Sequence[str], update: ... = None, ...)
```

Check: `uv run python scripts/check_portable_store.py --strict` with `portable-baseline.txt`, in the CI `checks` job.

## DA4 No query inside a loop

Rule: a list loads its related rows with a join or one `IN` query per relation; no store method is called once per
row.
Why: a query per row grows with the page and hides in a test with three rows.

Today (`services/agents-service/src/ops_agents/api/publish_reviews.py:166`): one owner lookup per skill, guardrail or
widget request.

Pattern (`services/agents-service/src/ops_agents/store/agent_registry.py:201`): the batched form of the same lookup.

```python
async def owner_teams(self, agent_ids: set[str]) -> dict[str, str]:
```

Check: no check yet; covered by the statement budget in `DA6`.

## DA5 Lists are paged and filtered in SQL

Rule: every list route takes page, size, filters and search, runs `count()` and `LIMIT`/`OFFSET` in SQL, and returns
`paged()`'s `{data, pagination, facets}`; totals and facet counts come from the database; the maximum page size is a
setting.
Why: a list that loads every row and slices in Python costs the same for five rows as for two hundred, and the cost grows
with the team's history rather than the page.

Today (`services/agents-service/src/ops_agents/api/hitl_facade.py:320`, `services/kb-service/src/ops_kb/service.py:174`):
every row is loaded, then sliced.

```python
return {"data": rows[start : start + size], "pagination": meta}
```

The audit found nine list routes that page this way (reviews, tasks, tools, knowledge, channels, widgets, runs, tool
modules, batches).

Pattern (`services/agents-service/src/ops_agents/store/cases.py:236`):

```python
total = int((await c.execute(sa.select(sa.func.count()).select_from(cases).where(*where))).scalar_one())
q = sa.select(cases).where(*where).order_by(cases.c.resolution_due_at, cases.c.id).limit(size).offset((page - 1) * size)
```

Check: `uv run python scripts/check_portable_store.py --strict` fails on a list slice (`rows[start : start + size]`) in
a service's code outside its store, with today's sites in `list-slice-baseline.txt`, which may only fall. The shared
form is `ListQuery` (`packages/ops_service_kit/src/ops_service_kit/listing.py`) and `list_page`
(`packages/ops_store/src/ops_store/listing.py`). Needed: an OpenAPI rule that every list operation returns the paged
shape. The rule catches a bound held in a name the same function assigns (`end = o + n`), `itertools.islice` and a
tail cut then cut again; a window counted in another function or a helper passes.

## DA6 Every route has a statement budget

Rule: a list route runs a fixed number of statements whatever the page size, and a test fails when a route exceeds the
budget written beside it.
Why: a budget turns N+1 from a review opinion into a failing test.

Today: no budgets. The services already count queries per request
(`packages/ops_service_kit/src/ops_service_kit/request_timing.py:44`, logged as `db.query_count`).

Pattern (`packages/ops_service_kit/src/ops_service_kit/request_timing.py:124`): the request line carries the count the
test reads.

Check: no check yet. Needed: a pytest fixture that seeds a team at two sizes, calls each `GET` in the route inventory
through the real app, reads `db.query_count`, and fails when the count differs between sizes or exceeds the checked-in
budget.

## DA7 Foreign keys and filter columns are indexed

Rule: every foreign key column and every column a list filters or sorts on has an index, declared in the store metadata
and in the migration.
Why: an unindexed filter is a full scan that grows with the table; the mailbox poller alone made over a million
sequential scans on a development database.

Today (`services/agents-service/src/ops_agents/store/agent_registry.py:79`): publish requests are indexed on
`tenant_id` only and have no `team_id` column, so the team filter runs in Python (`TN3`). The audit lists eight missing
or unusable indexes (`mailboxes`, `engine_definitions`, `kb_chunks`, `graph_threads`, `secret_audit`,
`role_assignments` and five foreign keys).

Pattern (`services/agents-service/src/ops_agents/store/background.py:47`):

```python
sa.Index("ix_background_jobs_at", "tenant_id", "at"),
```

Check: `deploy/database/tests/test_indexes.py` fails on a foreign key column, or a column declared `info=LISTED`
(`ops_store.listing`), with no index that leads with it, outside a waiting list per chain that may only shrink.

## DA8 One migration chain per service, one head

Rule: each service has one Alembic chain with its own version table; a new revision is made by `make migration` and is
named `YYYYMMDD_HHMM_<what_it_changes>.py` (UTC), so two branches never take the same number; the revisions already in
the chains keep their `NNNN_` names. A chain has one head, and two branches that both follow the same revision are joined
by a merge revision before merge.
Why: two heads stop `alembic upgrade head` on every database at once.

Today: no breach.

Pattern (`services/agents-service/migrations/versions/0103_eval_cases_runs.py:1`): a docstring saying what the revision
changes and why, then `revision`, `down_revision`.

Check: `scripts/check_migration_heads.py` (`migration-heads` in `make checks`) fails on a chain with two heads;
`scripts/new_migration.py --self-test` (`new-migration-self-test`) checks the timestamped id; each service's test setup
upgrades an empty database to head (only for services in the CI plan).

## DA9 Every migration downgrades and runs on both databases

Rule: every revision has a working `downgrade()` and uses only operations that run on PostgreSQL and SQL Server.
Why: a rollback needs the downgrade, and the down-then-up parity test fails on an empty one ("already exists").

Today: no breach; three empty downgrades held QA red for an hour each on 10-31 before the check existed
(`scripts/check_downgrades.py:1`).

Pattern (`services/agents-service/migrations/versions/0103_eval_cases_runs.py:103`):

```python
def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
```

Check: `scripts/check_downgrades.py` in pre-commit; `deploy/database/tests/test_runtime_logins.py` (down and up per
chain) and `test_mssql_ddl.py`; `deploy/database/tests/test_model_parity.py`.

## DA10 A column is dropped one release after it stops being read

Rule: a release that stops reading a column or table only stops reading it; the next release drops it.
Why: the previous build keeps running while the new one starts, and a dropped column breaks it.

Today: no breach.

Check: no check yet. Needed: review of drop migrations against the previous release tag.

## DA11 Request paths are async end to end

Rule: request paths run on `AsyncEngine`; synchronous database access and `time.sleep` appear only in migrations,
`scripts/` and test helpers.
Why: a blocking call inside the event loop stalls every request on that process.

Today (`services/runner-service/src/ops_runner/wasm.py:165`): `time.sleep(0.01)` in a reader loop.

Pattern (`packages/ops_store/src/ops_store/isolation.py:175`): `isolated_tx` on `AsyncEngine`; every route is
`async def` (266 of 266).

Check: no check yet. Needed: ruff rule set `ASYNC` in `pyproject.toml`.

## DA12 A write states the state it expects

Rule: an update is `update().where(...)` with the expected state in the `WHERE`; code never reads a row, changes it in
Python and writes the whole row back. Time written to the database comes from `db_now()`. A person's edit of a
team-owned row carries the revision it saw and answers `409 stale_revision` when another writer got there first.
Why: a read-modify-write loses the other writer's change silently; one clock across processes keeps order.

Today (`logging-and-data-writes.md`, "What is built"): the shared write helper (`ops_store.change`, `create`,
`remove`) and the stale-revision answer are designed and not built, so each store writes its own update.

Pattern (`services/agents-service/src/ops_agents/store/batches.py:143`):

```python
r.update().where(r.c.batch_id == batch_id, team_visible(r), r.c.run_id.in_(failed)).values(attempt=r.c.attempt + 1, status="pending", run_id=None)
```

Check: no check yet. Needed: build the helper as designed in [logging and data writes](../logging-and-data-writes.md),
then a `check_portable_store.py` rule that a person's edit goes through it.

## DA13 Append-only tables have a retention rule and write nothing per idle poll

Rule: every audit, heartbeat, outbox or log table names its retention in [data](../data.md) and has a sweep; a
background poll that finds nothing writes nothing.
Why: a table with no retention grows until the disk does not; one development box held 263,299 `secret_audit` rows
(46 MB) written by the mailbox poller.

Today (`services/tools-service/src/ops_tools/store/secrets.py:96`): one `secret_audit` row per secret read, including
the poller's.

Pattern (`packages/ops_store/src/ops_store/outbox.py:115`): the relay marks a row `sent_at` and prunes sent rows once an
hour.

Check: no check yet. Needed: a test that every `GET` and every idle poll writes no row, read from the statement log.
