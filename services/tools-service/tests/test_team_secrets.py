"""A team's secrets are its own (c-186, owner 2026-10-17; one team per secret, c-509), by failure mode: a builder
refused a secret for their own team's tools, a builder reading or writing another team's secret, a caller still
limiting a secret to several teams, a builder changing the egress list, and the `securityTeamAddsSecrets` policy not
moving those writes back to the Security team."""

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


def _secret(name: str, team: str | None = None) -> dict[str, Any]:
    return {"name": name, "value": "k1", **({"teamId": team} if team else {})}


async def test_a_builder_adds_rotates_and_removes_their_own_teams_secret(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, _ = tools
    me = builder(tenant, "team_platform")
    made = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY"), headers=me)
    assert made.status_code == 201 and made.json()["data"]["teamId"] == "team_platform", made.text
    rotated = await c.post("/v1/secrets/PLATFORM_KEY/rotate", json={"value": "k2"}, headers=me)
    assert rotated.status_code == 200 and rotated.json()["data"]["version"] == 2, rotated.text
    assert (await c.delete("/v1/secrets/PLATFORM_KEY", headers=me)).status_code == 204


async def test_a_builder_reads_and_writes_no_other_teams_secret_nor_egress(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    me = builder(tenant, "team_platform")
    other = await c.post("/v1/secrets", json=_secret("FRAUD_KEY", "team_fraud"), headers=me)
    assert other.status_code == 404, other.text
    made = await c.post("/v1/secrets", json=_secret("FRAUD_KEY", "team_fraud"), headers=people["sam"])
    assert made.status_code == 201 and made.json()["data"]["teamId"] == "team_fraud", made.text
    assert (await c.get("/v1/secrets", params={"teamId": "team_fraud"}, headers=me)).status_code == 404
    assert "FRAUD_KEY" not in (await c.get("/v1/secrets", headers=me)).text
    assert (await c.delete("/v1/secrets/FRAUD_KEY", headers=me)).status_code == 404
    assert (await c.delete("/v1/secrets/FRAUD_KEY", params={"teamId": "team_fraud"}, headers=me)).status_code == 404
    assert (await c.post("/v1/egress/hosts", json={"value": "ledger.example.com"}, headers=me)).status_code == 403


async def test_two_teams_hold_the_same_name_and_a_caller_naming_several_teams_is_refused(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    for team in ("team_platform", "team_fraud"):
        made = await c.post("/v1/secrets", json=_secret("LEDGER_API_KEY", team), headers=people["sam"])
        assert made.status_code == 201, made.text
    mine = await c.post(
        "/v1/secrets/LEDGER_API_KEY/rotate", json={"value": "k2"}, headers=builder(tenant, "team_fraud")
    )
    assert mine.json()["data"]["version"] == 2, mine.text
    theirs = (await c.get("/v1/secrets", headers=builder(tenant, "team_platform"))).json()["data"]
    assert [(s["name"], s["version"]) for s in theirs if s["name"] == "LEDGER_API_KEY"] == [("LEDGER_API_KEY", 1)]
    several = {"name": "SHARED_KEY", "value": "k1", "teams": ["team_platform", "team_fraud"]}
    refused = await c.post("/v1/secrets", json=several, headers=people["sam"])
    assert (refused.status_code, refused.json()["error"]["code"]) == (400, "secret_one_team"), refused.text


async def test_the_security_team_adds_secrets_when_the_policy_says_so(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    me = builder(tenant, "team_platform", {"securityTeamAddsSecrets": True})
    refused = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY"), headers=me)
    assert refused.status_code == 403, refused.text
    added = await c.post("/v1/secrets", json=_secret("PLATFORM_KEY", "team_platform"), headers=people["sam"])
    assert added.status_code == 201 and added.json()["data"]["teamId"] == "team_platform", added.text
