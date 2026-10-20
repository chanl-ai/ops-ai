"""GET /v1/team-names (c-224): every team's display name in the workspace, so a page showing another team's record
names its team rather than its id. By failure mode: a member of one team cannot name another; one workspace's names
reach another; a service without the settings:view scope reads them."""

from __future__ import annotations

from ops_identity import dev_service_signer, mint_service_token

from .conftest import SignInRig
from .test_policies import _team_admin  # pyright: ignore[reportPrivateUsage]


def service(scopes: list[str], tenant: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="platform", tenant_id=tenant, scopes=scopes
    )
    return {"Authorization": f"Bearer {token}"}


async def test_any_member_and_a_scoped_service_read_every_teams_name(signin: SignInRig) -> None:
    team_a, _ = await _team_admin(signin, "ana")
    team_b, viewer = await _team_admin(signin, "vic", role="viewer")
    r = await signin.public.get("/v1/team-names", headers=viewer)
    assert r.status_code == 200, r.text
    names = {t["id"]: t["name"] for t in r.json()["data"]}
    assert team_a in names and team_b in names and names[team_a], names

    by_service = await signin.public.get("/v1/team-names", headers=service(["settings:view"], signin.tenant))
    assert {t["id"] for t in by_service.json()["data"]} == set(names), by_service.text
    other = await signin.public.get("/v1/team-names", headers=service(["settings:view"], "ten_other"))
    assert other.json()["data"] == [], "another workspace's teams"
    bare = await signin.public.get("/v1/team-names", headers=service([], signin.tenant))
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required")


async def test_a_scoped_service_reads_every_persons_name_and_no_other_workspaces(signin: SignInRig) -> None:
    # Lists named people by email address; a service without the scope, or another workspace, reads none.
    _, viewer = await _team_admin(signin, "vic", role="viewer")
    r = await signin.public.get("/v1/people-names", headers=service(["settings:view"], signin.tenant))
    assert r.status_code == 200, r.text
    names = {p["email"]: p["name"] for p in r.json()["data"]}
    assert names and all(names.values()), names
    assert (await signin.public.get("/v1/people-names", headers=viewer)).status_code == 200
    other = await signin.public.get("/v1/people-names", headers=service(["settings:view"], "ten_other"))
    assert other.json()["data"] == []
    bare = await signin.public.get("/v1/people-names", headers=service([], signin.tenant))
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required")
