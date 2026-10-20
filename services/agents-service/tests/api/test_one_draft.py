"""Agent edits keep one draft and a version is cut only on publish (c-172), by failure mode: every save adds a
version (F1); a save after publish rewrites what runs (F2); a save while a publish request is open rewrites what the
reviewer approves (F3); a skill attach still cuts a version per save (F4); two saves at once open the next version
twice (F5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.tenancy import tenant_scope

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_skills import BRANCH, HARDSHIP, _published  # pyright: ignore[reportPrivateUsage]


async def _versions(c: AsyncClient, aid: str) -> dict[int, dict[str, Any]]:
    return {int(v["version"]): v for v in _ok(await c.get(f"/v1/agents/{aid}/versions"))}


async def _role(c: AsyncClient, aid: str, role: str) -> dict[str, Any]:
    return _ok(await c.patch(f"/v1/agents/{aid}", json={"role": role}))


async def test_saves_rewrite_one_draft_and_history_lists_it_once(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        made = _ok(await c.post("/v1/agents", json={"name": "Drafted", "role": "first"}), 201)
        await _role(c, made["id"], "second")
        after = await _role(c, made["id"], "third")
        assert (after["version"], after["role"]) == (1, "third"), after
        assert list(await _versions(c, made["id"])) == [1]


async def test_a_save_after_publish_opens_a_draft_and_leaves_the_published_version(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        made = _ok(await c.post("/v1/agents", json={"name": "Shipped", "role": "live"}), 201)
        published = _ok(await c.post(f"/v1/agents/{made['id']}/publish-requests", json={"version": 1}), 201)
        assert published["status"] == "approved", published
        live = (await _versions(c, made["id"]))[1]
        await _role(c, made["id"], "edit one")
        after = await _role(c, made["id"], "edit two")
        assert (after["version"], after["publishedVersion"]) == (2, 1), after
        history = await _versions(c, made["id"])
        assert list(history) == [2, 1] and history[1]["savedAt"] == live["savedAt"], history


async def test_a_save_while_a_publish_request_is_open_leaves_the_requested_version(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), registry_auto_approve=False) as c:
        made = _ok(await c.post("/v1/agents", json={"name": "Asked", "role": "asked"}), 201)
        review = _ok(await c.post(f"/v1/agents/{made['id']}/publish-requests", json={"version": 1}), 201)
        assert review["status"] == "pending", review
        asked = (await _versions(c, made["id"]))[1]
        after = await _role(c, made["id"], "changed while asked")
        assert after["version"] == 2, after
        assert (await _versions(c, made["id"]))[1]["savedAt"] == asked["savedAt"]


async def test_skill_attach_and_detach_rewrite_the_same_draft(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        before = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        skill = await _published(c, {**HARDSHIP, "name": "One draft"})
        _ok(await c.put(f"/v1/agents/{BRANCH}/skills/{skill['id']}", json={"version": 1}))
        _ok(await c.delete(f"/v1/agents/{BRANCH}/skills/{skill['id']}"))
        after = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        assert after["version"] == before["version"] + 1, (before["version"], after["version"])


async def test_two_saves_at_once_after_publish_leave_one_draft(database_url: str) -> None:
    """Two saves racing on a published agent (two tabs, or autosave behind a slow save) must take turns: both reading v1
    as the newest would open v2 twice, and the second would fail on the version key."""
    engine = create_async_engine(database_url)
    try:
        with tenant_scope(f"t-{uuid4().hex[:8]}"):
            reg = AgentRegistry(engine)
            aid = await reg.create(
                {"name": f"Raced {uuid4().hex[:6]}", "role": "live"}, by="a@x", team_id="team_ops", published=True
            )
            saved = await asyncio.gather(
                *(reg.save(aid, {"name": "Raced", "role": f"edit {i}"}, by="a@x") for i in range(4))
            )
            assert saved == [2, 2, 2, 2], saved
            assert [v["version"] for v in await reg.versions(aid)] == [2, 1]
    finally:
        await engine.dispose()
