"""Run again on a set-aside email (c-561), through the route, by failure mode: the email cannot be run at all, so its
mail is lost to the workflow; someone who may not start the workflow, or another team, runs it; it runs twice; and its
kept copy stays held after it ran."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.email_trigger import kept, run_key
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvent, TriggerEvents
from ops_email import InboundMessage
from tests.api.test_action_roles import OTHER_REVIEWER, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER
from tests.engine.test_run_starts import TEAM, Files, files_client, live_intake

Stack = tuple[AsyncClient, AsyncEngine]
NOTICE = InboundMessage(
    key="notice-7@court.example",
    sender="registry@court.example",
    subject="Garnishment notice",
    body="Please hold the account.",
    received_at="2026-10-29T09:00:00Z",
)


async def set_aside(engine: AsyncEngine, workflow_id: str) -> str:
    events = TriggerEvents(engine)
    with tenant_scope(TENANT):
        await events.add(
            TriggerEvent(
                team_id=TEAM,
                workflow_id=workflow_id,
                source="email:levy@bank.example",
                event_key=run_key(NOTICE.fingerprint),
                sender=NOTICE.sender,
                subject=NOTICE.subject,
                received_at=NOTICE.received_at,
                outcome="set_aside",
                detail={"reason": "RuntimeError: boom", "message": "This email was set aside after 3 failed reads"},
                item=kept(NOTICE),
            )
        )
        rows, _ = await events.page(workflow_id, team_id=TEAM, page=1, page_size=5)
    return str(rows[0]["id"])


async def test_run_again_starts_a_set_aside_email_once_for_whoever_may_start_the_workflow(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    rt: Any = c._transport.app.state.runtime  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportPrivateUsage, reportUnknownMemberType]
    rt.start_files = files_client(Files())
    row = await live_intake(engine, TENANT)
    event_id = await set_aside(engine, str(row["workflow_id"]))
    url = f"/v1/runs/set-aside-emails/{event_id}/run"
    assert (await c.post(url, headers=VIEWER)).status_code == 403
    assert (await c.post(url, headers=OTHER_REVIEWER)).status_code == 404, "another team's email is not found"
    r = await c.post(url, headers=BUILDER)
    assert r.status_code == 202, r.text
    run = (await c.get(f"/v1/runs/{r.json()['data']['runId']}", headers=BUILDER)).json()["data"]
    assert run["input"]["subject"] == NOTICE.subject and run["startedBy"]["kind"] == "person", run
    again = await c.post(url, headers=BUILDER)
    assert again.status_code == 404, "it ran, and its kept copy is gone"
