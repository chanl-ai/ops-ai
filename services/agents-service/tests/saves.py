"""Saves that name the copy they were made from: the agent and skill-draft routes refuse a body without it."""

from __future__ import annotations

from typing import Any

import httpx
from httpx import AsyncClient

Headers = dict[str, str] | None


async def save_agent(
    c: AsyncClient, agent_id: str, fields: dict[str, Any], *, headers: Headers = None, read_as: Headers = None
) -> httpx.Response:
    """The save names the copy it read: the agent is read as `read_as` (default `headers`), then PATCHed."""
    opened = (await c.get(f"/v1/agents/{agent_id}", headers=read_as or headers)).json()["data"]
    body = {"baseVersion": opened["version"], "baseDigest": opened["digest"], **fields}
    return await c.patch(f"/v1/agents/{agent_id}", json=body, headers=headers)


async def save_skill_draft(
    c: AsyncClient, skill_id: str, fields: dict[str, Any], *, headers: Headers = None, read_as: Headers = None
) -> httpx.Response:
    """The save names the copy it read: the skill is read as `read_as` (default `headers`), then its draft PUT."""
    opened = (await c.get(f"/v1/skills/{skill_id}", headers=read_as or headers)).json()["data"]
    body = {"baseVersion": opened["version"], "baseDigest": opened["digest"], **fields}
    return await c.put(f"/v1/skills/{skill_id}/draft", json=body, headers=headers)
