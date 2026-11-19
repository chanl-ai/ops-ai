# Standards: layers and ownership

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `LY1` to `LY9` are frozen.

The order inside a service is `api` (routes) → `app` (use cases) → `store` (repositories) → `ops_store` (the database
door), with `domain` below `app` holding rules that touch no input or output. Across the product the order is
services → OpenAPI document → SDKs → console and CLI. Every rule below keeps those arrows pointing one way, and keeps
one owner for each job.

```
console, CLI ──► SDK ──► HTTP ──► api ──► app ──► store ──► ops_store ──► database
                                          └──► domain (pure rules)
                 adapters (other services, model and tool gateways) ◄── app, through a port
```

## LY1 Imports point inward

Rule: inside a service a module imports only its own layer or a lower one; `api` imports `app`, `app` imports `store`
and `domain`, and `store` imports nothing else of its service.
Why: a layer that imports upward cannot be tested alone, and a route that reaches a store directly cannot be reused by
the worker, the CLI or a workflow step.

Today (`services/agents-service/src/ops_agents/api/channels/inbox.py:33`): a module under `api/` opens a database
transaction and takes a row lock itself.

```python
async with graph_store(rt).engine.begin() as c:
    await thread_lock(c, thread_id)
```

Pattern (`services/agents-service/src/ops_agents/api/routers/cases.py:44`): the route parses, calls one `app`
function and wraps the result.

```python
@router.get("/{thread_id}", response_model=Envelope[CaseRun])
async def get_run(rt: Rt, thread_id: str) -> JSONResponse:
    return ok(await hitl_facade.get_run(rt, thread_id))
```

Check: `.importlinter` contracts `*-store-is-bottom` (`.importlinter:80` onward) keep `store` at the bottom of eight
services, run by `uv run lint-imports --no-logo` in the CI `checks` job. The full order is checked only for
agents-service (`services/agents-service/scripts/check_standards.py` rule 1). Needed: a `layers` contract per service
with today's upward imports listed as ignored imports that may only shrink.

## LY2 A route does one thing

Rule: a route parses its input, resolves the caller, calls one `app` function and returns `ok()` or `paged()`; it
holds no business rule, no loop over rows and no transaction.
Why: a rule written in a route exists once for HTTP and nowhere for the worker or a workflow step, so the two drift.

Today (`services/agents-service/src/ops_agents/api/hitl_facade.py:320`): a module under `api/` builds, filters and
pages a list in Python.

```python
return {"data": rows[start : start + size], "pagination": meta}
```

Pattern (`services/agents-service/src/ops_agents/api/routers/cases.py:35`): a list route hands the query to the app
layer and returns the envelope.

Check: no check yet. Needed: an AST rule that a function decorated with a router method calls one `app` function and
imports no `store` module.

## LY3 Database code lives in the stores

Rule: SQLAlchemy, Alembic and database drivers are imported only in a service's `store/` package, in `ops_store`, in
`ops_engine.store` and in the checkpointer.
Why: tenant isolation and support for two databases are possible only while the database is reached from one place.

Today: no breach; the contract holds across every service.

Pattern (`.importlinter:34`): the contract `drivers-only-in-stores` names the allowed importers.

Check: `uv run lint-imports --no-logo`, the `lint-imports` entry of `make checks` (`make/checks.mk`).

## LY4 Services never import each other

Rule: a service never imports another service's code and never reads another service's tables; it calls the other
service through `ops_identity.ServiceClient` or a client package.
Why: each service must deploy alone or inside one host process with no hidden coupling
([service map](../service-map.md)).

Today (`services/tools-service/src/ops_tools/registry.py:15`): tools-service imports agents-service code.

```python
from ops_agents.activities.catalog import Catalog
```

Pattern (`services/documents-service/src/ops_documents/store/event_relay.py:34`): documents-service reaches
agents-service and kb-service over HTTP with a service token.

```python
await client.post("/v1/events", body, tenant=str(item["tenantId"]), team=str(body["teamId"]))
```

A shape one service sends and another reads is one class in `ops_contracts` (a `ServiceShape`), which the sender
builds and the reader reads; a reader that keeps its own model of the shape refuses the sender's next field and
answers 500 (`packages/contracts/src/ops_contracts/templates.py`, `CopyRef`: agents-service and documents-service
send it, tools-service reads it into an app's resources).

Check: `.importlinter` contract `services-independent` (`.importlinter:145`) with the departure listed; the list may
only shrink. For a `ServiceShape`, `scripts/tests/test_no_cross_service_imports.py` (the `cross-service` check) fails
when a service's committed `openapi.json` describes it differently or declares its fields under another name. A shape
that is not yet a `ServiceShape` has no check: `Installed` and `TemplateRequires` are still declared in all three
services (`services/tools-service/src/ops_tools/plugins/templates.py`, `ResourceInstalled` and `TemplateRequires`).

## LY5 Packages never import a service

Rule: a package holds mechanism; the rule a service applies arrives as an argument, a port or a setting, and no
package imports `ops_agents`, `ops_tools`, `ops_platform`, `ops_models`, `ops_kb`, `ops_files` or `ops_documents`.
Why: a package that knows one service's rules cannot serve the next service.

Today: `ops_pii` and `ops_plugin_sdk` sit outside the contract's `root_packages` (`packages/CLAUDE.md:24`), so a
service import added to either would not be caught.

Pattern (`packages/ops_store/src/ops_store/outbox.py:115`): `Relay` takes the table, the send function and the role
as arguments and knows no service.

Check: `.importlinter` contract `libraries-below-services` (`.importlinter:164`). Needed: add the two packages to
`root_packages`.

## LY6 The console and the CLI call the platform through the SDK

Rule: the console sends HTTP only from `apps/console/src/lib/api/`, and new screens call services through `sdk()`
(`apps/console/src/lib/api/ops-sdk.ts`); the CLI calls client methods only.
Why: one client is one place for the token, the team header, the envelope, paging and errors.

Today (`apps/console/src/components/ai-elements/prompt-input.tsx:685`): a component fetches on its own.

```ts
const response = await fetch(url);
```

Pattern (`apps/console/src/hooks/systems-queries.ts:11`): a hook reads through the generated SDK, and its types come
from the SDK's operations.

```ts
import { sdk } from '@/lib/api/ops-sdk';
type Tools = OpsAI['raw']['tools'];
```

Check: `apps/console/scripts/check-standards.mjs` rules 2 and 3 (components are props-only, pages read through hooks).
Needed: a rule that `fetch(` appears only under `src/lib/api/`, with the two files that break it today listed.

## LY7 One owner per job

Rule: before adding a helper, client, queue, scheduler, store method or component, list what already does that job
(file:line) and use or extend it; a second owner needs a written reason.
Why: a fix lands in one copy and leaves the others broken.

Today (`services/agents-service/src/ops_agents/store/agent_registry.py:191`, `guardrails.py:133`, `skills.py:149`,
`widgets.py:134`, `workflow_registry.py:101`): the same `owner_team(id)` lookup is written in five stores.

Pattern (`packages/ops_store/src/ops_store/outbox.py:115`): one `Relay` delivers every service's outbox; each service
passes its table and its send function.

Check: review, with `scripts/agents/review_context.py` listing the new public surface of a change. The console has
`check-standards.mjs` rule 16 (one component per job). Needed: a duplicate-code ratchet over `services/*/src` with
today's count as the ceiling.

## LY8 Names say what the module does

Rule: a package or module is named for its job; nothing is called `shared`, `common`, `utils`, `helpers` or `manager`.
Why: a vague name hides that a module has more than one job, and is where the next unrelated function lands.

Today (`apps/console/src/lib/utils/`): a folder named for nothing in particular. (`components/shared/` is the
console's published pattern library and is named in `apps/console/CLAUDE.md`.)

Pattern (`packages/`): `ops_store`, `ops_access`, `ops_identity`, `ops_metering`; each name is the job.

Check: no check yet. Needed: a name ratchet in `scripts/check-public-paths.mjs` or a sibling.

## LY9 Outside systems sit behind a port

Rule: anything that may later live outside us (a vault, a model provider, search, object storage, a workflow engine)
is a port in `app` or in a package, with our implementation as one adapter.
Why: an enterprise replaces the adapter and keeps the use case.

Today: no known breach.

Pattern (`packages/ops_policy/src/ops_policy/credentials.py:27`, `packages/ops_engine/src/ops_engine/ports.py:44`):
`CredentialStore` and `ToolPort` are protocols; the services supply the implementation.

Check: review against [ADR-0015](../decisions/) (the engine stays open) and the service map.
