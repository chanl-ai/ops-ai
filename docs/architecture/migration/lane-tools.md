# Phase 2, tools lane

Status: current, 2026-11-15. tools-service's store and request layers replaced wholesale against the components, in
one branch and one pull request, beside the platform, kb and agents lanes. The gateway, OAuth, MCP, connectors, egress
and plugin logic stays; what changes is that every table is marked and policed, every store call takes the request
transaction with `team_visible()` in place of hand filters, the lists are answered in SQL, and the events the agents
lane's tool catalogue copy needs go on the outbox.

## Inputs

| Input | Where |
|---|---|
| The components and the pilot, merged on `develop` | [components.md](components.md), [pilot.md](pilot.md) and its published rates |
| The service today | `services/tools-service/src/ops_tools/`: `store/` 14 files, 3,831 lines (`calls.py`, `connections.py`, `egress.py`, `event_relay.py`, `mcp_links.py`, `mocks.py`, `modules.py`, `plugin_bindings.py`, `rate_windows.py`, `review_handoffs.py`, `secrets.py`, `send_policies.py`, `team_defaults.py`); 36 top-level modules (`gateway_calls.py` 642, `executor.py` 814, `apps.py` 2,260, `mcp_server.py`, `egress.py`, `mailboxes.py` and the rest); `modules/` 15 files 5,697 lines, `connections/` 8 files 2,619, `auth/` 6 files 1,608, `plugins/` 5 files 2,873, `secrets/` 2 files 557 |
| Its use cases | 56: `make usecase-coverage SERVICE=tools-service` lists them |
| Its unit tests | `services/tools-service/tests`, 170 files |
| The sites, counted on `develop` | 63 raw engine sites in 9 store files, filtering by hand on tables with no marking; 7 caught database errors that carry on; 16 tables with no row policy (`egress_audit`, `egress_hosts`, `egress_ranges`, `gateway_calls`, `gateway_fences`, `module_approvals`, `module_egress_hosts`, `module_operations`, `module_versions`, `operation_mocks`, `operation_rate_windows`, `plugin_bindings`, `send_checks`, `send_policies`, `team_defaults`, `tool_modules`), the credential tables among them; 2 list routes sliced in Python in `modules/service.py`; the `secret_audit` and foreign-key indexes; a relay wiring split over two receiving routes; `secret_audit` written on every poll with no retention (263,299 rows on a dev box); 10 clients, 10 literal timeouts, 3 loopback fallbacks; 21 store functions returning a dict; 2 `create_task` sites; 33 GET routes; 25 access lines on the allowlist: 16 kept with a reason, 9 converted onto `can()` or a policy |

## Size

7 to 9 builder days, against 4 to 5 in the site-by-site plan. Basis: store 3,831 lines where the hand filters are
rewritten onto `team_visible()`, not swapped (2 to 2.5); 16 tables marked and policed with backfills in one migration
(1.5); request plumbing across 36 modules for 33 GET routes and their writes, the two lists and the `/v1/apps` facets
(1.5); relay split, `secret_audit` retention, clients and fallbacks (0.75); the 25 access lines by outcome (0.75); typed
rows and tasks (0.5); the four events for the catalogue copy (0.5); the budgets file for 33 GET routes (0.5). One
builder; a second on the store layer brings it to 5 to 6 working days.

## What is replaced and what is kept

| Replaced | Kept |
|---|---|
| Every file under `store/`: classes extend `Store`; the 63 raw sites become `self.tx()` or take `conn`; every hand-written team filter becomes `team_visible()`; the 7 caught errors run inside `attempt()`; 21 functions return `Out` models; `store/event_relay.py` deleted; `store/secrets.py` stops writing `secret_audit` on a poller's read | The statements each function runs |
| The migration chain: 16 tables marked `TEAM_OWNED` or `TENANT_SCOPED`, the policy DDL for both databases, a backfill statement per table from the column the policy reads, a down path; indexes on `secret_audit` and the five foreign keys | |
| Route plumbing in `app.py`, `apps.py`, `modules/routes.py`, `connections/`, `mcp_links.py`, `send_policy_routes.py`, `egress_routes.py`, `expression_routes.py`, `mock_routes.py`: `Tx`, `ListQuery`, `In`, `Out`; `/v1/apps` with `view=`, `search=`, `ids=` and facets; the two lists in `modules/service.py` onto `list_page` | `gateway_calls.py`, `executor.py`, `egress.py`, `mcp_server.py`, `mcp_tools.py`, `mcp.py`, `transform.py`, `expressions.py`, `auth/`, `plugins/`, the connector logic in `connections/`: domain logic, inputs retyped |
| `__main__.py` endpoint fields and `require()`; its `service_client()` and the 10 clients onto `ServiceClient.for_settings`; 3 fallbacks and 10 timeouts deleted; `opa.py`'s literal port onto a setting | The OPA policy evaluation itself |
| The relay: `run_relay(relay(...))` with two route rows (`policy.changed` to `/v1/platform-events`, the rest to `/v1/events`); `retention(secret_audit, ...)` registered | |
| The outbox gains `tool.module.published`, `tool.module.changed` and `tool.team_state.changed` (app on or off for a team, tool added, account linked) for the agents lane's catalogue copy | |
| Access, from the register: the 4 system locks in `gateway_calls.py`, `modules/review_events.py` and `registry.py` become a grid cell or a policy; `system_workflow_only` goes with them; `directory.py` and `send_policy_routes.py` raise the baseline codes; `modules/routes.py`'s service check becomes a scope check through `can()` | 16 lines kept with their register reason: refusals from a record's settings, an account's owner, a team's setup, the dev-caller lock, plugin modules |

## Target shapes

```python
# services/tools-service/src/ops_tools/store/send_policies.py, after
class SendPolicyOut(Out):
    id: str
    team_id: TeamId
    name: str
    mode: Literal["allow", "review", "block"]
    revision: int

class SendPolicies(Store):
    role = ROLE

    async def list(self, conn: AsyncConnection, p: Principal, q: ListParams) -> ListPage[SendPolicyOut]:
        stmt = team_visible(sa.select(*POLICY_COLUMNS), send_policies, p)     # the policy on the table does the rest
        return await list_page(conn, stmt, q, default_sort=send_policies.c.name, search=[send_policies.c.name])

# services/tools-service/migrations/versions/<rev>_police_sixteen_tables.py, after
def upgrade() -> None:
    for table in SIXTEEN:
        op.execute(backfill_team_id(table))              # from the column the policy reads; named per table
        for statement in isolation_ddl(table, dialect(), chain="tools"):
            op.execute(statement)

# services/tools-service/src/ops_tools/apps.py, after
@router.get("/v1/apps", response_model=Envelope[ListResult[AppOut]])
async def list_apps(p: CurrentPrincipal, _: Tx, q: ListQuery, st: Stores) -> JSONResponse:
    async with st.modules.tx() as conn:
        return ok(await st.modules.apps(conn, p, q))     # view=, search=, ids= and facets in SQL

# a system lock, after
if not can(p, "tools.manage", record=module):           # a grid cell on a system record, as the register says
    raise Forbidden("tools_manage_required")

# services/tools-service/src/ops_tools/__main__.py, after
settings.require("platform_internal", "agents")
run_relay(relay(engine, outbox, routes={"policy.changed": ("platform",), "*": ("agents",)}, targets=clients,
                role=SYSTEM_ROLE, path_by_target={"platform": "/v1/platform-events"}), key="tools.relay", stop=stop)
PROCESSES.append(retention(secret_audit, secret_audit.c.at, keep_s=90 * 86400, key="tools.secret_audit", service="tools"))
```

## Step order

1. Inventory and characterisation tests, as in the pilot; 56 use cases cover more here than elsewhere, so the
   uncovered list is the gateway's edge paths and the OAuth flows, which the 170 unit tests mostly hold.
2. Markings first: the 16 tables marked in `store/tables` metadata; one migration emits the policy DDL for both
   databases with a named backfill per table and a down path; `test_isolation_markings.py` goes green for tools before
   any store call moves, because a policed table read as the owner would hide nothing and a hand filter removed before
   the policy exists would show everything.
3. Store layer: every class extends `Store`; the 63 raw sites onto `self.tx()` or `conn`; hand filters onto
   `team_visible()`; the 7 caught errors inside `attempt()`; 21 functions onto `rows()`; `secrets.py` stops writing an
   audit row per poll.
4. Request layer: `Tx` on every route; the two lists and `/v1/apps` onto `list_page`; bodies `In`, replies `Out`; the
   two `create_task` sites onto `background.start()`.
5. Access: the 9 conversions from the register; the 16 kept lines keep their reason comments; the use cases that
   assert 403 codes rerun.
6. Clients, settings, relay and retention: `settings.require(...)`; 10 clients onto `ServiceClient.for_settings`;
   fallbacks, timeouts and the OPA port literal gone; `event_relay.py` deleted for `relay()` with the two-route split;
   `retention(secret_audit, ...)` registered; the three catalogue events on the outbox.
7. Budgets file for 33 GET routes; a `loop_reports_failure` test per loop.
8. Baselines to zero for this service; use cases and tests green; pull request; after merge, SDKs regenerated on
   `develop`, staging deployed and checked.

## Commands

| Step | Command |
|---|---|
| Tests, both databases | `make -s test PKG=services/tools-service`; the `store-mssql` job on the pull request |
| Only what the change touches | `make test-impacted BASE=origin/develop` |
| The 56 use cases, in parallel | `make usecase-batch UCS="<the ids from make usecase-coverage SERVICE=tools-service>"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| Try it on the stack as a person | `make apps-list AS=<person>`, `make apps-on AS=<person>`, `make tools-run AS=<person>`, `make connectors-list AS=<person>` |
| Markings | `uv run pytest -q deploy/database/tests/test_isolation_markings.py deploy/database/tests/test_credential_tables_locked.py` |
| The ratchets | `uv run python scripts/check_access_exceptions.py`; `uv run python scripts/check_portable_store.py --strict`; `uv run lint-imports --no-logo`; `uv run python scripts/check_config_literals.py --strict`; `uv run python scripts/check_typed_boundaries.py --strict` |
| The gate | `make verify` |
| After the merge | `make sdk` and `make sdk-verify` on `develop`; `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| Markings | The 16 tables off the `WAITING` list; the credential tables locked; the migration backfills and downgrades on both databases |
| Transactions | Zero raw engine sites; zero hand-written team filters; the 7 caught errors inside `attempt()` |
| Lists and indexes | The two lists and `/v1/apps` paged, filtered and faceted in SQL; `secret_audit` and the five foreign keys indexed |
| Audit retention | No `secret_audit` row on a poller's read; `retention()` on `PROCESSES` with a health test |
| Access | The 9 conversions landed; zero role-name compares; the kept lines carry their reason; the 403 use cases pass |
| Clients and settings | Zero fallbacks, timeouts and `httpx.AsyncClient` constructions outside the gateway's own egress client; `__main__` exits naming an unset required endpoint |
| Typed boundaries | 21 store functions return models; every body an `In`, every reply an `Out`; zero bare tasks |
| Relay, events and loops | `event_relay.py` gone; the three catalogue events on the outbox and received by agents-service; every `PROCESSES` key has a `loop_reports_failure` test |
| Relay and loop baselines | `packages/ops_store/tests/relay_sites/tools-service.txt` deleted; `packages/ops_store/tests/loop_health/tools.txt` emptied (`sign_in_keepalive`, `tools_relay`) |
| Budgets | 33 GET routes green at 5 and 50 rows on both databases |
| Behaviour and staging | Tests, the 56 use cases and `make verify` green on the merge commit; staging deployed with every process up and the console walk green; Apps, Connections, Egress and MCP screens opened by hand, one tool run through the gateway |

## Branch and pull request

Branch `refactor/tools-store-and-api-layers` from `origin/develop`, one pull request into `develop`, rebased once on
the pilot's merge. Commit subject at most 72 characters, body at most three lines. A reviewer who did not write it
approves against this page and the standards. Merge order: fourth, after kb. If the lane runs over, the split line is
the access conversions and the catalogue events as a second pull request on the same branch name with a suffix, never
a second lane.

## What not to touch

- `gateway_calls.py`, `executor.py`, `egress.py`, `mcp_server.py`, `auth/`, `plugins/`, `connections/` connector
  logic: domain logic, inputs retyped only.
- `packages/ops_plugin_sdk`, `builtin-plugins/`, `plugins/`.
- Any other service's files or baseline rows; the `tool_catalog` and `tool_team_state` copy tables are the agents
  lane's.
- The console; the Apps screens move onto `view=` and facets in the console lane.
- The generated SDK layer inside the pull request.
