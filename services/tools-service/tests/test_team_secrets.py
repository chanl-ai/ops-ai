"""A team's secrets are its own (c-186, owner 2026-10-17), by failure mode: a builder refused a secret for their own
team's tools, a builder writing another team's secret or a workspace-wide one, a builder changing the egress list, and
the `securityTeamAddsSecrets` policy not moving those writes back to the Security team."""

from __future__ import annotations

from typing import Any

import httpx

from ops_policy import mint

from .test_provisioned_records import tools  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
from .test_review_decisions import PLATFORM


def builder(tenant: str, team: str, policies: dict[str, Any] | None = None) -> dict[str, str]:
    claims = {
        "sub": "usr_jordan",
        "email": "jordan@bank.example",
        "name": "Jordan Hale",
        "kind": "person",
        "aud": ["tools"],
        "tenant_id": tenant,
        "team_ids": [team],
        "roles": {team: "builder"},
        "auth_method": "session",
        **({"policies": policies} if policies else {}),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=3600)}", "X-Team-Id": team}


def _secret(name: str, teams: list[str] | None) -> dict[str, Any]:
    return {"name": name, "value": "k1", **({"teams": teams} if teams is not None else {})}


async def test_a_builder_adds_rotates_and_removes_their_own_teams_secret(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, _ = tools
    me = builder(tenant, "team_platform")
    made = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY", ["team_platform"]), headers=me)
    assert made.status_code == 201, made.text
    rotated = await c.post("/v1/secrets/PLATFORM_KEY/rotate", json={"value": "k2"}, headers=me)
    assert rotated.status_code == 200 and rotated.json()["data"]["version"] == 2, rotated.text
    assert (await c.delete("/v1/secrets/PLATFORM_KEY", headers=me)).status_code == 204


async def test_a_builder_writes_no_other_teams_secret_nor_a_workspace_one_nor_egress(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    me = builder(tenant, "team_platform")
    other = await c.post("/v1/secrets", json=_secret("FRAUD_KEY", ["team_fraud"]), headers=me)
    assert other.status_code == 403, other.text
    workspace = await c.post("/v1/secrets", json=_secret("BANK_KEY", None), headers=me)
    assert workspace.status_code == 403, workspace.text
    _ = await c.post("/v1/secrets", json=_secret("FRAUD_KEY", ["team_fraud"]), headers=people["sam"])
    assert (await c.delete("/v1/secrets/FRAUD_KEY", headers=me)).status_code == 403
    assert (await c.post("/v1/egress/hosts", json={"value": "ledger.example.com"}, headers=me)).status_code == 403


async def test_the_security_team_adds_secrets_when_the_policy_says_so(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    me = builder(tenant, "team_platform", {"securityTeamAddsSecrets": True})
    refused = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY", ["team_platform"]), headers=me)
    assert refused.status_code == 403, refused.text
    added = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY", ["team_platform"]), headers=people["sam"])
    assert added.status_code == 201, added.text
