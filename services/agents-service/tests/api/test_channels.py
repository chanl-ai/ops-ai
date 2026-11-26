"""GET /v1/channels, by failure mode, through the app with platform tokens: another team's channel lists; a
mailbox no one has read for minutes shows green; a pinned chat channel hides that newer versions exist; the gallery
loses the types not built yet, or a page for one of them fails to load."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from ops_agents.store.agent_registry import registry_agents
from ops_agents.store.api_key_copies import ApiKeyCopies, KeySummary, api_key_copies, listed_event
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.poll_cursors import poll_cursors
from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.widget_deployments import WidgetDeployments
from ops_engine.store import DefinitionStore, RunStore
from ops_identity import dev_service_signer, mint_service_token
from ops_store import copies
from ops_store.outbox import ApiKeyChanged
from ops_store.schedule import Rule
from ops_store.schedule.wall_time import DAYS
from tests.api.test_action_roles import REVIEWER
from tests.api.test_activity import email
from tests.api.test_case_routes import started_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER, person
from tests.run_rows import write_run

from .connections import Request, connections
from .test_reply_pins import FIXTURES, answer, compare

FRAUD_BUILDER = person("omar", "team_fraud", "builder")
SEEDED: dict[str, Any] = {
    w["id"]: w for w in json.loads((Path(__file__).parents[2] / "seed" / "engine_workflows.json").read_text())
}


async def channels(c: AsyncClient, who: dict[str, str], **params: Any) -> dict[str, Any]:
    r = await c.get("/v1/channels", params=params, headers=who)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def mailbox(s: Stack, address: str, team: str = "team_ops") -> None:
    _, rt = s
    with tenant_scope(TENANT):
        await MailboxStore(rt.db).create(
            MailboxRow(
                id=f"mbx_{address.split('@', maxsplit=1)[0]}",
                team_id=team,
                name=f"Mail {address}",
                address=address,
                provider="imap",
                created_by="b",
                created_at="n",
                updated_at="n",
            )
        )


async def watch(c: AsyncClient, address: str) -> str:
    """mail_intake published by team_ops, its trigger rewritten to watch `address`."""
    d = {k: v for k, v in SEEDED["mail_intake"].items() if k != "teamId"}
    d["id"] = workflow = f"intake_{address.split('@', maxsplit=1)[0]}"
    for n in d["nodes"]:
        if n["type"] == "ops.trigger.email":
            n["parameters"]["mailbox"] = address
    assert (await c.post("/v1/workflows/definitions", json={"definition": d}, headers=BUILDER)).status_code == 201
    live = await c.post(f"/v1/workflows/definitions/{workflow}/publish-requests", json={}, headers=BUILDER)
    assert live.status_code == 201, live.text
    return workflow


async def read_at(s: Stack, workflow: str, at: str) -> None:
    _, rt = s
    async with rt.db.begin() as conn:
        await conn.execute(
            poll_cursors.insert().values(
                tenant_id=TENANT, binding_id=f"email:{workflow}", source="x", folder="inbox", cursor="c", updated_at=at
            )
        )


async def test_a_team_sees_its_own_channels_only(stack: Stack) -> None:  # noqa: F811
    # Each type in another team of the tenant, and in the same team of another tenant: none of them lists.
    c, rt = stack
    await mailbox(stack, "ops@bank.example")
    await mailbox(stack, "fraud@bank.example", team="team_fraud")
    await give_keys(stack, [key("key_ops"), key("key_fraud", team="team_fraud")])
    with tenant_scope(TENANT):
        await WidgetDeployments(rt.db).add({**OTHER_EMBED, "id": "wd_fraud", "team_id": "team_fraud"})
    other = "t-elsewhere"
    with tenant_scope(other):
        await MailboxStore(rt.db).create(OTHER_BOX)
        await WidgetDeployments(rt.db).add({**OTHER_EMBED, "id": "wd_elsewhere"})
        copies = ApiKeyCopies(rt.db)
        await copies.reconcile(
            [listed_event(KeySummary.model_validate(key("key_elsewhere")), tenant_id=other)], await copies.held()
        )
    ours = await channels(c, BUILDER, team="all")
    assert [r["id"] for r in ours["data"]] == ["mbx_ops", "key_ops"] and ours["data"][0]["canEdit"] is True
    assert ours["pagination"]["total"] == 2 and ours["facets"]["type"] == {"email": 1, "api": 1}
    theirs = await channels(c, FRAUD_BUILDER)
    assert [r["id"] for r in theirs["data"]] == ["mbx_fraud", "wd_fraud", "key_fraud"]


OTHER_BOX = MailboxRow(
    id="mbx_elsewhere",
    team_id="team_ops",
    name="Elsewhere",
    address="ops@elsewhere.example",
    provider="imap",
    created_by="b",
    created_at="n",
    updated_at="n",
)
OTHER_EMBED: dict[str, Any] = {
    "team_id": "team_ops",
    "name": "Elsewhere help",
    "agent_id": "ag_branch",
    "agent_version": None,
    "origins": ["https://elsewhere.example"],
    "created_by": "b",
    "created_at": "n",
    "updated_at": "n",
}


async def test_an_email_channel_is_green_only_while_it_is_read(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    for box in ("fresh", "stale", "idle"):
        await mailbox(stack, f"{box}@bank.example")
    fresh, stale = await watch(c, "fresh@bank.example"), await watch(c, "stale@bank.example")
    await read_at(stack, fresh, "2999-01-01T00:00:00.000Z")
    await read_at(stack, stale, "2020-01-01T00:00:00.000Z")
    await email(stack, "started", subject="Notice")  # to levy@, not a channel here: counts nothing below
    rows = {r["id"]: r for r in (await channels(c, BUILDER))["data"]}
    assert rows["mbx_fresh"]["health"]["state"] == "ok"
    assert rows["mbx_stale"]["health"]["state"] == "warn" and "Not read for" in rows["mbx_stale"]["health"]["reason"]
    assert rows["mbx_idle"]["health"]["state"] == "idle"
    assert rows["mbx_fresh"]["serves"]["id"] == fresh and rows["mbx_fresh"]["servesCount"] == 1
    warned = await channels(c, BUILDER, health="warn")
    assert [r["id"] for r in warned["data"]] == ["mbx_stale"]
    assert warned["facets"]["health"] == {"ok": 1, "warn": 1, "idle": 1}


async def test_a_pinned_chat_channel_says_how_far_behind_it_is(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    published = 3  # two versions published since the widget pinned version 1
    async with rt.db.begin() as conn:
        await conn.execute(
            registry_agents.update().where(registry_agents.c.id == "ag_branch").values(published_version=published)
        )
    with tenant_scope(TENANT):
        await WidgetDeployments(rt.db).add(
            {
                "id": "wd_pinned",
                "team_id": "team_ops",
                "name": "Intranet help",
                "agent_id": "ag_branch",
                "agent_version": 1,
                "origins": ["https://intranet.example"],
                "created_by": "b",
                "created_at": "n",
                "updated_at": "n",
            }
        )
    [row] = (await channels(c, BUILDER, type="chat"))["data"]
    serves = row["serves"]
    assert (serves["version"], serves["latestVersion"], serves["behind"]) == (1, published, published - 1), serves
    assert (row["detail"], row["health"]["state"]) == ("https://intranet.example", "ok")


async def test_the_gallery_lists_every_type_built_or_not(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    kinds = {k["type"]: k for k in (await channels(c, BUILDER))["kinds"]}
    assert [t for t, k in kinds.items() if not k["built"]] == ["slack", "teams"]
    assert kinds["email"]["total"] == 0 and kinds["email"]["health"] is None


async def test_a_kind_not_built_yet_lists_nothing_instead_of_failing(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    for kind in ("slack", "teams"):
        page = await channels(c, BUILDER, type=kind)
        found = next(k for k in page["kinds"] if k["type"] == kind)
        assert (page["data"], found["built"]) == ([], False), (kind, page)


async def test_an_agents_live_places_are_its_channels_and_the_steps_that_run_it(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    with tenant_scope(TENANT):
        await WidgetDeployments(rt.db).add(
            {
                "id": "wd_branch",
                "team_id": "team_ops",
                "name": "Advisor desk",
                "agent_id": "ag_branch",
                "agent_version": 1,
                "origins": ["https://intranet.example"],
                "created_by": "b",
                "created_at": "n",
                "updated_at": "n",
            }
        )
    d = {k: v for k, v in SEEDED["customer_summary"].items() if k != "teamId"}
    for n in d["nodes"]:
        if n["type"] == "ops.ai.agent":
            n["parameters"]["agent"] = "ag_branch"
        if str(n["type"]).startswith("ops.trigger."):
            n["type"], n["parameters"] = "ops.trigger.schedule", {}
    assert (await c.post("/v1/workflows/definitions", json={"definition": d}, headers=BUILDER)).status_code == 201
    live = await c.post("/v1/workflows/definitions/customer_summary/publish-requests", json={}, headers=BUILDER)
    assert live.status_code == 201, live.text
    r = await c.get("/v1/agents/ag_branch/live", headers=BUILDER)
    assert r.status_code == 200, r.text
    places = {(p["where"]["kind"], p["where"]["id"]): p for p in r.json()["data"]["rows"]}
    assert set(places) == {("channel", "wd_branch"), ("workflow_step", "summarise")}, places
    assert places[("channel", "wd_branch")]["pinned"] is True
    assert places[("workflow_step", "summarise")]["where"]["workflowId"] == "customer_summary"
    assert places[("workflow_step", "summarise")]["schedule"] is None
    trigger = next(n["id"] for n in d["nodes"] if str(n["type"]).startswith("ops.trigger."))
    rule: Rule = {"kind": "every", "every": 15, "unit": "minutes", "start": "00:00", "tz": "UTC", "days": list(DAYS)}
    with tenant_scope(TENANT):
        await WorkflowSchedules(rt.db).save("customer_summary", trigger, "team_ops", rule, "user_ana")
    again = (await c.get("/v1/agents/ag_branch/live", headers=BUILDER)).json()["data"]["rows"]
    step = next(p for p in again if p["where"]["kind"] == "workflow_step")
    assert step["schedule"]["words"] == "Every 15 minutes from 00:00, UTC", step
    assert step["schedule"]["triggerStep"] == trigger
    assert datetime.fromisoformat(step["schedule"]["nextRun"]) > datetime.now(UTC)
    assert next(p for p in again if p["where"]["kind"] == "channel")["schedule"] is None
    # Another team's workflow runs the same agent on a schedule: neither its step nor its schedule is listed.
    theirs = {**d, "id": "fraud_summary", "name": "Fraud summary"}
    digest = hashlib.sha256(json.dumps(theirs, sort_keys=True).encode()).hexdigest()
    with tenant_scope(TENANT):
        store = DefinitionStore(EngineTransactions(rt.db))
        version, _ = await store.publish(
            "fraud_summary", name="Fraud summary", definition=theirs, digest=digest, now="n", by="b", team="team_fraud"
        )
        await store.go_live("fraud_summary", version)
        await WorkflowSchedules(rt.db).save("fraud_summary", trigger, "team_fraud", rule, "user_omar")
    both = (await c.get("/v1/agents/ag_branch/live", headers=BUILDER)).json()["data"]["rows"]
    steps = {p["where"]["workflowId"]: p["schedule"] for p in both if p["where"]["kind"] == "workflow_step"}
    assert steps["customer_summary"] is not None and "fraud_summary" not in steps, steps
    assert (await c.get("/v1/workflows/fraud_summary/live", headers=BUILDER)).status_code == 404
    assert (await c.get("/v1/agents/ag_nobody/live", headers=BUILDER)).status_code == 404


async def test_a_workflows_live_places_are_the_mailboxes_it_watches(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await mailbox(stack, "desk@bank.example")
    workflow = await watch(c, "desk@bank.example")
    r = await c.get(f"/v1/workflows/{workflow}/live", headers=BUILDER)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert [p["where"]["id"] for p in data["rows"]] == ["mbx_desk"] and data["rows"][0]["version"] == "latest"
    assert (await c.get(f"/v1/workflows/{workflow}/live", headers=FRAUD_BUILDER)).status_code == 404


async def widget(s: Stack, wid: str = "wd_branch", version: int | None = 1) -> None:
    _, rt = s
    async with rt.db.begin() as conn:
        await conn.execute(
            registry_agents.update().where(registry_agents.c.id == "ag_branch").values(published_version=3)
        )
    with tenant_scope(TENANT):
        await WidgetDeployments(rt.db).add(
            {
                "id": wid,
                "team_id": "team_ops",
                "name": "Intranet help",
                "agent_id": "ag_branch",
                "agent_version": version,
                "origins": ["https://intranet.example"],
                "created_by": "b",
                "created_at": "n",
                "updated_at": "n",
            }
        )


class AlwaysReview:
    """The team's publishReview setting as platform-service answers it: every agents change waits."""

    async def value(self, key: str) -> Any:
        return {"team_ops": {"agents": "always"}} if key == "publishReview" else None


async def test_a_chat_channel_moves_to_latest_and_stops_falling_behind(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await widget(stack)
    body = {"serves": {"kind": "agent", "id": "ag_branch", "version": "latest"}}
    r = await c.patch("/v1/channels/wd_branch", json=body, headers=BUILDER)
    assert r.status_code == 200, r.text
    serves = r.json()["data"]["serves"]
    assert (serves["version"], serves["latestVersion"], serves["behind"]) == ("latest", 3, 0), serves


async def test_a_serves_change_waits_when_the_team_reviews_every_change(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await widget(stack)
    rt.policies = AlwaysReview()
    body = {"serves": {"kind": "agent", "id": "ag_branch", "version": 3}}
    r = await c.patch("/v1/channels/wd_branch", json=body, headers=BUILDER)
    assert r.status_code == 202 and r.json()["data"]["reviewId"], r.text
    [row] = (await channels(c, BUILDER, type="chat"))["data"]
    assert row["serves"]["version"] == 1, "the channel keeps serving its pin until the review is approved"


async def test_only_a_builder_of_the_team_changes_a_channel(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await widget(stack)
    await mailbox(stack, "ops@bank.example")
    assert (await c.patch("/v1/channels/wd_branch", json={"paused": True}, headers=FRAUD_BUILDER)).status_code == 404
    assert (await c.patch("/v1/channels/wd_branch", json={"paused": True}, headers=VIEWER)).status_code == 403
    paused = await c.patch("/v1/channels/mbx_ops", json={"paused": True}, headers=BUILDER)
    assert paused.status_code == 200 and paused.json()["data"]["health"]["state"] == "idle", paused.text
    serves = {"serves": {"kind": "workflow", "id": "x", "version": "latest"}}
    refused = await c.patch("/v1/channels/mbx_ops", json=serves, headers=BUILDER)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "serves_from_workflow"


async def test_latest_chosen_through_a_review_stays_latest_when_approved(stack: Stack) -> None:  # noqa: F811
    # An approved "Latest" was written as the version it meant then, so the channel fell behind at the next publish.
    c, rt = stack
    await widget(stack)
    rt.policies = AlwaysReview()
    body = {"serves": {"kind": "agent", "id": "ag_branch", "version": "latest"}}
    asked = await c.patch("/v1/channels/wd_branch", json=body, headers=BUILDER)
    assert asked.status_code == 202, asked.text
    review = asked.json()["data"]["reviewId"]
    decided = await c.post(f"/reviews/{review}/decision", json={"decision": "approved"}, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    [row] = (await channels(c, BUILDER, type="chat"))["data"]
    assert row["serves"]["version"] == "latest", row["serves"]


def key(kid: str, *, team: str = "team_ops", status: str = "active", **more: Any) -> dict[str, Any]:
    row = {"id": kid, "name": f"Key {kid}", "prefix": kid, "teamId": team, "status": status, "target": None}
    return row | {"lastUsedAt": None, "expiresAt": None, "createdAt": "2026-10-01T00:00:00.000Z"} | more


async def test_an_api_key_is_a_channel_with_its_traffic_and_health(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await mailbox(stack, "api@bank.example")
    workflow = await watch(c, "api@bank.example")
    soon = (datetime.now(UTC) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    await give_keys(
        stack,
        [
            key("key_ci", target={"kind": "workflow", "id": workflow, "version": None}),
            key("key_soon", expiresAt=soon),
            key("key_gone", status="disabled"),
            key("key_rev", status="revoked"),
            key("key_fraud", team="team_fraud"),
        ],
    )
    parent = await started_run(c, BUILDER, "ops_check")
    tx = EngineTransactions(rt.db)
    with tenant_scope(TENANT):
        base = await RunStore(tx).get(parent)
        assert base is not None
        same = {k: base[k] for k in ("team_id", "workflow_id", "version", "digest", "mode", "input")}
        await write_run(tx, same | {"id": "wfrun_bykey", "run_key": "kk", "created_by": "key:key_ci"})
    rows = {r["id"]: r for r in (await channels(c, BUILDER, type="api"))["data"]}
    assert set(rows) == {"key_ci", "key_soon", "key_gone"}, rows
    ci = rows["key_ci"]
    assert (ci["serves"]["id"], ci["serves"]["version"], ci["traffic24h"], ci["health"]["state"]) == (
        workflow,
        "latest",
        1,
        "ok",
    ), ci
    assert rows["key_soon"]["health"]["state"] == "warn" and "Expires in" in rows["key_soon"]["health"]["reason"]
    assert rows["key_gone"]["health"]["state"] == "error" and not ci["canEdit"]
    patched = await c.patch("/v1/channels/key_ci", json={"paused": True}, headers=BUILDER)
    assert (patched.status_code, patched.json()["error"]["code"]) == (409, "channel_managed_elsewhere")


async def test_a_chat_channel_is_renamed_its_websites_wait_for_review_and_it_retires(stack: Stack) -> None:  # noqa: F811
    # One API for a chat channel: the edits the old widget-deployment PATCH made are made here.
    c, rt = stack
    await widget(stack)
    renamed = await c.patch("/v1/channels/wd_branch", json={"name": "Branch help"}, headers=BUILDER)
    assert renamed.status_code == 200 and renamed.json()["data"]["name"] == "Branch help", renamed.text
    rt.policies = AlwaysReview()
    sites = await c.patch("/v1/channels/wd_branch", json={"origins": ["https://new.example"]}, headers=BUILDER)
    assert sites.status_code == 202 and sites.json()["data"]["reviewId"], sites.text
    [row] = (await channels(c, BUILDER, type="chat"))["data"]
    assert row["detail"] != "https://new.example", "the websites stay as they were until the review is approved"
    retired = await c.post("/v1/channels/wd_branch/retire", headers=BUILDER)
    again = await c.post("/v1/channels/wd_branch/retire", headers=BUILDER)
    assert retired.status_code == 200 and retired.json()["data"]["retiredAt"], retired.text
    assert (again.status_code, again.json()["error"]["code"]) == (409, "channel_retired"), again.text
    assert (await channels(c, BUILDER, type="chat"))["data"] == []


DEPLOYMENT = {"id": "dep_pin", "graph": "complex_workflow", "channel": "api"}
REPLY = {"kind": "customer_reply", "messageKey": "m1", "payload": {"text": "Yes, go ahead."}}


async def test_deployment_and_inbox_routes_keep_every_reply_and_error(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    made = await c.post("/v1/threads", json={"graph": "dispute_email"}, headers=BUILDER)
    tid = made.json()["data"]["threadId"]
    # James's own chat: Vera, in his team, may not read its channel messages, as she may not read the thread.
    chat = await c.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {"chat": True}}, headers=BUILDER)
    mine = chat.json()["data"]["threadId"]
    rows: list[tuple[str, str, str, dict[str, Any] | None, dict[str, str]]] = [
        ("dep.create", "POST", "/v1/deployments", DEPLOYMENT, BUILDER),
        ("dep.change", "POST", "/v1/deployments", {**DEPLOYMENT, "paused": True, "multitask": "reject"}, BUILDER),
        ("dep.unknownGraph", "POST", "/v1/deployments", {**DEPLOYMENT, "graph": "nowhere"}, BUILDER),
        ("dep.unknownField", "POST", "/v1/deployments", {**DEPLOYMENT, "colour": "red"}, BUILDER),
        ("dep.otherTeam", "POST", "/v1/deployments", DEPLOYMENT, FRAUD_BUILDER),
        ("dep.viewer", "POST", "/v1/deployments", {**DEPLOYMENT, "id": "dep_viewer"}, VIEWER),
        ("pause", "PATCH", "/v1/deployments/dep_pin", {"paused": False}, BUILDER),
        ("pause.missing", "PATCH", "/v1/deployments/dep_missing", {"paused": True}, BUILDER),
        ("pause.otherTeam", "PATCH", "/v1/deployments/dep_pin", {"paused": True}, FRAUD_BUILDER),
        ("inbox.post", "POST", f"/v1/threads/{tid}/inbox", REPLY, BUILDER),
        ("inbox.postAgain", "POST", f"/v1/threads/{tid}/inbox", REPLY, BUILDER),
        ("inbox.postMissing", "POST", "/v1/threads/th_missing1/inbox", REPLY, BUILDER),
        ("inbox.read", "GET", f"/v1/threads/{tid}/inbox", None, BUILDER),
        ("inbox.readOtherTeam", "GET", f"/v1/threads/{tid}/inbox", None, FRAUD_BUILDER),
        ("inbox.readMissing", "GET", "/v1/threads/th_missing1/inbox", None, BUILDER),
        ("inbox.readOwnChat", "GET", f"/v1/threads/{mine}/inbox", None, BUILDER),
        ("inbox.readTeammatesChat", "GET", f"/v1/threads/{mine}/inbox", None, VIEWER),
    ]
    seen = {name: answer(await c.request(m, path, json=body, headers=who)) for name, m, path, body, who in rows}
    compare(seen, FIXTURES / "reply-pins-deployments.json")


async def test_local_channel_routes_answer_in_one_transaction(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await widget(stack)
    made = await c.post("/v1/threads", json={"graph": "dispute_email"}, headers=BUILDER)
    tid = made.json()["data"]["threadId"]
    requests: list[Request] = [
        ("POST", "/v1/deployments", DEPLOYMENT, BUILDER),
        ("PATCH", "/v1/deployments/dep_pin", {"paused": True}, BUILDER),
        ("GET", f"/v1/threads/{tid}/inbox", None, BUILDER),
        ("POST", "/v1/channels/wd_branch/retire", None, BUILDER),
        ("POST", "/v1/threads", {"graph": "dispute_email"}, BUILDER),
    ]
    made = {"/v1/deployments", "/v1/threads"}
    expected = [(m, p, 201 if p in made else 200, 1) for m, p, _, _ in requests]
    assert await connections(c, requests) == expected


async def test_channel_list_routes_keep_every_reply_and_error(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await widget(stack)
    await mailbox(stack, "intake@bank.example")
    other_agent = {"serves": {"kind": "agent", "id": "ag_x", "version": 1}}
    a_workflow = {"serves": {"kind": "workflow", "id": "w", "version": 1}}
    rows: list[tuple[str, str, str, dict[str, Any] | None, dict[str, str]]] = [
        ("list", "GET", "/v1/channels", None, BUILDER),
        ("list.otherTeam", "GET", "/v1/channels", None, FRAUD_BUILDER),
        ("list.badType", "GET", "/v1/channels?type=fax", None, BUILDER),
        ("list.pastEnd", "GET", "/v1/channels?page=9&pageSize=1", None, BUILDER),
        ("create.unknownField", "POST", "/v1/channels", {"type": "chat", "agentId": "ag_branch", "x": 1}, BUILDER),
        ("rename", "PATCH", "/v1/channels/wd_branch", {"name": "Branch help"}, BUILDER),
        ("rename.unknownField", "PATCH", "/v1/channels/wd_branch", {"colour": "red"}, BUILDER),
        ("serves.otherAgent", "PATCH", "/v1/channels/wd_branch", other_agent, BUILDER),
        ("rename.otherTeam", "PATCH", "/v1/channels/wd_branch", {"name": "Theirs"}, FRAUD_BUILDER),
        ("mailbox.pause", "PATCH", "/v1/channels/mbx_intake", {"paused": True}, BUILDER),
        ("mailbox.serves", "PATCH", "/v1/channels/mbx_intake", a_workflow, BUILDER),
        ("key.change", "PATCH", "/v1/channels/key_ci", {"paused": True}, BUILDER),
        ("other.change", "PATCH", "/v1/channels/zz_1", {"paused": True}, BUILDER),
        ("agentLive", "GET", "/v1/agents/ag_branch/live", None, BUILDER),
        ("agentLive.missing", "GET", "/v1/agents/ag_missing/live", None, BUILDER),
        ("workflowLive.missing", "GET", "/v1/workflows/wf_missing/live", None, BUILDER),
        ("retire.mailbox", "POST", "/v1/channels/mbx_intake/retire", None, BUILDER),
        ("retire.otherTeam", "POST", "/v1/channels/wd_branch/retire", None, FRAUD_BUILDER),
        ("retire.viewer", "POST", "/v1/channels/wd_branch/retire", None, VIEWER),
        ("retire", "POST", "/v1/channels/wd_branch/retire", None, BUILDER),
        ("retire.again", "POST", "/v1/channels/wd_branch/retire", None, BUILDER),
        ("list.afterRetire", "GET", "/v1/channels?includeRetired=true", None, BUILDER),
    ]
    seen = {name: answer(await c.request(m, path, json=body, headers=who)) for name, m, path, body, who in rows}
    compare(seen, FIXTURES / "reply-pins-channel-list.json")


async def give_keys(s: Stack, keys: list[dict[str, Any]]) -> None:
    """platform-service's API keys as this service holds them: its copy, as a resync writes it."""
    _, rt = s
    with tenant_scope(TENANT):
        copies = ApiKeyCopies(rt.db)
        listed = [listed_event(KeySummary.model_validate(k), tenant_id=TENANT) for k in keys]
        await copies.reconcile(listed, await copies.held())


async def test_channel_list_pages_filters_and_counts_every_type(stack: Stack) -> None:  # noqa: F811
    """One list over mailboxes, embeds and API keys: its order, pages, filters, search, facets and kinds."""
    c, _ = stack
    await widget(stack)
    await mailbox(stack, "ops@bank.example")
    await mailbox(stack, "idle@bank.example")
    await mailbox(stack, "fraud@bank.example", team="team_fraud")
    flow = await watch(c, "ops@bank.example")
    await read_at(stack, flow, "2999-01-01T00:00:00.000Z")
    soon = (datetime.now(UTC) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    await give_keys(
        stack,
        [
            key("key_ci", name="Intranet help", target={"kind": "workflow", "id": flow, "version": None}),
            key("key_bot", target={"kind": "agent", "id": "ag_branch", "version": None}),
            key("key_soon", expiresAt=soon),
            key("key_gone", status="disabled"),
            key("key_rev", status="revoked"),
            key("key_fraud", team="team_fraud"),
        ],
    )
    rows: list[tuple[str, str, dict[str, str]]] = [
        ("list", "/v1/channels", BUILDER),
        ("page2", "/v1/channels?page=2&pageSize=2", BUILDER),
        ("pastEnd", "/v1/channels?type=api&page=5&pageSize=2", BUILDER),
        ("typeApi", "/v1/channels?type=api", BUILDER),
        ("typeEmailChat", "/v1/channels?type=email&type=chat", BUILDER),
        ("healthWarnError", "/v1/channels?health=warn&health=error", BUILDER),
        ("searchName", "/v1/channels?search=INTRANET", BUILDER),
        ("searchDetail", "/v1/channels?search=key_so", BUILDER),
        ("agent", "/v1/channels?agentId=ag_branch", BUILDER),
        ("teamAll", "/v1/channels?team=all", BUILDER),
        ("otherTeam", "/v1/channels", FRAUD_BUILDER),
        ("viewer", "/v1/channels", VIEWER),
    ]
    seen = {name: answer(await c.get(path, headers=who)) for name, path, who in rows}
    compare(seen, FIXTURES / "reply-pins-channel-pages.json")


async def test_an_api_key_event_from_platform_keeps_the_newest_state_in_its_own_tenant(stack: Stack) -> None:  # noqa: F811
    # As platform's relay sends it (`ops_store.outbox.add`): a repeat or an older revision changes nothing, a delete
    # buries the row, and the same key id in another tenant never touches this tenant's copy.
    c, rt = stack
    made = ApiKeyChanged(id="key_new", name="Billing sync", prefix="key_new", status="active", created_at="n")

    async def send(payload: ApiKeyChanged, revision: int, tenant: str = TENANT) -> None:
        body = {"name": "api_key.changed", "key": f"key_new@{revision}", "teamId": "team_ops"}
        body |= {"payload": payload.model_dump(by_alias=True, mode="json") | {"revision": revision}}
        token = mint_service_token(
            dev_service_signer(), service="platform", audience="agents", tenant_id=tenant, scopes=["agents:create"],
            team_id="team_ops",
        )  # fmt: skip
        r = await c.post("/v1/platform-events", json=body, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["data"]["handled"], r.text

    async def held(tenant: str) -> dict[str, tuple[int, bool, str]]:
        with tenant_scope(tenant):
            rows = await ApiKeyCopies(rt.db).held()
        status = [c.name for c in api_key_copies.c if c.name not in copies.OWN].index("status")
        return {k[-1]: (h.revision, h.deleted, h.values[status]) for k, h in rows.items()}

    await send(made, 1)
    assert [r["name"] for r in (await channels(c, BUILDER, type="api"))["data"]] == ["Billing sync"]
    await send(made.model_copy(update={"status": "revoked"}), 3)
    await send(made.model_copy(update={"name": "Renamed late"}), 2)
    await send(made, 1)
    assert (await channels(c, BUILDER, type="api"))["data"] == []
    await send(made.model_copy(update={"name": "Other tenant's key"}), 9, tenant="tenant_other")
    assert await held(TENANT) == {"key_new": (3, False, "revoked")}
    assert await held("tenant_other") == {"key_new": (9, False, "active")}
    await send(made.model_copy(update={"status": "revoked", "deleted": True}), 4)
    await send(made.model_copy(update={"status": "active"}), 4)
    assert await held(TENANT) == {"key_new": (4, True, "revoked")}
    assert await held("tenant_other") == {"key_new": (9, False, "active")}
