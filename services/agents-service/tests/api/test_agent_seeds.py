"""A seed's change to an agent (a pinned guardrail or skill) never steps over a draft a person saved, and outside
dev it waits for review instead of publishing (c-063, review pass 3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_agents.api import guardrails

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]

BRANCH = "ag_branch"


def _seed(tmp_path: Path) -> Path:
    path = tmp_path / "guardrails.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "gr_seeded",
                    "name": "No investment advice",
                    "kind": "blocked_topics",
                    "owner": "Compliance",
                    "topics": ["investment advice"],
                    "message": "I can't give investment advice.",
                    "pinnedBy": [BRANCH],
                }
            ]
        )
    )
    return path


async def _load(c: object, path: Path) -> None:
    app = cast(Any, c)._transport.app
    await guardrails.load_seed(app.state.runtime, path)


async def test_a_seed_keeps_a_draft_a_person_saved(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        draft = _ok(await c.patch(f"/v1/agents/{BRANCH}", json={"role": "Answers branch staff, edited by Lee"}))
        await _load(c, _seed(tmp_path))
        after = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        assert (after["version"], after["role"], after["guardrailPins"]) == (draft["version"], draft["role"], [])


async def test_outside_dev_a_seed_opens_a_review_instead_of_publishing(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), registry_auto_approve=False) as c:
        before = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        await _load(c, _seed(tmp_path))
        after = _ok(await c.get(f"/v1/agents/{BRANCH}"))
        assert after["publishedVersion"] == before["publishedVersion"], "nothing published past review"
        assert after["version"] == before["version"] + 1 and after["guardrailPins"][0]["guardrailId"] == "gr_seeded"
        app = cast(Any, c)._transport.app
        assert app.state.runtime.catalog.agent(BRANCH).guardrails == []
