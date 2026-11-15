# Phase 2, agents lane

Status: current, 2026-11-15. agents-service's store and request layers replaced wholesale against the components, in
one branch and one pull request, beside the platform, kb and tools lanes. The largest lane and the least certain
number. Graph execution, the kernel, the engine, reviews, cases, chat and the channel adapters stay; what changes is
that every store file sits on the base with typed rows, every table is policed, every list is answered in SQL, the
screens' labels come from local copies, and every route opens one transaction.

## Inputs

| Input | Where |
|---|---|
| The components, C8 included, and the pilot, merged on `develop` | [components.md](components.md), [pilot.md](pilot.md) and its published rates |
| The service today | `services/agents-service/src/ops_agents/`: `store/` 43 files, 8,504 lines; `api/` 91 files, 19,852 lines (`api/routers/` 46 files, `api/channels/inbox.py`, and the top-level `api/*.py` modules where most domain functions live); `app/` 2 files; `domain/` 3 files; `graphs/`, `activities/` |
| Its use cases | 93: `make usecase-coverage SERVICE=agents-service` lists them |
| Its unit tests | `services/agents-service/tests`, 318 files |
| The sites, counted on `develop` | 104 raw engine sites and 170 `tenant_tx` calls in 14 store files; 7 caught database errors that carry on; 6 streaming routes (`api/chat.py`, `api/routers/engine.py`, `api/routers/events.py` twice, `api/routers/graphs.py`, `api/routers/widget.py`); 21 tables with no row policy in two chains (runtime: `channel_cursors`, `channel_files`, `channel_messages`, `deployments`, `graph_versions`, `model_call_records`, `thread_budgets`, `thread_inbox`, `thread_leases`, `timers`; registry: `registry_agents`, `registry_agent_versions`, `registry_guardrails`, `registry_guardrail_versions`, `registry_skills`, `registry_skill_versions`, `registry_validations`, `registry_widgets`, `registry_widget_versions`, `registry_workflows`, `registry_workflow_versions`); 7 list routes sliced in Python (`api/hitl_facade.py`, `api/routers/channel_list.py`, `api/routers/engine.py`, `api/routers/tool_catalog.py` twice, `api/routers/widgets.py` twice); `registry_publish_requests` with no team column, other teams dropped in Python; `owner_team()` copied in five stores and called per row; the `graph_threads` owner read from JSON; 12 clients and 14 literal timeouts, 1 loopback fallback; 3 bodies with `extra="allow"`; the lock in `api/channels/inbox.py` opening its own connection; 89 store functions returning a dict; 3 gather and 12 `create_task` sites; replies built as dicts across 112 api files; 102 GET routes; 11 access lines on the allowlist: 9 kept with a reason, 2 deleted with the import route; `/v1/tools` built from two hops to tools-service and sliced in Python; the agent page fetching 200 tools and 100 knowledge bases to label a few |

## Size

11 to 14 builder days with one builder, against 6 to 7 in the site-by-site plan. Basis: store 8,504 lines at 1,800 a
day (4.5 to 5); 21 tables marked and policed in two chains with backfills (1.5); request plumbing for 102 GET routes
and their writes across 91 files, the 7 lists onto `list_page`, the 6 streaming routes onto `Tx` (3); the agent read
and the overview with labels and counts from the copies and local tables in one transaction (1); clients, the inbox
lock, the publish-request column with its backfill and indexes (0.75); typed rows, replies and tasks beyond the store
rewrite (0.75); the budgets file for 102 GET routes and the loop tests (0.75). With two builders, one on the store
layer and one on the request layer, with the `Out` row models agreed on day one as the contract between them: 6 to 8
working days. This is the lane whose size the pilot's measured rates matter most for.

## What is replaced and what is kept

| Replaced | Kept |
|---|---|
| Every file under `store/` (43): classes extend `Store`; `tenancy.py`'s `tenant_tx` becomes an alias of the base's `tx()`; the 104 raw sites and 170 calls onto `self.tx()` or `conn`; `owner_team()` in `agent_registry.py`, `guardrails.py`, `skills.py`, `widgets.py` and `workflow_registry.py` deleted for `Store.owner_teams()`; the 7 caught errors inside `attempt()`; 89 functions onto `rows()` and `one()`; `activity.py`'s 12 JSON owner reads onto the new `graph_threads` owner column | The statements each function runs |
| Both migration chains: 21 tables marked and policed with a backfill per table and a down path; `registry_publish_requests.team_id` with its backfill from the subject's owning team; `graph_threads.owner` from `meta->>'ownerEmail'`; indexes on publish requests by team, `engine_definitions` by team, `graph_threads` owner; the `tool_catalog`, `tool_team_state` and `kb_labels` copy tables from C8 | |
| Route plumbing in `api/routers/` (46 files) and the route-bearing top-level `api/` modules: `Tx` on every route; the 7 lists onto `list_page`; `/v1/tools` onto `list_page` over the catalogue copy; bodies onto `In` (the 3 `extra="allow"` bodies onto `Passthrough` where they forward, `In` otherwise); replies onto `Out`; `api/channels/inbox.py`'s lock into the store; the 3 gather sites onto `TaskGroup`, the 12 `create_task` sites onto `background.start()`; the agent read and the overview counts from SQL and the copies | The domain functions in `api/*.py` and `graphs/`, `activities/`, `domain/`, `app/`: `engine_host.py`, `engine_runs.py`, `engine_resume.py`, `hitl_facade.py`'s review rules, `chat_history.py`, `run_story.py`, `case_page.py`, `mailbox_gateway.py`, `sweeper.py`, `worker.py`; inputs retyped where a dict crossed |
| `api/app.py`'s `service_client()` and the 12 clients onto `ServiceClient.for_settings`; the fallback and 14 timeouts deleted; endpoint fields and `require()` in the entry point | `service_events.py` keeps receiving tools-service's and kb-service's events; it gains `copies.apply()` for the three catalogue events and `kb.changed` |
| Access, from the register: the import route and its `service_required` line deleted; `api/tool_module_reviews.py`'s service-name compare deleted with it | 9 lines kept with their reason: typed errors from a `can()` answer computed earlier, the asker rule, owner or `chat.manage` through `can()`, separation of duties, a team's own form, the dev-caller lock |

## Target shapes

```python
# services/agents-service/src/ops_agents/store/agent_registry.py, after
class AgentOut(Out):
    id: str
    team_id: TeamId
    name: str
    status: Literal["draft", "published", "retired"]
    owner_team_name: str          # joined in the statement
    tool_count: int               # counted in the statement
    revision: int

class AgentRegistry(Store):
    role = ROLE

    async def list(self, conn: AsyncConnection, p: Principal, q: ListParams) -> ListPage[AgentOut]:
        return await list_page(conn, team_visible(agents_with_counts(), registry_agents, p), q,
                               default_sort=registry_agents.c.name, search=[registry_agents.c.name],
                               facets={"status": registry_agents.c.status}, sortable={"updated": registry_agents.c.updated_at})

    async def read(self, conn: AsyncConnection, p: Principal, agent_id: str) -> AgentPageOut | None:
        """The agent page in one transaction: the agent, its granted tools with names and approval state from
        tool_catalog and tool_team_state, its knowledge bases with names and colours from kb_labels, its guardrail
        names. No hop, no second call from the browser."""

# services/agents-service/src/ops_agents/api/routers/agents.py, after
@router.get("/v1/agents", response_model=Envelope[ListResult[AgentOut]])
async def list_agents(p: CurrentPrincipal, _: Tx, q: ListQuery, rt: Rt) -> JSONResponse:
    async with rt.registry.tx() as conn:
        return ok(await rt.registry.list(conn, p, q))

# services/agents-service/src/ops_agents/api/routers/events.py, after
@router.get("/v1/runs/{run_id}/events")
async def run_events(p: CurrentPrincipal, _: Tx, rt: Rt, run_id: str) -> EventSourceResponse:
    run = await rt.runs.get(run_id)                       # on the request transaction, which closes on return
    return EventSourceResponse(frames(rt, run_id))        # each frame's store call opens its own transaction

# services/agents-service/src/ops_agents/api/routers/overview.py, after
@router.get("/v1/overview", response_model=Envelope[OverviewOut])
async def overview(p: CurrentPrincipal, _: Tx, rt: Rt) -> JSONResponse:
    async with rt.activity.tx() as conn:
        return ok(await rt.activity.overview(conn, p))     # the tiles counted in SQL, one transaction, not 53 queries in 34

# services/agents-service/src/ops_agents/api/service_events.py, after
async def receive(p: CurrentPrincipal, _: Tx, event: Event, rt: Rt) -> JSONResponse:
    async with rt.copies.tx() as conn:
        match event.payload:
            case ToolPublished() | ToolChanged():      await copies.apply(conn, tool_catalog, event)
            case ToolTeamStateChanged():               await copies.apply(conn, tool_team_state, event)
            case KbChanged():                          await copies.apply(conn, kb_labels, event)
    return ok(None)
```

## Step order

1. Inventory and characterisation tests, as in the pilot. With 93 use cases and 318 test files this service is the
   best covered; the uncovered list is still written down and tested first, since the rewrite touches 28,000 lines.
2. Agree the row models: one `Out` per store function, written as a module per store file before either layer moves,
   so a store builder and a request builder can work the same days.
3. Markings and migrations first, in both chains: the 21 tables, the publish-request team column with its backfill,
   the `graph_threads` owner column, the indexes, the three copy tables; `test_isolation_markings.py` green for agents
   before any store call moves.
4. Store layer: the 43 files onto the base; `owner_team()` deleted five times for `Store.owner_teams()`; the 7 caught
   errors inside `attempt()`; 89 functions onto `rows()` and `one()`; the inbox lock moved into `store/mailboxes.py`.
5. Request layer: `Tx` on every route; the 7 lists and `/v1/tools` onto `list_page`; the 6 streaming routes as above;
   the agent read and the overview from SQL and the copies; bodies `In` or `Passthrough`, replies `Out`; the 15 bare
   task sites onto `TaskGroup` and `background.start()`; `service_events.py` applies the four copy events.
6. Access: the import route and its two lines deleted; the 9 kept lines keep their reason; the 403 use cases rerun.
7. Clients and settings: `settings.require("tools", "kb", "platform_internal", "models", "files", "documents")` as
   the deployment needs; the 12 clients onto `ServiceClient.for_settings`; the fallback and timeouts deleted.
8. Budgets file for 102 GET routes with the 6 streaming and the fan-out routes carrying their allowance; a
   `loop_reports_failure` test per loop (the sweeper, timers, the relay receiver, the copy resyncs).
9. Baselines to zero for this service; use cases and tests green; pull request; after merge, SDKs regenerated on
   `develop`, staging deployed and checked. If the lane runs over, the split line is the screen-shaped reads (the agent
   page, the overview) and the typed replies as a second pull request on the same lane; the store layer and markings
   never split from each other.

## Commands

| Step | Command |
|---|---|
| Tests, both databases | `make -s test PKG=services/agents-service`; the `store-mssql` job on the pull request |
| Only what the change touches | `make test-impacted BASE=origin/develop` |
| The 93 use cases, in parallel | `make usecase-batch UCS="<the ids from make usecase-coverage SERVICE=agents-service>"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| Try it on the stack as a person | `make chat AS=<person>`, `make runs-start AS=<person>`, `make runs-events AS=<person>`, `make tasks-list AS=<person>`, `make cases-list AS=<person>` |
| Markings | `uv run pytest -q deploy/database/tests/test_isolation_markings.py` |
| The ratchets | `uv run python scripts/check_access_exceptions.py`; `uv run python scripts/check_portable_store.py --strict`; `uv run lint-imports --no-logo`; `uv run python scripts/check_config_literals.py --strict`; `uv run python scripts/check_typed_boundaries.py --strict` |
| The gate | `make verify` |
| After the merge | `make sdk` and `make sdk-verify` on `develop`; `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| Markings and migrations | The 21 tables off the `WAITING` list; `registry_publish_requests.team_id` filled and indexed; `graph_threads.owner` filled and indexed; both chains downgrade on both databases; the release proof passes from the last tag against a seeded database |
| Transactions | Zero raw engine sites and zero `tenant_tx` outside the alias; the 7 caught errors inside `attempt()`; the 6 streaming routes close the request transaction before the first frame; the agent page is a handful of calls each in one transaction, not 596 statements in 157 |
| Lists and labels | The 7 lists and `/v1/tools` paged, filtered and faceted in SQL; publish requests filtered by team in SQL; the agent read's tool, knowledge-base and guardrail labels from the copies and local tables; the overview tiles counted in SQL; `owner_team()` gone |
| Copies | A published module appears in `/v1/tools` after one relay pass; a renamed knowledge base appears on the agent page; the resyncs on `PROCESSES` with health tests |
| Access | The import route gone with its two lines; zero role-name compares; the kept lines carry their reason; the 403 use cases pass |
| Clients and settings | Zero fallbacks, timeouts and `httpx.AsyncClient` constructions; the entry point exits naming an unset required endpoint; the `ops_agents` and `ops_email` lines of the `httpx` waiting list in `.importlinter` (contract `http-clients-in-their-owners`) are deleted, and `services/agents-service/config-literals-baseline.txt` is empty |
| Typed boundaries | 89 store functions return models; zero `extra="allow"` outside `Passthrough`; every reply an `Out`; zero bare tasks |
| Budgets | 102 GET routes green at 5 and 50 rows on both databases |
| Behaviour and staging | Tests, the 93 use cases and `make verify` green on the merge commit; staging deployed with every process up and the console walk green; the agent page, a chat, a run with its events, Reviews and Cases opened by hand |

## Branch and pull request

Branch `refactor/agents-store-and-api-layers` from `origin/develop`, one pull request into `develop`, rebased once on
the tools lane's merge. Commit subject at most 72 characters, body at most three lines. A reviewer who did not write
it approves against this page and the standards. Merge order: fifth, after tools, and before the console lane closes.

## What not to touch

- `graphs/`, `activities/`, `domain/`, the kernel and engine modules under `api/` (`engine_host.py`, `engine_runs.py`,
  `engine_resume.py`, `fencing.py`, `sweeper.py`, `worker.py`), the review rules in `hitl_facade.py`, the channel
  adapters: domain logic, inputs retyped only.
- `packages/ops_engine`, `packages/ops_agent_kernel`, `packages/ops_checkpointer`.
- Any other service's files or baseline rows. tools-service's and kb-service's outbox events are their lanes'.
- The console; the agent page's and runs screens' hooks move in the console lane once this lane's SDK is regenerated.
- The generated SDK layer inside the pull request.
