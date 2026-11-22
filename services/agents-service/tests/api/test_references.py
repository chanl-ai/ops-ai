"""What a builder can mention with @, by failure mode: the picker listing another team's record or answering a
person who may not edit; an insert on an agent granting nothing, granting twice, or granting across teams."""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.api.routers import references as route
from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_route_pins import client  # pyright: ignore[reportPrivateUsage]

__all__ = ["client"]

AGENT = "ag_fraud"
RECALL: dict[str, Any] = {
    "name": "Wire recall steps",
    "useWhen": "A customer asks to recall a wire.",
    "instructions": "Confirm the wire, then ask the payments desk to recall it.",
    "ownerTeam": "Retail",
}
LATER = "insert"


async def _skill(c: AsyncClient, name: str, who: dict[str, str], *, publish: bool = True) -> str:
    made = await c.post("/v1/skills", json={**RECALL, "name": name}, headers=who)
    assert made.status_code == 201, made.text
    sid = str(made.json()["data"]["id"])
    if publish:
        asked = await c.post(f"/v1/skills/{sid}/publish-requests", json={}, headers=who)
        assert asked.status_code == 201, asked.text
    return sid


def _listed(r: Any) -> dict[str, str]:
    """Every item a references reply lists, as `kind:id` to its label."""
    assert r.status_code == 200, r.text
    groups = cast(list[dict[str, Any]], r.json()["data"]["groups"])
    return {f"{g['kind']}:{i['id']}": i["label"] for g in groups for i in g["items"]}


@pytest.mark.parametrize("half", ["search", LATER])
async def test_references_stay_inside_the_team_and_an_insert_grants_once(
    client: AsyncClient, half: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = client
    ours = await _skill(c, "Wire recall steps", BUILDER)
    draft = await _skill(c, "Wire recall follow-up", BUILDER, publish=False)
    theirs = await _skill(c, "Wire recall for fraud", OUTSIDER)

    if half == "search":
        asked = {"forSkill": draft, "search": "wire recall"}
        found = _listed(await c.get("/v1/references", params=asked, headers=BUILDER))
        assert found.get(f"skill:{ours}") == "Wire recall steps", found
        assert f"skill:{theirs}" not in found, "another team's skill is never listed"
        for_agent = _listed(
            await c.get("/v1/references", params={"forAgent": AGENT, "search": "lookup"}, headers=BUILDER)
        )
        assert any(k.startswith("tool:lookup") for k in for_agent), for_agent

        neither = await c.get("/v1/references", params={"search": "wire"}, headers=BUILDER)
        both = await c.get("/v1/references", params={**asked, "forAgent": AGENT}, headers=BUILDER)
        assert (neither.status_code, both.status_code) == (400, 400), (neither.text, both.text)
        # Searching is for people who may edit; a viewer still gets the names of what a saved text already mentions.
        refused = await c.get("/v1/references", params=asked, headers=VIEWER)
        assert (refused.status_code, refused.json()["error"]["code"]) == (403, "forbidden"), refused.text
        named = {"forSkill": draft, "ids": [f"skill:{ours}", f"skill:{theirs}"]}
        assert _listed(await c.get("/v1/references", params=named, headers=VIEWER)) == {
            f"skill:{ours}": "Wire recall steps"
        }
        return

    url = f"/v1/agents/{AGENT}/references"
    before = (await c.get(f"/v1/agents/{AGENT}", headers=BUILDER)).json()["data"]["version"]
    added = await c.post(url, json={"kind": "skill", "id": ours}, headers=BUILDER)
    assert added.status_code == 200, added.text
    granted = added.json()["data"]
    assert [(i["kind"], i["id"]) for i in granted["added"]] == [("skill", ours)] and granted["agentVersion"] > before
    pins = (await c.get(f"/v1/agents/{AGENT}/skills", headers=BUILDER)).json()["data"]["pins"]
    assert [p["skillId"] for p in pins] == [ours], "the insert pinned the skill on a new draft version"
    again = await c.post(url, json={"kind": "skill", "id": ours}, headers=BUILDER)
    assert (again.status_code, again.json()["data"]["added"]) == (200, []), again.text

    other_team = await c.post(url, json={"kind": "skill", "id": theirs}, headers=BUILDER)
    assert (other_team.status_code, other_team.json()["error"]["code"]) == (422, "unknown_reference"), other_team.text
    unpublished = await c.post(url, json={"kind": "skill", "id": draft}, headers=BUILDER)
    assert (unpublished.status_code, unpublished.json()["error"]["code"]) == (422, "not_published"), unpublished.text
    viewer = await c.post(url, json={"kind": "tool", "id": "lookup_account"}, headers=VIEWER)
    assert viewer.status_code == 403, viewer.text

    # A save that lands while the insert asks another service is not written over: the insert is refused.
    emptied = await c.patch(f"/v1/agents/{AGENT}", json={"collections": []}, headers=BUILDER)
    assert emptied.status_code == 200, emptied.text
    asks = getattr(route, "check_knowledge")  # noqa: B009  imported there under this name, not exported

    async def saved_meanwhile(*args: Any, **more: Any) -> Any:
        renamed = await c.patch(f"/v1/agents/{AGENT}", json={"name": "Renamed meanwhile"}, headers=BUILDER)
        assert renamed.status_code == 200, renamed.text
        return await asks(*args, **more)

    monkeypatch.setattr(route, "check_knowledge", saved_meanwhile)
    raced = await c.post(url, json={"kind": "knowledge", "id": "kb_people"}, headers=BUILDER)
    assert (raced.status_code, raced.json().get("error", {}).get("code")) == (409, "stale_base"), raced.text
    kept = (await c.get(f"/v1/agents/{AGENT}", headers=BUILDER)).json()["data"]
    assert kept["name"] == "Renamed meanwhile" and "kb_people" not in kept["collections"], kept
