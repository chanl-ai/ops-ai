"""A workspace admin acts in any team (c-208), by failure mode: a workspace admin refused in a team they do not belong
to, here or at another service that picks `X-Team-Id` from the token (F1); a team admin, the Security team's included,
let into a team they do not belong to (F2); an archived team offered to a workspace admin (F3)."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from ops_identity import Identity
from ops_platform.keys import dev_signer
from ops_service_kit.errors import Forbidden

from .conftest import DEMO_PASSWORD, SignInRig


async def _session(rig: SignInRig, email: str) -> dict[str, Any]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _team_led_by_someone_else(rig: SignInRig, lead: str) -> str:
    await rig.person(lead, role="viewer")
    r = await rig.public.post("/v1/settings/teams", json={"name": f"Team of {lead}", "admin": lead}, headers=rig.admin)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


def _request(method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "headers": [], "path": "/", "query_string": b""})


async def test_a_workspace_admin_acts_in_a_team_they_do_not_belong_to(signin: SignInRig) -> None:
    team = await _team_led_by_someone_else(signin, f"lead@{signin.zone}")
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    admin_email = me.json()["data"]["user"]["email"]
    session = await _session(signin, admin_email)
    assert team in session["principal"]["teamIds"]
    h = {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}
    members = await signin.public.get("/v1/settings/members", headers=h)
    assert members.status_code == 200, members.text
    invite = await signin.public.post(
        "/v1/settings/members/invite", json={"emails": [f"new@{signin.zone}"], "role": "viewer"}, headers=h
    )
    assert invite.status_code == 200, invite.text
    listed = await signin.public.get("/v1/teams", headers={"Authorization": f"Bearer {session['token']}"})
    assert any(t["id"] == team and t["role"] == "admin" for t in listed.json()["data"])
    # Another service verifies the same token and lets the admin act in that team.
    jwks = {"keys": [dev_signer().public_jwk()]}

    async def fetch() -> dict[str, Any]:
        return jwks

    async def no_keys(_: str) -> None:
        return None

    identity = Identity(audience="agents", jwks=fetch, introspect=no_keys)
    p = await identity.principal(_request(), authorization=f"Bearer {session['token']}", x_team_id=team)
    assert p.team_id == team


async def test_a_team_admin_is_kept_to_their_own_teams(signin: SignInRig) -> None:
    team = await _team_led_by_someone_else(signin, f"lead2@{signin.zone}")
    h = await signin.security_admin_only(f"sec2@{signin.zone}")
    token = h["Authorization"].removeprefix("Bearer ")
    r = await signin.public.get("/v1/settings/members", headers={**h, "X-Team-Id": team})
    assert r.status_code == 403 and r.json()["error"]["code"] == "team_forbidden", r.text
    listed = await signin.public.get("/v1/teams", headers={"Authorization": h["Authorization"]})
    assert team not in [t["id"] for t in listed.json()["data"]]

    async def fetch() -> dict[str, Any]:
        return {"keys": [dev_signer().public_jwk()]}

    async def no_keys(_: str) -> None:
        return None

    identity = Identity(audience="agents", jwks=fetch, introspect=no_keys)
    try:
        await identity.principal(_request(), authorization=f"Bearer {token}", x_team_id=team)
        raise AssertionError("a team admin acted in a team they do not belong to")
    except Forbidden as e:
        assert e.code == "team_forbidden"


async def test_an_archived_team_is_not_offered_to_a_workspace_admin(signin: SignInRig) -> None:
    team = await _team_led_by_someone_else(signin, f"lead3@{signin.zone}")
    r = await signin.public.post(f"/v1/settings/teams/{team}/archive", headers=signin.admin)
    assert r.status_code == 200, r.text
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    session = await _session(signin, me.json()["data"]["user"]["email"])
    assert team not in session["principal"]["teamIds"]


async def test_a_workspace_admin_lists_every_teams_keys_and_a_team_admin_does_not(signin: SignInRig) -> None:
    # A workspace admin may do everything, the workspace's key list included; a team's own admin reads only its keys.
    lead = f"keys-lead@{signin.zone}"
    await _team_led_by_someone_else(signin, lead)
    admin = await signin.public.get("/v1/api-key-summaries", headers={"Authorization": signin.admin["Authorization"]})
    assert admin.status_code == 200, admin.text
    assert isinstance(admin.json()["data"], list)
    session = await _session(signin, lead)
    team_admin = await signin.public.get(
        "/v1/api-key-summaries", headers={"Authorization": f"Bearer {session['token']}"}
    )
    assert (team_admin.status_code, team_admin.json()["error"]["code"]) == (403, "admin_required"), team_admin.text


async def test_a_team_list_says_where_access_beyond_the_team_role_comes_from(signin: SignInRig) -> None:
    # A Viewer of a team who is also an admin across the workspace reads as both, so Access never shows less than
    # the person can do; the row names the person, whose page reads their grants with their name.
    lead = f"wide-lead@{signin.zone}"
    team = await _team_led_by_someone_else(signin, lead)
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    admin_email = me.json()["data"]["user"]["email"]
    session = await _session(signin, admin_email)
    h = {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}
    rows = (await signin.public.get("/v1/settings/members", headers=h)).json()["data"]["data"]
    lead_row = next(r for r in rows if r["email"] == lead)
    assert lead_row["userId"] and lead_row["workspaceRoles"] == [], lead_row
    admin_id = me.json()["data"]["user"]["id"]
    perms = await signin.public.get(f"/v1/people/{lead_row['userId']}/permissions", headers=h)
    assert perms.status_code == 200 and perms.json()["data"]["email"] == lead, perms.text
    mine = await signin.public.get(f"/v1/people/{admin_id}/permissions", headers=h)
    assert mine.json()["data"]["workspace"], "the workspace admin holds grants in every team"
    team_rows = (await signin.public.get("/v1/settings/members", headers=signin.admin)).json()["data"]["data"]
    assert any(r["workspaceRoles"] for r in team_rows if r.get("userId") == admin_id), team_rows
