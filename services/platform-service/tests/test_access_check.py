"""Check one action for one person (c-150), by failure mode: the answer disagrees with the services' own can() (a
grant missed, or a refusal the grid would allow), a policy refusal reads as the grid's yes, someone without access.view
checks a colleague, a refusal speaks to the admin instead of about the person, and a check leaves no trace in the
audit log or one that does not say whose access was checked."""

from __future__ import annotations

from typing import Any

from .conftest import DEMO_PASSWORD, SignInRig


async def _headers(rig: SignInRig, email: str, team: str) -> dict[str, str]:
    r = await rig.public.post("/v1/auth/sign-in", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


async def _team_of(rig: SignInRig, person: str) -> str:
    r = await rig.public.get(f"/v1/people/{person}/permissions", headers=rig.admin)
    assert r.status_code == 200, r.text
    return str(r.json()["data"]["teams"][0]["teamId"])


async def _admin_email(rig: SignInRig) -> str:
    me = await rig.public.get("/v1/me", headers={"Authorization": rig.admin["Authorization"]})
    return str(me.json()["data"]["user"]["email"])


async def _check(rig: SignInRig, h: dict[str, str], **body: Any) -> dict[str, Any]:
    r = await rig.public.post("/v1/access/check", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_the_answer_names_the_granting_role_or_the_refusal_the_services_would_give(signin: SignInRig) -> None:
    builder = await signin.person(f"builder@{signin.zone}", role="builder")
    team = await _team_of(signin, builder)
    h = await _headers(signin, await _admin_email(signin), team)
    yes = await _check(signin, h, personId=builder, area="agents", action="edit")
    assert (yes["allowed"], yes["scope"], yes["refusedBy"]) == (True, "all", None), yes
    assert any(r["name"] == "Builder" for r in yes["grantedBy"]), yes
    no = await _check(signin, h, personId=builder, area="access", action="manage")
    assert (no["allowed"], no["refusedBy"]["code"]) == (False, "role_required"), no
    assert "access.manage" in no["refusedBy"]["reason"], no


async def test_a_policy_refusal_is_reported_as_the_policy_not_the_grid(signin: SignInRig) -> None:
    approver_email = f"approver@{signin.zone}"
    approver = await signin.person(approver_email, role="approver")
    team = await _team_of(signin, approver)
    h = await _headers(signin, await _admin_email(signin), team)
    asked = {"personId": approver, "area": "reviews", "action": "decide", "requestedBy": approver_email}
    assert (await _check(signin, h, **asked))["allowed"] is True, "the workspace lets a requester decide by default"
    off = await signin.public.put("/v1/policies/requesterMayDecide", json={"value": False}, headers=signin.admin)
    assert off.status_code == 200, off.text
    refused = await _check(signin, h, **asked)
    assert (refused["allowed"], refused["refusedBy"]["code"]) == (False, "own_request"), refused
    # The admin reads a refusal about the person checked, not one addressed to the admin.
    assert refused["refusedBy"]["reason"].startswith(f"{approver_email} asked for this"), refused
    audit = await signin.public.get("/v1/audit?action=access.check", headers=h)
    assert audit.status_code == 200 and audit.json()["data"]["pagination"]["total"] >= 2, audit.text
    rows = audit.json()["data"]["data"]
    said = [(r["kind"], r["summary"]) for r in rows]
    assert ("checked", f"Checked {approver_email}'s access to decide on reviews: refused") in said, said


async def test_a_person_without_access_view_cannot_check_a_colleague(signin: SignInRig) -> None:
    viewer_email = f"chat@{signin.zone}"
    viewer = await signin.person(viewer_email, role="chat_user")
    team = await _team_of(signin, viewer)
    h = await _headers(signin, viewer_email, team)
    r = await signin.public.post(
        "/v1/access/check", json={"personId": viewer, "area": "agents", "action": "view"}, headers=h
    )
    assert (r.status_code, r.json()["error"]["code"]) == (403, "admin_required"), r.text


async def test_a_locked_action_says_why_and_who_can_grant_it(signin: SignInRig) -> None:
    # A Viewer asking to publish an agent reads the refusal, the roles that grant it and who can give roles there.
    email = f"locked@{signin.zone}"
    viewer = await signin.person(email, role="viewer")
    team = await _team_of(signin, viewer)
    h = await _headers(signin, email, team)
    r = await signin.public.get("/v1/me/why?area=agents&action=publish", headers=h)
    assert r.status_code == 200, r.text
    why = r.json()["data"]
    assert (why["allowed"], why["refusedBy"]["code"]) == (False, "role_required"), why
    assert {"Admin", "Builder"} <= {x["name"] for x in why["roles"]}, why["roles"]
    assert why["askable"], "the workspace admin reaches every team and can give roles"
    mine = await signin.public.get("/v1/me/why?area=agents&action=view", headers=h)
    assert mine.json()["data"]["allowed"] is True, mine.text
