"""Service events start workflows (c-258): services never call each other to act. A service reports a named event with
a key (`POST /v1/events`), and the tenant's handler for it runs, on the event's team, with the event's payload as its
input. The handler is the tenant's no-team workflow under the id `seed/event_workflows.json` gives the event, at its
live version; it is an ordinary workflow, edited and published through review.

The run key is `<event>:<key>`, so a repeat delivery returns the run it started; a repeat after that run failed starts
the next attempt (`<event>:<key>:2`, `:3`). An event nobody handles is recorded `unhandled`, never dropped. The shipped
event workflows are published to a tenant when its first event arrives, so every tenant has them without a migration
per tenant; one the tenant already has, edited or not, is left as it is."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from ops_engine import default_registry
from ops_engine.definition import WorkflowDefinition, parse, validate
from ops_engine.store import DefinitionStore, RunStore, WorkflowOwnedError
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.engine import AsyncEngine, EngineTransactions
from ..store.service_events import ServiceEvents, attempts_of, listeners
from ..store.tenancy import current_tenant
from .deps import Runtime
from .engine_lifecycle import definitions, open_publish
from .engine_runs import start_run
from .event_workflows import EVENT_WORKFLOWS, handlers

log = get_logger("ops_agents.service_events")

FAILED = ("failed", "cancelled")


def event_workflows(rt: Runtime) -> list[dict[str, Any]]:
    return rt.event_workflows if rt.event_workflows is not None else EVENT_WORKFLOWS


def handler_ids(rt: Runtime) -> dict[str, str]:
    """Each event to the id of the workflow that handles it."""
    return handlers(event_workflows(rt))


# Who publishes a shipped version, and the events a shipped change is recorded as (c-288).
SEED = "seed"
# Who published the seed's own versions: "seed", and "system" from 0a7ea469 (10-18), when these were platform-owned
# system workflows. A tenant provisioned then still runs the seed's version and follows the seed like any other.
SEED_AUTHORS = frozenset({SEED, "system"})
SOURCE = "agents"
UPDATED = "system_workflow.updated"
UPDATE_AVAILABLE = "system_workflow.update_available"


async def ensure_event_workflows(rt: Runtime) -> None:
    """Publishes each shipped event workflow the current tenant does not have yet, live and owned by no team, once per
    process. One the tenant has is never replaced: a person may have published a new version through review. An id a
    team already holds is logged and skipped, so the other events are still handled and this one is recorded
    unhandled rather than failing every time."""
    tenant = current_tenant()
    store = definitions(rt)
    for item in event_workflows(rt):
        d = parse(item)
        if (tenant, d.id) in rt.event_workflows_seen:
            continue
        if checks := validate(d, default_registry()):
            raise ValueError(f"Event workflow {d.id} does not pass its checks: {checks}")
        versions = await store.versions(d.id)
        if not versions:
            try:
                version, _ = await store.publish(
                    d.id, name=d.name or d.id, definition=d.wire(), digest=d.digest(), now=now_iso(), by=SEED
                )
            except WorkflowOwnedError as e:
                log.warning("event_workflow_id_taken", workflow=d.id, error=str(e))
                continue
            await store.go_live(d.id, version)
        elif d.digest() not in {v["digest"] for v in versions}:
            await _follow_seed(rt, store, d)
        rt.event_workflows_seen.add((tenant, d.id))


async def _follow_seed(rt: Runtime, store: DefinitionStore, d: WorkflowDefinition) -> None:
    """A shipped event workflow changed in the seed file (c-288): a tenant still running the seed's own version gets
    the new one as a publish request its publishReview decides, live at once only where no review is needed; one whose
    live version a person published keeps it and is told an update exists. Either is recorded once per shipped digest
    as a service event."""
    live = await store.current(d.id)
    events = ServiceEvents(rt.db)
    key = f"{d.id}:{d.digest()[:16]}"
    if live is not None and live["created_by"] in SEED_AUTHORS:
        # Saved as a draft and published through the same request a person's publish opens, so the workspace's
        # publishReview decides it now: live at once where no review is needed, otherwise waiting in Reviews.
        version, _ = await store.publish(
            d.id, name=d.name or d.id, definition=d.wire(), digest=d.digest(), now=now_iso(), by=SEED
        )
        row = await store.get(d.id, version)
        if row is None:
            return
        req = await open_publish(rt, d.id, row, live, by=SEED, team="", note="An update to a shipped workflow")
        await events.record(
            name=UPDATED,
            key=key,
            team_id="",
            source=SOURCE,
            actor=None,
            payload={"workflowId": d.id, "version": version, "reviewId": req["id"], "status": req["status"]},
        )
        log.info("event_workflow_updated", workflow=d.id, version=version, status=req["status"])
        return
    await events.record(
        name=UPDATE_AVAILABLE,
        key=key,
        team_id="",
        source=SOURCE,
        actor=None,
        payload={"workflowId": d.id, "liveVersion": live["version"] if live else None},
    )


# Which service reports which events (the catalogue in docs/architecture/service-map.md): a service reports only events
# about its own records, so one holding events:emit cannot start another service's reactions.
EVENT_OWNERS: dict[str, tuple[str, ...]] = {
    "tools": ("tool_access.", "tool_module.", "module_review."),
    "files": ("file.",),
    "documents": ("extraction.",),
    # The task API (c-288) records a posted task as its own event, so the task runs as the api_task workflow.
    "agents": ("task.",),
}


REMINDER = "task.reminder"


def reminders(db: AsyncEngine) -> Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]:
    """The worker's `remind` (c-277): a review still waiting is reported as this service's task.reminder event, keyed
    by run, step, iteration and count, so a retried pass records it once. What follows is the handler the tenant runs
    for it; none is shipped, so it is recorded unhandled until a team adds one."""
    handler = handlers(EVENT_WORKFLOWS).get(REMINDER)

    async def remind(run: dict[str, Any], reminder: dict[str, Any]) -> None:
        await deliver(
            db,
            handler,
            name=REMINDER,
            key=f"{run['id']}:{reminder['node']}:{reminder['iteration']}:{reminder['n']}",
            team_id=str(run.get("team_id") or ""),
            source=SOURCE,
            actor=None,
            payload={"runId": run["id"], "workflowId": run["workflow_id"]} | reminder,
        )

    return remind


def owns(source: str, name: str) -> bool:
    return name.startswith(EVENT_OWNERS.get(source, ()))


def starter(source: str, name: str, actor: str | None) -> tuple[str, str | None]:
    """A run's (created_by, started_via). An event that is someone's request starts their run: created_by is their
    email, so who may decide or cancel it reads them, and started_via names the event. Otherwise the event itself."""
    event = f"event:{source}/{name}"
    return (actor, event) if actor else (event, None)


async def emit(
    rt: Runtime,
    *,
    name: str,
    key: str,
    team_id: str,
    source: str,
    actor: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Records the event and starts or returns its handler's run. Returns the event row."""
    await ensure_event_workflows(rt)
    return await deliver(
        rt.db,
        handler_ids(rt).get(name),
        name=name,
        key=key,
        team_id=team_id,
        source=source,
        actor=actor,
        payload=payload,
    )


async def deliver(
    db: AsyncEngine,
    handler: str | None,
    *,
    name: str,
    key: str,
    team_id: str,
    source: str,
    actor: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """`emit` without first publishing the shipped event workflows, for the engine worker, which has no Runtime: a
    tenant gets them on its first event through the API, and until then the event is recorded unhandled."""
    events = ServiceEvents(db)
    event = await events.record(name=name, key=key, team_id=team_id, source=source, actor=actor, payload=payload)
    # The stored event is what runs: a repeat with another payload or team cannot change what an earlier one meant.
    run_key = f"{name}:{key}"
    runs = RunStore(EngineTransactions(db))
    run_ids: list[str] = []
    attempts = 0
    for stored in await listeners(db, name, handler) if handler else []:
        tried = await attempts_of(db, stored["workflow_id"], run_key)
        if tried and tried[-1]["status"] not in FAILED:
            run_ids.append(str(tried[-1]["id"]))
            attempts = max(attempts, len(tried))
            continue
        n = len(tried) + 1
        created_by, via = starter(str(event["source"]), name, cast(str | None, event["actor"]))
        run, _ = await start_run(
            runs,
            stored,
            team_id=str(event["team_id"]),
            mode="live",
            input=cast(dict[str, Any], event["payload"]),
            run_key=run_key if n == 1 else f"{run_key}:{n}",
            created_by=created_by,
            started_via=via,
        )
        run_ids.append(str(run["id"]))
        attempts = max(attempts, n)
    status = "started" if run_ids else "unhandled"
    if not run_ids:
        log.warning("service_event_unhandled", event_name=name, key=key, source=source)
    await events.started(str(event["id"]), status=status, run_ids=run_ids, attempts=attempts)
    return event | {"status": status, "run_ids": run_ids, "attempts": attempts}
