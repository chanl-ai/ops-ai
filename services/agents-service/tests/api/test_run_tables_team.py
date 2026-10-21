"""Agent threads, runs, events and reviews are read inside the caller's team (c-429), through the real routes with the
tokens platform-service mints, by failure mode: another team's thread read by id through any of its routes answers
anything but 404; a thread list shows another team's threads; and an approver of the approving team reaches a review
while acting in a team other than the thread's. Each read is checked as the owning team first, so a 404 means the row
is hidden, not missing. The database's own hold on the five tables is tests/store/test_run_tables_isolation.py."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ops_agents.api import hitl_facade
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from tests.api.test_write_approval_policy import (
    PLATFORM,
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    drafted,
    person,
    policy,
)


def builder(sub: str, team: str) -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@northfield.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": [team],
        "roles": {team: "builder"},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


OWNER = builder("usr_james", "team_ops")
OUTSIDER = builder("usr_omar", "team_fraud")


async def _thread(c: AsyncClient) -> str:
    r = await c.post("/v1/threads", json={"graph": "simple_workflow", "metadata": {}}, headers=OWNER)
    assert r.status_code == 201, r.text
    tid = str(r.json()["data"]["threadId"])
    ran = await c.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"question": "hello"}}, headers=OWNER)
    assert ran.status_code == 200, ran.text
    return tid


async def test_another_teams_thread_answers_404_on_every_read_route(dev_platform: AsyncClient) -> None:  # noqa: F811
    c = dev_platform
    tid = await _thread(c)
    runs = (await c.get(f"/v1/threads/{tid}/runs", headers=OWNER)).json()["data"]
    assert runs, "the owner's run is listed"
    run_id = str(runs[0]["runId"] if "runId" in runs[0] else runs[0]["id"])
    for path in (
        f"/v1/threads/{tid}/state",
        f"/v1/threads/{tid}/runs",
        f"/v1/threads/{tid}/runs/{run_id}/events",
        f"/runs/{tid}",
    ):
        assert (await c.get(path, headers=OWNER)).status_code == 200, path
        seen = await c.get(path, headers=OUTSIDER)
        assert seen.status_code == 404, (path, seen.status_code, seen.text)
    listed = (await c.get("/v1/threads", headers=OUTSIDER)).json()["data"]
    assert tid not in [t["threadId"] for t in listed]


async def test_a_reviewer_reaches_a_review_only_acting_in_the_threads_team(
    dev_platform: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The approving team (Fraud) still decides the write; the reviewer acts in the thread's team (Operations) to do it,
    as before c-429, and from any other team the review is not found."""
    monkeypatch.setattr(hitl_facade, "policy_of", policy(approver_team="team_fraud"))
    c = dev_platform
    url = await drafted(c, person("usr_james", ["team_ops"]))
    thread = url.split("/chat/threads/")[1].split("/")[0]
    in_fraud = {**person("usr_nadia", ["team_ops", "team_fraud"]), "X-Team-Id": "team_fraud"}
    assert (await c.get(f"/reviews/{thread}", headers=in_fraud)).status_code == 404
    refused = await c.post(url, json={"type": "approve"}, headers=in_fraud)
    assert refused.status_code == 404, refused.text
    in_ops = person("usr_nadia", ["team_ops", "team_fraud"])
    assert (await c.get(f"/reviews/{thread}", headers=in_ops)).status_code == 200
    assert (await c.post(url, json={"type": "approve"}, headers=in_ops)).status_code == 200
