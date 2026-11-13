"""Case types through `/v1/case-types` for a caller with no acting team."""

from __future__ import annotations

from httpx import AsyncClient

from .role_app import ok


async def test_dev_header_caller_reads_the_case_types_of_the_team_it_names(client: AsyncClient) -> None:
    """The dev header caller reads tenant-wide, yet a case type belongs to one team: its X-Team-Id names the team
    whose seeded case types it lists and opens."""
    team = {"X-Team-Id": "team_all", "X-Dev-User": "lee@harborpine.example"}
    listed = ok(await client.get("/v1/case-types", headers=team))
    assert "complaint" in {t["id"] for t in listed}
    assert ok(await client.get("/v1/case-types/complaint", headers=team))["id"] == "complaint"
