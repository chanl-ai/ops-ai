# Phase 2, kb lane

Status: current, 2026-11-15. kb-service's store and request layers replaced wholesale against the components, in one
branch and one pull request, beside the platform, tools and agents lanes. Ingest, chunking, embedding, retrieval and
the source adapters stay; what changes is how the four lists are answered, how a route opens its transaction, types its
values and reaches other services, and the `kb.changed` event the agents lane needs for its label copy.

## Inputs

| Input | Where |
|---|---|
| The components and the pilot, merged on `develop` | [components.md](components.md), [pilot.md](pilot.md) and its published rates |
| The service today | `services/kb-service/src/ops_kb/`: `store/` 5 files, 1,619 lines (`fulltext.py`, `knowledge.py`, `vectors.py`, `event_relay.py`); `service.py` 3,323 lines holding the four lists and much of the request plumbing beside the domain logic; `app.py` 659; `schemas.py` 756; `tool_sources.py` 665; `files.py`, `retrieval.py`, `embedding.py`, `query_steps.py`, `schedule.py`, `search.py` |
| Its use cases | 7: `uc-080 uc-129 uc-399 uc-675 uc-676 uc-677 uc-678` |
| Its unit tests | `services/kb-service/tests`, 52 files |
| The sites, counted on `develop` | 4 lists sliced in Python in `service.py`; 2 raw engine sites and 7 `isolated_tx` calls; the `kb_chunks` index; a relay wiring with two targets (audit to platform, the rest to agents); 7 clients, 12 literal timeouts, 3 loopback fallbacks; a local `In` base; 14 store functions returning a dict; 1 gather and 5 `create_task` sites; 20 GET routes; a duplicate knowledge-base name answered without a savepoint |

## Size

4 to 5 builder days, against 3 to 4 in the site-by-site plan. Basis: store 1,619 lines (1); the four lists and the
request plumbing in a 3,323-line `service.py` where it sits beside the domain logic, so the cut takes care (1.5);
clients, fallbacks and the relay (0.5); `kb.changed` on the outbox and the 409 (0.5); typed rows and tasks (0.5); the
budgets file for 20 GET routes (0.5). One builder.

## What is replaced and what is kept

| Replaced | Kept |
|---|---|
| `store/knowledge.py`, `store/fulltext.py`, `store/vectors.py` onto `Store`, `rows()` and `attempt()`; `store/event_relay.py` deleted | The statements each function runs, with named columns |
| In `service.py`: `page_of()` and `_facet()` and the four list functions onto `list_page`; every store call onto `self.tx()` or `conn`; the request-shaped functions take `ListParams` and return `Out` models; the gather and `create_task` sites | In `service.py`: ingest, chunking, change detection and sync logic, called by the same routes with typed inputs |
| Route plumbing in `app.py`: every route takes `Tx`; list routes take `ListQuery`; bodies in `schemas.py` extend the kit's `In` (the local base deleted), replies `Out` | `retrieval.py`, `embedding.py`, `query_steps.py`, `search.py`, `tool_sources.py`, `files.py`, `schedule.py` (its loop registered with a health test) |
| `__main__.py` endpoint fields and `require()`; the 7 clients onto `ServiceClient.for_settings`; 3 fallbacks and 12 timeouts deleted (`agents.py` and the files client among them) | `seed.py`, `origin.py`, `repeats.py` |
| The outbox gains `kb.changed` (name, colour, revision) for the agents lane's `kb_labels` copy | |
| Wired to `ops_store.copies`: `kb.changed` carries the knowledge base's `id` in its payload (`"deleted": true` when it goes), and an internal full list of every tenant's names, colours and revisions is what the agents lane's `resync` of `kb_labels` reads | |

## Target shapes

```python
# services/kb-service/src/ops_kb/store/knowledge.py, after
class KnowledgeBaseOut(Out):
    id: str
    team_id: TeamId
    name: str
    colour: str
    source_count: int          # counted in the same statement, never in Python
    revision: int

class Knowledge(Store):
    role = ROLE

    async def list(self, conn: AsyncConnection, team: str, q: ListParams) -> ListPage[KnowledgeBaseOut]:
        return await list_page(conn, bases_with_counts(team), q, default_sort=bases.c.name,
                               search=[bases.c.name], facets={"status": bases.c.status})

    async def create(self, conn: AsyncConnection, team: str, body: KnowledgeBaseIn) -> KnowledgeBaseOut:
        try:
            async with self.attempt(conn):
                row = await one(conn, sa.insert(bases).values(...).returning(*BASE_COLUMNS), KnowledgeBaseOut)
        except IntegrityError as e:
            raise Conflict("knowledge_base_name_taken") from e      # 409, on a connection that stays usable
        await outbox.add(conn, events, Event(name="kb.changed", tenant_id=..., team_id=team, revision=row.revision,
                                             payload=KbChanged(id=row.id, name=row.name, colour=row.colour)))
        return row

# services/kb-service/src/ops_kb/app.py, after
@router.get("/v1/knowledge-bases", response_model=Envelope[ListResult[KnowledgeBaseOut]])
async def list_bases(p: CurrentPrincipal, _: Tx, q: ListQuery, st: Stores) -> JSONResponse:
    async with st.knowledge.tx() as conn:
        return ok(await st.knowledge.list(conn, p.team, q))       # ids= and search= serve the pickers

# services/kb-service/src/ops_kb/__main__.py, after
run_relay(relay(engine, outbox, routes={"kb.audit": ("platform",), "*": ("agents",)}, targets=clients,
                role=SYSTEM_ROLE), key="kb.relay", stop=stop)
```

## Step order

1. Inventory and characterisation tests, as in the pilot; seven use cases over 20 GET routes leaves many routes
   uncovered, so this step is larger here than its line count suggests.
2. Store layer: the three store files onto the base; the 2 raw and 7 `isolated_tx` sites; 14 functions onto `rows()`
   and `one()`; the duplicate-name insert inside `attempt()` answering 409; the `kb_chunks` index in the migration
   chain.
3. The four lists in `service.py` onto `list_page` with their facets and counts in SQL; `page_of()` and `_facet()`
   deleted; knowledge bases answer `ids=` and `search=`.
4. Request layer in `app.py`: `Tx`, `ListQuery`, `In` and `Out`; the local `In` base deleted; the gather site onto
   `TaskGroup`, the five `create_task` sites onto `background.start()` or a `TaskGroup` child.
5. Clients, settings and relay: `settings.require("agents", "platform_internal", "files")`; the 7 clients onto
   `ServiceClient.for_settings`; fallbacks and timeouts deleted; `event_relay.py` deleted for `relay()` with two route
   rows; `kb.changed` added to the outbox on create, rename, recolour and delete.
6. Budgets file for 20 GET routes; a `loop_reports_failure` test per loop, the sync schedule included.
7. Baselines to zero for this service; use cases and tests green; pull request; after merge, SDKs regenerated on
   `develop`, staging deployed and checked.

## Commands

| Step | Command |
|---|---|
| Tests, both databases | `make -s test PKG=services/kb-service`; the `store-mssql` job on the pull request |
| Only what the change touches | `make test-impacted BASE=origin/develop` |
| The seven use cases, in parallel | `make usecase-batch UCS="uc-080 uc-129 uc-399 uc-675 uc-676 uc-677 uc-678"` |
| Use cases the change touches, plus the core console ones | `make uc-impacted BASE=origin/develop` |
| Try it on the stack as a person | `make kb-bases AS=<person>`, `make kb-search AS=<person>`, `make kb-sync AS=<person>` |
| The ratchets | `uv run python scripts/check_portable_store.py --strict`; `uv run python scripts/check_access_exceptions.py`; `uv run lint-imports --no-logo`; `uv run pytest -q deploy/database/tests`; `uv run python scripts/check_config_literals.py --strict`; `uv run python scripts/check_typed_boundaries.py --strict` |
| The gate | `make verify` |
| After the merge | `make sdk` and `make sdk-verify` on `develop`; `make stg-deploy REF=<merge commit>`; `make stg-health` |

## Acceptance

| Check | Green when |
|---|---|
| Transactions | Zero raw engine sites and zero per-call `isolated_tx` outside `self.tx()`; the duplicate-name path answers 409 and the request's connection stays usable |
| Lists and indexes | The four lists paged, filtered and counted in SQL; zero list slices; `kb_chunks` indexed; pickers answer `ids=` |
| Clients and settings | Zero fallbacks, timeouts and `httpx.AsyncClient` constructions; `__main__` exits naming an unset required endpoint |
| Typed boundaries | 14 store functions return models; the local `In` gone; zero bare tasks |
| Relay, event and loops | `event_relay.py` gone; `kb.changed` on the outbox and received by agents-service's `/v1/events`; every `PROCESSES` key has a `loop_reports_failure` test |
| Relay and loop baselines | `packages/ops_store/tests/relay_sites/kb-service.txt` deleted; `packages/ops_store/tests/loop_health/kb.txt` emptied (`kb_embed`, `kb_relay`, `knowledge_schedule`) |
| Budgets | 20 GET routes green at 5 and 50 rows on both databases |
| Behaviour and staging | Tests, the seven use cases and `make verify` green on the merge commit; staging deployed with every process up and the console walk green; the Knowledge screens opened by hand, a sync run |

## Exceptions

| Site | Why it stays | Baseline rows kept |
|---|---|---|
| `app.py` `_models_http`: an `httpx.AsyncClient` for rerank, rewrite and embeddings; `ai.py` `models_clients`: an `httpx.Client` per sync run for likely questions | Both call models-service with kb-service's own model key (`models_key`), not a service token, so `ServiceClient.for_settings` does not fit. The kit's model clients (`ops_service_kit.model_calls.ModelCalls` and `IngestModel`) take the key but expect the caller to build the HTTP client; the kit has no constructor that builds one from the `models` endpoint. The address and timeout still come from `settings.models`, and a search's model steps are bound by `kb_search_wait_s`. The rows go when the kit gives `ModelCalls` and `IngestModel` a constructor from settings | `config-literals-baseline.txt`: `client` for `ai.py` and `app.py` |

## Branch and pull request

Branch `refactor/kb-store-and-api-layers` from `origin/develop`, one pull request into `develop`, rebased once on the
pilot's merge. Commit subject at most 72 characters, body at most three lines. A reviewer who did not write it approves
against this page and the standards. Merge order: third, after platform.

## What not to touch

- Ingest, chunking, embedding and retrieval logic in `service.py`, `retrieval.py`, `embedding.py`, `query_steps.py`,
  `tool_sources.py`: inputs retyped only.
- Any other service's files or baseline rows. The `kb_labels` copy table lives in agents-service and is the agents
  lane's.
- The console; the Knowledge pickers move onto `ids=` in the console lane.
- The generated SDK layer inside the pull request.
