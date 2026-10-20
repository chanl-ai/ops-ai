"""tools-service reads a workspace's own security team from platform-service (tick 36), by failure mode: the read made
at the wrong route or key, so every tenant reads as unknown and its platform tools are never written; the team of
another workspace; and a failed read taken for a team. platform-service is a fake HTTP endpoint here; its own tests
cover the route (87c159a0)."""

from __future__ import annotations

import httpx

from ops_tools.modules.policy import WorkspaceTeams

from .service_clients import claims, fake_service

TEAMS = {"t_a": "team_infosec", "t_b": "team_security"}


def _platform(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/v1/settings/workspace-teams":
        return httpx.Response(404)
    seen = claims(request)
    if "settings:view" not in seen.get("scopes", []):
        return httpx.Response(403, json={"success": False, "error": {"code": "scope_required"}})
    team = TEAMS[str(seen["tenant_id"])]
    return httpx.Response(200, json={"success": True, "data": {"securityTeam": team, "defaultTeam": None}})


async def test_each_workspace_reads_its_own_security_team() -> None:
    teams = WorkspaceTeams(fake_service(_platform, "platform", ["settings:view"]))
    assert await teams.security_team("t_a") == "team_infosec"
    assert await teams.security_team("t_b") == "team_security"


async def test_a_failed_read_is_no_team() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert await WorkspaceTeams(fake_service(down, "platform", ["settings:view"])).security_team("t_a") is None
