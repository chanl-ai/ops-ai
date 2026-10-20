"""A builder switches a pinned guardrail off on the agent version, so a test can run without it, by failure
mode: the switch not saved on a new version, an off guardrail still checked (a classification call and its cost),
a run that looks protected by a guardrail that was off, and a caller turning one off."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ops_agents.api.deps import Runtime
from ops_agents.store.events import thread_events

from ..conftest import SEED
from .test_agent_registry import _app  # pyright: ignore[reportPrivateUsage]

DEV_AGENTS = SEED.parents[2] / "seed" / "chat_agents.json"
ADVISOR = "ag_advisor"


def runtime(c: AsyncClient) -> Runtime:
    transport = cast(ASGITransport, c._transport)  # pyright: ignore[reportPrivateUsage]
    return cast(Runtime, cast(FastAPI, transport.app).state.runtime)


async def advisor(c: AsyncClient) -> dict[str, Any]:
    return (await c.get(f"/v1/agents/{ADVISOR}")).json()["data"]


async def test_switching_a_guardrail_off_saves_a_version_and_stops_its_checks(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), agents_seed_file=DEV_AGENTS) as c:
        # The seeded advisor's always-on skill checks its own guardrail on every turn; detached, the switched pin is
        # the agent's only guardrail.
        assert (await c.delete(f"/v1/agents/{ADVISOR}/skills/sk_hardship_triage")).status_code == 200
        detached = (await advisor(c))["version"]
        assert (await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": detached})).status_code == 201
        before = await advisor(c)
        [pin] = before["guardrailPins"]
        assert pin["enabled"] is True
        off = {"guardrailId": pin["guardrailId"], "version": pin["version"], "enabled": False}
        saved = (await c.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": [off], "note": "test"})).json()["data"]
        assert saved["version"] == before["version"] + 1 and saved["guardrailPins"][0]["enabled"] is False, saved
        versions = (await c.get(f"/v1/agents/{ADVISOR}/versions")).json()["data"]
        assert "Changed guardrail pins" in versions[0]["changes"]
        review = (await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": saved["version"]})).json()
        body = review["data"]["agentPublish"]
        # The reviewer sees the switch: the pin with enabled false, and the change named.
        assert body["guardrailPins"] == [{**{k: pin[k] for k in ("guardrailId", "version", "name")}, "enabled": False}]
        assert f"Switched {pin['name']} v{pin['version']} off" in body["changes"], body["changes"]
        rt = runtime(c)
        served = rt.catalog.agent(ADVISOR)
        assert served is not None
        settings = rt.catalog.settings_for(served, rt.settings.model_alias)
        assert (settings.guardrails, [g.guardrail_id for g in settings.guardrails_off]) == ([], [pin["guardrailId"]])

        # The run journal says the turn was not protected by it.
        thread = (await c.post("/chat/threads", json={"agentId": ADVISOR, "kbIds": []})).json()["data"]
        await c.post(f"/chat/threads/{thread['id']}/messages", json={"content": "What is the fee for a wire?"})
        async with rt.db.connect() as conn:
            rows = await conn.execute(thread_events.select().where(thread_events.c.thread_id == thread["id"]))
            turns = [r.data for r in rows.all() if r.type == "turn"]
        assert turns and turns[-1]["guardrails"] == {
            "checked": [],
            "off": [{"guardrailId": pin["guardrailId"], "version": pin["version"], "name": pin["name"]}],
        }, turns

        on = {**off, "enabled": True}
        back = (await c.patch(f"/v1/agents/{ADVISOR}", json={"guardrailPins": [on]})).json()["data"]
        assert back["guardrailPins"][0]["enabled"] is True


async def test_a_caller_cannot_switch_a_guardrail_off_for_a_chat(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), agents_seed_file=DEV_AGENTS) as c:
        r = await c.post("/chat/threads", json={"agentId": ADVISOR, "kbIds": [], "guardrails": []})
        assert r.status_code == 400, "the thread routes take no guardrail field; a caller has no switch"
