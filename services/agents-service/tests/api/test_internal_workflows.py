"""agents-service's internal workflow list (c-039), by failure mode: a person's token or a token naming no tenant
reading it, a workflow missing its owning team, and a seed that names a placeholder team no service has a record
of."""

from __future__ import annotations

from httpx import AsyncClient

from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.ids import new_id

URL = "/v1/internal/workflows"


def service(tenant: str | None = "local") -> dict[str, str]:
    token = mint_service_token(dev_service_signer(), service="tools", audience="agents", tenant_id=tenant)
    return {"Authorization": f"Bearer {token}"}


async def test_a_service_reads_every_workflow_with_its_owning_team(client: AsyncClient) -> None:
    body = {"name": f"Mine {new_id('x')}", "trigger": "manual", "owner": "Card Services"}
    created = await client.post("/v1/workflows", json=body, headers={"X-Team-Id": "team_cards"})
    assert created.status_code == 201, created.text
    r = await client.get(URL, headers=service())
    assert r.status_code == 200, r.text
    rows = {w["id"]: w for w in r.json()["data"]}
    assert rows[created.json()["data"]["id"]]["teamId"] == "team_cards", "an API-created workflow keeps its team"
    seeded = [w for w in rows.values() if w["id"] in ("dispute_email", "wire_hold_review")]
    assert seeded and all(w["teamId"] == "team_ops" for w in seeded), "seeds name Operations, not a placeholder"
    assert not [w for w in rows.values() if w["teamId"] == "team_all"]


async def test_only_a_tenant_scoped_service_token_reads_it(client: AsyncClient) -> None:
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(URL, headers={"X-Team-Id": "team_cards"})).status_code == 401, "a dev person is refused"
    assert (await client.get(URL, headers=service(None))).status_code == 401, "a token naming no tenant is refused"
