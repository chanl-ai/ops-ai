"""Tools-service reads go through the one central check, by failure mode: a Chat user lists the team's tool modules,
egress hosts or secrets, which they hold no view right for."""

from __future__ import annotations

import httpx

from .test_review_decisions import person, signed_in  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

READS = ("/v1/tool-modules", "/v1/egress/hosts", "/v1/secrets")


async def test_a_chat_user_reads_no_tool_modules_egress_hosts_or_secrets(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = signed_in
    chat = person(tenant, "Cleo Chat", {"team_platform": "chat_user"})
    allowed = (await c.get(READS[0], headers=people["james"])).status_code
    refused = [(await c.get(path, headers=chat)).status_code for path in READS]
    assert allowed == 200, allowed
    assert refused == [403, 403, 403], refused
