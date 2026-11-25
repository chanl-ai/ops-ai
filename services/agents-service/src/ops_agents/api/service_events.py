"""Service events start workflows: services never call each other to act. A service reports a named event with
a key (`POST /v1/events`), and the tenant's handler for it runs, on the event's team, with the event's payload as its
input. The handler is the tenant's no-team workflow under the id `seed/event_workflows.json` gives the event, at its
live version; it is an ordinary workflow, edited and published through review.

The run key is `<event>:<key>`, so a repeat delivery returns the run it started; a repeat after that run failed starts
the next attempt (`<event>:<key>:2`, `:3`). An event nobody handles is recorded `unhandled`, never dropped. The shipped
event workflows are published to a tenant when its first event arrives, so every tenant has them without a migration
per tenant; one the tenant already has, edited or not, is left as it is."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TypedDict, cast

from ops_engine import default_registry
from ops_engine.definition import WorkflowDefinition, parse, validate
from ops_engine.store import DefinitionStore, RunRow, RunStore, WorkflowOwnedError
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger
from ops_store import background

from ..store.background import BackgroundJobs, heartbeats
from ..store.engine import AsyncEngine, EngineTransactions
from ..store.service_events import ServiceEvents, attempts_of, listeners
from ..store.tenancy import current_tenant
from .deps import Runtime
from .engine_lifecycle import definitions, open_publish
from .engine_resume import wake_parked
from .engine_runs import start_run
from .event_workflows import EVENT_WORKFLOWS, handlers

log = get_logger("ops_agents.service_events")

FAILED = ("failed", "cancelled")


class DeliveredEvent(TypedDict):
    """The event's stored row with the latest delivery's outcome: the columns in their order, then the runs woken."""

    id: str
    tenant_id: str
    team_id: str
    name: str
    event_key: str
    source: str
    actor: str | None
    payload: JsonValue
    status: str
    run_ids: JsonList
    attempts: int
    recorded_at: str
    updated_at: str
    woke: list[str]


def event_workflows(rt: Runtime) -> list[Json]:
    return rt.event_workflows if rt.event_workflows is not None else EVENT_WORKFLOWS


def handler_ids(rt: Runtime) -> dict[str, str]:
    """Each event to the id of the workflow that handles it."""
    return handlers(event_workflows(rt))


# Who publishes a shipped version, and the events a shipped change is recorded as.
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
        elif d.digest() not in {v.digest for v in versions}:
            await _follow_seed(rt, store, d)
        rt.event_workflows_seen.add((tenant, d.id))


async def _follow_seed(rt: Runtime, store: DefinitionStore, d: WorkflowDefinition) -> None:
    """A shipped event workflow changed in the seed file: a tenant still running the seed's own version gets
    the new one as a publish request its publishReview decides, live at once only where no review is needed; one whose
    live version a person published keeps it and is told an update exists. Either is recorded once per shipped digest
    as a service event."""
    live = await store.serving(d.id)
    events = ServiceEvents(rt.db)
    key = f"{d.id}:{d.digest()[:16]}"
    if live is not None and live.created_by in SEED_AUTHORS:
        # Saved as a draft and published through the same request a person's publish opens, so the workspace's
        # publishReview decides it now: live at once where no review is needed, otherwise waiting in Reviews.
        version, _ = await store.publish(
            d.id, name=d.name or d.id, definition=d.wire(), digest=d.digest(), now=now_iso(), by=SEED
        )
        row = await store.row(d.id, version)
        if row is None:
            return
        req = await open_publish(rt, d.id, row, live, by=SEED, team="", note="An update to a shipped workflow")
        await events.record(
            name=UPDATED,
            key=key,
            team_id="",
            source=SOURCE,
            actor=None,
            payload={"workflowId": d.id, "version": version, "reviewId": req.id, "status": req.status},
        )
        log.info("event_workflow_updated", workflow=d.id, version=version, status=req.status)
        return
    await events.record(
        name=UPDATE_AVAILABLE,
        key=key,
        team_id="",
        source=SOURCE,
        actor=None,
        payload={"workflowId": d.id, "liveVersion": live.version if live else None},
    )


# Which service reports which events (the catalogue in docs/architecture/service-map.md): a service reports only events
# about its own records, so one holding events:emit cannot start another service's reactions.
EVENT_OWNERS: dict[str, tuple[str, ...]] = {
    # tool.module.* and tool.team_state.changed also keep this service's copy of the catalogue (store/tool_copies.py).
    "tools": ("tool_access.", "tool_module.", "module_review.", "app_account.", "tool.module.", "tool.team_state."),
    # watch.checked: a watched folder's check ended; the Files changed trigger reads its events after it.
    "files": ("file.", "watch."),
    "documents": ("extraction.",),
    "kb": ("kb.", "knowledge."),
    # The task API records a posted task as its own event, so the task runs as the api_task workflow.
    "agents": ("task.",),
}


REMINDER = "task.reminder"


def reminders(db: AsyncEngine) -> Callable[[RunRow, Json], Awaitable[None]]:
    """The worker's `remind`: a review still waiting is reported as this service's task.reminder event, keyed
    by run, step, iteration and count, so a retried pass records it once. What follows is the handler the tenant runs
    for it; none is shipped, so it is recorded unhandled until a team adds one."""
    handler = handlers(EVENT_WORKFLOWS).get(REMINDER)

    async def remind(run: RunRow, reminder: Json) -> None:
        await deliver(
            db,
            handler,
            name=REMINDER,
            key=f"{run.id}:{reminder['node']}:{reminder['iteration']}:{reminder['n']}",
            team_id=run.team_id,
            source=SOURCE,
            actor=None,
            payload={"runId": run.id, "workflowId": run.workflow_id} | reminder,
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
    payload: Json,
) -> DeliveredEvent:
    """Records the event and starts or returns its handler's run. Returns the event row. A payload holding infinity
    or not-a-number (a JSON body's 1e999) is refused before anything is written: the event's JSON column cannot store
    it, for a reported event and a posted task alike."""
    try:
        json.dumps(payload, allow_nan=False)
    except ValueError as e:
        raise Unprocessable(
            "An event's payload holds a number that is too large or is not a number.", code="payload_not_finite"
        ) from e
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


_beats: dict[int, background.Beat] = {}


def event_beat(db: AsyncEngine) -> background.Beat:
    """The event workflows' heartbeat in this process: one per database, as the API and worker both deliver."""
    if id(db) not in _beats:
        _beats[id(db)] = background.Beat("event_workflows", heartbeats(db))
    return _beats[id(db)]


class DeliveryFailedError(RuntimeError):
    """What the shared heartbeat records of a failed delivery: the kind of error alone."""


async def deliver(
    db: AsyncEngine,
    handler: str | None,
    *,
    name: str,
    key: str,
    team_id: str,
    source: str,
    actor: str | None,
    payload: Json,
) -> DeliveredEvent:
    """`emit` without first publishing the shipped event workflows, for the engine worker, which has no Runtime: a
    tenant gets them on its first event through the API, and until then the event is recorded unhandled."""
    try:
        out = await _deliver(
            db, handler, name=name, key=key, team_id=team_id, source=source, actor=actor, payload=payload
        )
    except Exception as e:
        # The heartbeat is one row for every tenant, read by each tenant's account admins, so it carries the kind of
        # error and never its message, which can quote a tenant's records. The event's team reads the failure as its
        # own failed job; the message is in this service's log and the caller's error.
        log.warning("event_delivery_failed", name=name, key=key, error=type(e).__name__)
        if team_id:
            await BackgroundJobs(db).record(
                "event_workflows", f"Could not deliver the event {name}: {type(e).__name__}", "failed", team_id=team_id
            )
        await event_beat(db).failed(DeliveryFailedError(type(e).__name__))
        raise
    # A payload a listener's schema refused is likewise the event's team's failed job (`_deliver`), never this line.
    await event_beat(db).ok(len(out["run_ids"]))
    return out


async def _deliver(
    db: AsyncEngine,
    handler: str | None,
    *,
    name: str,
    key: str,
    team_id: str,
    source: str,
    actor: str | None,
    payload: Json,
) -> DeliveredEvent:
    events = ServiceEvents(db)
    jobs = BackgroundJobs(db)
    event = await events.record(name=name, key=key, team_id=team_id, source=source, actor=actor, payload=payload)
    # A step parked on this event and key resumes before any listener starts: the run it belongs to is waiting.
    # `at` from this delivery, not the stored row: a repeat of a key returns the first row, and a person's later
    # sign-in repeats the key of their first.
    at = payload.get("at")
    woken = await wake_parked(
        db, name=name, key=key, team_id=str(event.team_id), payload=cast(Json, event.payload), at=at
    )
    # The stored event is what runs: a repeat with another payload or team cannot change what an earlier one meant.
    run_key = f"{name}:{key}"
    runs = RunStore(EngineTransactions(db))
    run_ids: list[str] = []
    attempts = 0
    for stored in await listeners(db, name, handler) if handler else []:
        tried = await attempts_of(db, stored.workflow_id, run_key)
        if tried and tried[-1]["status"] not in FAILED:
            run_ids.append(str(tried[-1]["id"]))
            attempts = max(attempts, len(tried))
            continue
        n = len(tried) + 1
        created_by, via = starter(str(event.source), name, event.actor)
        title = stored.name or stored.workflow_id
        try:
            run, _ = await start_run(
                runs,
                stored,
                team_id=str(event.team_id),
                mode="live",
                input=cast(Json, event.payload),
                run_key=run_key if n == 1 else f"{run_key}:{n}",
                created_by=created_by,
                started_via=via,
            )
        except Unprocessable as e:
            # The payload does not match this listener's input schema: it starts no run, the other listeners still
            # hear the event, and the event's team reads which workflow and field as a failed job, in its Activity and
            # on its own account admins' Background page. The message can quote the value sent, so it is kept out of
            # the log and the job. Every caller names a team (the events route, a posted task, a run's reminder).
            field = str((e.details or {}).get("path") or "its input")
            log.warning("event_input_refused", workflow=stored.workflow_id, name=name, key=key, field=field)
            if event.team_id:
                await jobs.record(
                    "event_workflows",
                    f"Did not run {title}: the event's {field} does not match its input schema",
                    "failed",
                    team_id=str(event.team_id),
                )
            continue
        run_ids.append(run.id)
        attempts = max(attempts, n)
        # An account-level notice has no team, so no team's Activity shows it; the Background page counts it.
        if event.team_id:
            await jobs.record(
                "event_workflows",
                f"Ran {title}",
                "done",
                team_id=str(event.team_id),
            )
    status = "started" if run_ids else "resumed" if woken else "unhandled"
    if not run_ids and not woken:
        log.warning("service_event_unhandled", event_name=name, key=key, source=source)
    await events.started(str(event.id), status=status, run_ids=run_ids, attempts=attempts)
    return DeliveredEvent(
        id=event.id,
        tenant_id=event.tenant_id,
        team_id=event.team_id,
        name=event.name,
        event_key=event.event_key,
        source=event.source,
        actor=event.actor,
        payload=event.payload,
        status=status,
        run_ids=[*run_ids],
        attempts=attempts,
        recorded_at=event.recorded_at,
        updated_at=event.updated_at,
        woke=woken,
    )
