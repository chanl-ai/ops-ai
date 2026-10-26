"""A held write is decided in its run's team (c-509 US2), through the real routes with the tokens platform-service
mints, by failure mode: tools-service still naming another approving team (an operation saved with `approverTeam`
before c-509) sends the write to a team that cannot see the run, so nobody can decide it; and a person of another team
with reviews.decide reaches it. tools-service's answer is faked at the client, as rt.tools returns it."""

from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient

from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    drafted,
    person,
)


class _StaleTools:
    """tools-service answering for an operation whose policy still names Security as its approving team."""

    async def tool_policy(self, tool: str) -> dict[str, Any]:
        return {"name": tool, "access": "write", "approval": {"approvers": 1, "approverTeam": "team_security"}}

    async def tool_access(self, _tool: str) -> str:
        return "write"


async def test_the_runs_team_decides_whatever_team_tools_service_names(dev_platform: AsyncClient) -> None:  # noqa: F811
    c = dev_platform
    # The app behind the fixture's client: its runtime asks tools-service through `tools`.
    app = cast(Any, c._transport).app  # pyright: ignore[reportPrivateUsage]
    app.state.runtime.tools = _StaleTools()
    james = person("usr_james", ["team_ops"])
    url = await drafted(c, james)
    thread = url.split("/chat/threads/")[1].split("/")[0]
    sam = person("usr_sam", ["team_security"])
    assert (await c.get(f"/reviews/{thread}", headers=sam)).status_code == 404
    theirs = await c.post(url, json={"type": "approve"}, headers=sam)
    assert theirs.status_code == 404 and "team_ops" not in theirs.text, theirs.text
    review = await c.get(f"/reviews/{thread}", headers=james)
    assert review.status_code == 200 and review.json()["data"]["decidingTeam"]["id"] == "team_ops", review.text
    maya = person("usr_maya", ["team_ops"])
    decided = await c.post(url, json={"type": "approve"}, headers=maya)
    assert decided.status_code == 200, decided.text
