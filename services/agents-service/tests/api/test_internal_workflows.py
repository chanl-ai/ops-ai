"""agents-service's workflow refs for services (c-039, on a public route since c-168), by failure mode: a person's
token, a token naming no tenant or a token without `workflows:view` reading it, a workflow missing its owning team,
and a seed that names a placeholder team no service has a record of."""

from __future__ import annotations

from httpx import AsyncClient

from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.ids import new_id

URL = "/v1/workflow-refs"


def service(tenant: str | None = "local", scopes: tuple[str, ...] = ("workflows:view",)) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="tools", audience="agents", tenant_id=tenant, scopes=list(scopes)
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_service_reads_every_workflow_with_its_owning_team(client: AsyncClient) -> None:
    body = {"name": f"Mine {new_id('x')}", "trigger": "manual"}
    created = await client.post("/v1/workflows", json=body, headers={"X-Team-Id": "team_cards"})
    assert created.status_code == 201, created.text
    r = await client.get(URL, headers=service())
    assert r.status_code == 200, r.text
    rows = {w["id"]: w for w in r.json()["data"]}
    assert rows[created.json()["data"]["id"]]["teamId"] == "team_cards", "an API-created workflow keeps its team"
    seeded = [w for w in rows.values() if w["id"] in ("dispute_email", "wire_hold_review")]
    assert seeded and all(w["teamId"] == "team_ops" for w in seeded), "seeds name Operations, not a placeholder"
    assert not [w for w in rows.values() if w["teamId"] == "team_all"]


async def test_a_person_reads_their_teams_workflows_and_a_service_needs_a_tenant_and_its_scope(
    client: AsyncClient,
) -> None:
    """A person calls it too (c-222) and reads their team's workflows only."""
    body = {"name": f"Cards {new_id('x')}", "trigger": "manual"}
    created = (await client.post("/v1/workflows", json=body, headers={"X-Team-Id": "team_cards"})).json()["data"]
    cards = (await client.get(URL, headers={"X-Team-Id": "team_cards"})).json()["data"]
    assert created["id"] in [w["id"] for w in cards] and {w["teamId"] for w in cards} == {"team_cards"}, cards
    assert (await client.get(URL, headers=service(None))).status_code == 401, "a token naming no tenant is refused"
    unscoped = await client.get(URL, headers=service(scopes=()))
    assert unscoped.status_code == 403 and unscoped.json()["error"]["code"] == "scope_required", unscoped.text


async def test_a_service_token_naming_a_team_still_reads_every_teams_workflows(client: AsyncClient) -> None:
    # tools-service calls on behalf of a person, so its token names that person's team; the workflow it checks a grant
    # for may belong to any team (c-407: the registry read is scoped to the acting team, so this read names why not).
    body = {"name": f"Cards {new_id('x')}", "trigger": "manual"}
    made = (await client.post("/v1/workflows", json=body, headers={"X-Team-Id": "team_cards"})).json()["data"]
    token = mint_service_token(
        dev_service_signer(),
        service="tools",
        audience="agents",
        tenant_id="local",
        scopes=["workflows:view"],
        team_id="team_lending",
    )
    r = await client.get(URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert made["id"] in [w["id"] for w in r.json()["data"]], "a team-named service token read one team's workflows"
