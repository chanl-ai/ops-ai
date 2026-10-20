"""tools-service reads the team's publish-review mode live from platform-service (c-214), by failure mode: the mode
read for the wrong team, a change that waits on a cache, the read made with someone else's credentials, and a failed
read letting a version go live. platform-service is a fake HTTP endpoint here; its own tests cover the route."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ops_tools.modules.policy import PublishPolicy, ToolsMode

from .service_clients import claims, fake_service

# What the fake platform-service holds: team_ops set Tools to never, every other team has the default.
STORED: dict[str, object] = {"team_ops": {"tools": "never"}}


def _platform(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/v1/policies/publishReview":
        return httpx.Response(404)
    if claims(request)["tenant_id"] != "t_a":
        return httpx.Response(401, json={"success": False, "error": {"code": "unauthorized"}})
    return httpx.Response(200, json={"success": True, "data": {"key": "publishReview", "value": STORED}})


def _policy(handler: Callable[[httpx.Request], httpx.Response] = _platform) -> PublishPolicy:
    return PublishPolicy(fake_service(handler, "platform", ["settings:view"]))


async def test_reads_the_mode_of_the_team_deciding() -> None:
    policy = _policy()
    assert await policy.mode("t_a", "team_ops") == ToolsMode("never")
    assert await policy.mode("t_a", "team_fraud") == ToolsMode("major"), "a team that set nothing has the default"


async def test_a_change_applies_at_the_next_decision() -> None:
    reads: list[str] = []

    def counted(request: httpx.Request) -> httpx.Response:
        reads.append(request.url.path)
        return _platform(request)

    policy = _policy(counted)
    assert await policy.mode("t_a", "team_ops") == ToolsMode("never")
    STORED["team_ops"] = {"tools": "always"}
    try:
        assert await policy.mode("t_a", "team_ops") == ToolsMode("always"), "read live, never cached"
    finally:
        STORED["team_ops"] = {"tools": "never"}
    assert len(reads) == 2


async def test_reads_with_this_services_token_for_the_tenant() -> None:
    assert await _policy().mode("t_b", "team_ops") == ToolsMode("always", unreadable=True), "t_b's token is refused"


async def test_an_unreachable_platform_reads_as_always() -> None:
    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert await _policy(down).mode("t_a", "team_ops") == ToolsMode("always", unreadable=True)
