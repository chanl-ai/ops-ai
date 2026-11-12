"""Who may use a team's skill text, by failure mode: a person whose role cannot view skills reading a skill's filled-in
text through render; a chat offering, or running, a skill another team owns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from ..conftest import sse_events
from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_chat_budget import who
from .test_write_approval_policy import dev_platform  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture

BRIEF: dict[str, Any] = {
    "name": "Client brief",
    "useWhen": "Before a client meeting.",
    "instructions": "Prepare a brief for {{client}}.",
    "ownerTeam": "Lending",
    "inputs": [{"name": "client", "required": True}],
}


async def _publish(c: AsyncClient, headers: dict[str, str]) -> str:
    s = _ok(await c.post("/v1/skills", json=BRIEF, headers=headers), 201)
    _ok(await c.post(f"/v1/skills/{s['id']}/publish-requests", json={"note": ""}, headers=headers), 201)
    return str(s["id"])


async def test_render_needs_skills_view_in_the_skills_team(dev_platform: AsyncClient) -> None:  # noqa: F811
    skill = await _publish(dev_platform, who("usr_admin", "admin"))
    body = {"inputs": {"client": "Okafor"}}
    r = await dev_platform.post(f"/v1/skills/{skill}/render", json=body, headers=who("usr_chat", "chat_user"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", r.text
    _ok(await dev_platform.post(f"/v1/skills/{skill}/render", json=body, headers=who("usr_view", "viewer")))


async def test_a_chat_neither_offers_nor_runs_another_teams_skill(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        lending, ops = {"X-Team-Id": "team_lending"}, {"X-Team-Id": "team_ops"}
        theirs = await _publish(c, lending)
        offered = _ok(await c.get("/v1/skills", params={"usableBy": "agent", "agentId": "ag_fraud"}, headers=ops))
        assert theirs not in [s["id"] for s in offered["data"]]

        made = _ok(await c.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=ops), 201)
        sent = await c.post(
            f"/chat/threads/{made['id']}/messages",
            json={"content": "Brief me", "skill": {"skillId": theirs, "inputs": {"client": "Okafor"}}},
            headers={**ops, "Accept": "text/event-stream"},
        )
        assert sent.status_code == 404, [e.get("type") for e in sse_events(sent.text)] if sent.is_success else sent.text
