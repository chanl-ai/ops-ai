"""Agent edits keep one draft and a version is cut only on publish, by failure mode: every save adds a
version (F1); a save after publish rewrites what runs (F2); a save while a publish request is open rewrites what the
reviewer approves (F3); a skill attach still cuts a version per save (F4); two saves at once open the next version
twice (F5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.tenancy import tenant_scope

from ..saves import save_agent
from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_skills import BRANCH, HARDSHIP, _published  # pyright: ignore[reportPrivateUsage]


async def _versions(c: AsyncClient, aid: str) -> dict[int, dict[str, Any]]:
    return {int(v["version"]): v for v in _ok(await c.get(f"/v1/agents/{aid}/versions"))}


async def _role(c: AsyncClient, aid: str, role: str) -> dict[str, Any]:
    return _ok(await save_agent(c, aid, {"role": role}))


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
            assert [v.version for v in await reg.versions(aid)] == [2, 1]
    finally:
        await engine.dispose()


async def test_an_agent_save_made_from_an_old_copy_or_naming_no_copy_is_refused(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        aid = _ok(await c.post("/v1/agents", json={"name": "Typed", "role": "first"}), 201)["id"]
        opened = _ok(await c.get(f"/v1/agents/{aid}"))
        base = {"baseVersion": opened["version"], "baseDigest": opened["digest"]}
        # The builder's @ insert lands after the page read the agent and before its autosave is sent.
        granted = _ok(await c.post(f"/v1/agents/{aid}/references", json={"kind": "tool", "id": "lookup_customer"}))
        assert [g["id"] for g in granted["added"]] == ["lookup_customer"], granted

        late = await c.patch(f"/v1/agents/{aid}", json={"role": "typed meanwhile", **base})
        assert (late.status_code, late.json()["error"]["code"]) == (409, "stale_base"), late.text
        assert set(late.json()["error"]["details"]) >= {"savedBy", "savedAt"}, late.text
        kept = _ok(await c.get(f"/v1/agents/{aid}"))
        assert (kept["toolIds"], kept["role"]) == (["lookup_customer"], "first"), kept

        unnamed = await c.patch(f"/v1/agents/{aid}", json={"role": "names no copy"})
        assert unnamed.status_code == 400 and "baseVersion" in unnamed.text, unnamed.text
        again = {"baseVersion": kept["version"], "baseDigest": kept["digest"]}
        saved = _ok(await c.patch(f"/v1/agents/{aid}", json={"role": "typed meanwhile", **again}))
        assert (saved["toolIds"], saved["role"]) == (["lookup_customer"], "typed meanwhile"), saved


async def test_a_save_landing_while_a_route_holds_its_read_is_never_written_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PATCH, an attach and a detach each read the agent, change that copy and save it. Another save landing between
    the read and the save must refuse the route's save (409), or the route writes its older copy over it. Attach and
    detach take no base from the caller, so the copy the route read is the only thing that can tell."""
    stored = AgentRegistry.save
    between: list[str] = []

    async def save(self: AgentRegistry, agent_id: str, spec: Any, **kw: Any) -> int:
        if between:
            # The other session's save, made after the route read the agent and before the route saves.
            newest = (await self.version(agent_id, (await self.row(agent_id)).version)).spec
            await stored(self, agent_id, {**newest, "role": between.pop()}, by="kim@x.example")
        return await stored(self, agent_id, spec, **kw)

    monkeypatch.setattr(AgentRegistry, "save", save)
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        pin = f"/v1/agents/{BRANCH}/skills/{s['id']}"
        opened = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        base = {"baseVersion": opened["version"], "baseDigest": opened["digest"]}
        between.append("saved during the patch")
        patched = await c.patch(f"/v1/agents/{BRANCH}", json={"name": "Renamed", **base})
        between.append("saved during the attach")
        attached = await c.put(pin, json={"version": 1})
        _ok(await c.put(pin, json={"version": 1}))
        between.append("saved during the detach")
        detached = await c.delete(pin)
        kept = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        still_pinned = await c.delete(pin)
    answers = [(r.status_code, r.json().get("error", {}).get("code")) for r in (patched, attached, detached)]
    assert answers == [(409, "stale_base")] * 3, [r.text[:200] for r in (patched, attached, detached)]
    # Each refused route wrote nothing: the name is as it was, and the pin the refused detach named is still there.
    assert (kept["name"], still_pinned.status_code) == (opened["name"], 200), (kept["name"], still_pinned.text[:200])
