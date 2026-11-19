# Standards: events, the relay and workers

Status: target state. Part of the [engineering standards](../engineering-standards.md); ids `EV1` to `EV6` are frozen.
The design is in [durability, failure and audit](../durability-failure-and-audit.md) and the
[workflow runner](../workflow-runner.md).

A change and the event that announces it commit together; one relay delivers every service's events; every receiver
tolerates a repeat; every loop reports its health and works one tenant at a time.

## EV1 The event commits with the change

Rule: a cross-service event is written to the service's outbox table with `ops_store.outbox.add(conn, ...)` on the same
connection, inside the same transaction, as the change it announces.
Why: an event sent after the commit is lost when the process dies between the two; an event sent before it announces a
change that may roll back.

Today: no breach among the outboxes read.

Pattern (`services/documents-service/src/ops_documents/store/extractions.py:416`):

```python
await add(c, service_outbox, **event, now=now, due_at=now + CORRECTION_SETTLE_SECONDS)
```

Check: `packages/ops_store/tests/test_outbox.py`.

## EV2 One relay, wired once

Rule: `ops_store.outbox.Relay` is the one delivery mechanism, and the per-service wiring (which subscriber each event
goes to, the loop that runs the relay) is one kit function that takes the subscriber map; a service never copies the
wiring.
Why: a fix to the wiring lands in one place; five copies drift the first time one is fixed.

Today (`services/documents-service/src/ops_documents/store/event_relay.py`, `files-service`, `kb-service`,
`platform-service`, `tools-service`): five near-identical files (38 to 52 lines each) define `sender()` and
`keep_relaying()` around the same `Relay`.

```python
await Relay(engine, service_outbox, sender(agents, kb), role=SYSTEM_ROLE).run(asyncio.Event(), key="documents_relay", store=background.LOCAL)
```

Pattern (`packages/ops_store/src/ops_store/outbox.py:115`): `Relay` itself, which takes the table, the send function and
the role, is the one owner of delivery, retry and backoff.

Check: `packages/ops_store/tests/test_relay_sites.py` fails on a `Relay(` built outside `ops_store.outbox`; the five
files are listed under `packages/ops_store/tests/relay_sites/` until each service calls `ops_store.outbox.relay()`.

## EV3 A receiver tolerates a repeat

Rule: every event, inbox item and write carries a key the receiver dedupes on, and a redelivery returns the first
outcome.
Why: the relay delivers at least once; a repeat must do nothing the second time.

Today: no known breach.

Pattern (`services/agents-service/src/ops_agents/api/channels/inbox.py:28`): the docstring states the contract.

```python
async def deliver(rt, thread_id, *, key, kind, payload) -> tuple[Outcome, int]:
    """Adds the message to the thread's inbox once (a redelivery returns the first outcome)."""
```

Check: `packages/ops_store/tests/test_outbox.py`; use cases for repeated writes.

## EV4 Every loop reports its health

Rule: every background loop runs under a heartbeat key and reports through `/health/background` in the kit's shape; a
loop that fails stops reporting healthy.
Why: a stuck sweeper, relay or poller is invisible without it, and the Background page is what an operator reads.

Today: no per-loop test that a failure turns the report unhealthy.

Pattern (`services/documents-service/src/ops_documents/store/event_relay.py:41` and
`packages/ops_store/src/ops_store/background.py:274`): the relay runs with a `key` and a heartbeat store.

```python
.run(asyncio.Event(), key="documents_relay", store=background.LOCAL)
```

Check: `packages/ops_service_kit/src/ops_service_kit/background.py` defines the shape;
`services/agents-service/src/ops_agents/api/routers/background.py` reads it.
`packages/ops_store/tests/test_loop_health.py` fails on a process with no `ops_store.testing.loop_reports_failure`
test in its service; the 20 with none today are listed under `packages/ops_store/tests/loop_health/`.

## EV5 Workers claim with the dialect and lease what they hold

Rule: a worker takes work with `ops_store.dialect.claim` (skip-locked on PostgreSQL, the equivalent on SQL Server) and
holds a lease while it works; two workers never take the same row.
Why: at-least-once delivery with two workers means duplicate work unless the claim is atomic.

Today: no breach.

Pattern (`packages/ops_store/src/ops_store/outbox.py:138`):

```python
due = claim(due, t)
```

Check: `uv run python scripts/check_portable_store.py --strict` (claim and lock only through the dialect);
`packages/ops_store/tests/test_outbox.py`.

## EV6 A worker enters one tenant per item

Rule: a loop that reads across tenants runs under `tenant_wide(reason)` or `system_tx(reason)` to find work, then
enters each item's tenant and team with `isolation.scope` before acting on it.
Why: what the work writes (a run, an audit entry) must carry the item's tenant, and two items from different tenants
worked by one sweep must never see each other.

Today: no breach; every widening is listed by reason.

Pattern (`packages/ops_store/src/ops_store/outbox.py:145`):

```python
with isolation.scope(str(row["tenant_id"]), str(row["team_id"])):
    await self.send(wire(row))
```

Check: `packages/ops_store/tests/test_isolation_sites.py`.
