"""Check one action for one person, by failure mode: the answer disagrees with the services' own can() (a
grant missed, or a refusal the grid would allow), a policy refusal reads as the grid's yes, someone without access.view
checks a colleague, a refusal speaks to the admin instead of about the person, and a check leaves no trace in the
audit log or one that does not say whose access was checked."""

from __future__ import annotations

from typing import Any

from ops_identity import dev_service_signer, mint_service_token
from ops_platform.store.tables import users

from .conftest import DEMO_PASSWORD, SignInRig, seed_tx


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
    assert "an Admin can" in no["refusedBy"]["reason"], no


async def test_a_policy_refusal_is_reported_as_the_policy_not_the_grid(signin: SignInRig) -> None:
    approver_email = f"approver@{signin.zone}"
    approver = await signin.person(approver_email, role="approver")
    team = await _team_of(signin, approver)
    h = await _headers(signin, await _admin_email(signin), team)
    asked = {"personId": approver, "area": "reviews", "action": "decide", "requestedBy": approver_email}
    # Approve own requests is Approvals · decide, which only Admin holds; a saved requesterMayDecide is retired.
    refused = await _check(signin, h, **asked)
    assert (refused["allowed"], refused["refusedBy"]["code"]) == (False, "own_request"), refused
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    admin_email = str(me.json()["data"]["user"]["email"])
    own = {"personId": str(me.json()["data"]["user"]["id"]), "requestedBy": admin_email}
    assert (await _check(signin, h, **{**asked, **own}))["allowed"] is True, "the admin holds the cell"
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


async def test_whom_to_ask_never_names_the_caller(signin: SignInRig) -> None:
    # The workspace admin holds access.manage, so a list that kept the caller would name her to herself.
    email = await _admin_email(signin)
    me = await signin.public.get("/v1/me", headers={"Authorization": signin.admin["Authorization"]})
    name = str(me.json()["data"]["user"]["name"])
    why = await signin.public.get("/v1/me/why?area=agents&action=publish", headers=signin.admin)
    assert why.status_code == 200, why.text
    assert why.json()["data"]["allowed"] is True, why.text
    assert name not in why.json()["data"]["askable"], why.json()["data"]["askable"]
    held = await signin.public.get("/v1/access/holders?area=access&action=manage", headers=signin.admin)
    assert held.status_code == 200, held.text
    assert email not in [h["email"] for h in held.json()["data"]["holders"]], held.json()["data"]["holders"]


async def test_a_service_asks_by_email_in_its_tokens_team_and_needs_access_view(signin: SignInRig) -> None:
    """tools-service decides a request on a workflow's behalf and knows only the asker's address: its token names the
    tenant and the deciding team, and the answer is the same can() a person's check gives."""
    approver_email = f"svc.approver@{signin.zone}"
    approver = await signin.person(approver_email, role="approver")
    team = await _team_of(signin, approver)

    def svc(scopes: list[str], tenant: str = signin.tenant) -> dict[str, str]:
        token = mint_service_token(
            dev_service_signer(), service="tools", audience="platform", tenant_id=tenant, scopes=scopes, team_id=team
        )
        return {"Authorization": f"Bearer {token}"}

    own = {"email": approver_email, "area": "reviews", "action": "decide", "requestedBy": approver_email}
    r = await signin.public.post("/v1/access/check", json=own, headers=svc(["access:view"]))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["refusedBy"]["code"] == "own_request", r.text
    other = await signin.public.post(
        "/v1/access/check", json={**own, "requestedBy": "someone@else.test"}, headers=svc(["access:view"])
    )
    assert other.json()["data"]["allowed"] is True, other.text
    no_scope = await signin.public.post("/v1/access/check", json=own, headers=svc(["settings:view"]))
    assert (no_scope.status_code, no_scope.json()["error"]["code"]) == (403, "scope_required"), no_scope.text
    elsewhere = await signin.public.post("/v1/access/check", json=own, headers=svc(["access:view"], "ten_other"))
    assert elsewhere.status_code in (403, 404), elsewhere.text


async def test_a_service_and_a_person_token_get_one_answer_for_the_same_asker(signin: SignInRig) -> None:
    """tools-service and agents-service name the asker by email and an admin names them by id; both must reach the
    same person through one lookup. A suspended person keeps their user row and role assignments, so a lookup by
    email that skipped the status would let them approve their own request."""
    email = f"suspended.admin@{signin.zone}"
    person = await signin.person(email, role="admin")
    team = await _team_of(signin, person)
    token = mint_service_token(
        dev_service_signer(), service="tools", audience="platform", tenant_id=signin.tenant,
        scopes=["access:view"], team_id=team,
    )  # fmt: skip
    svc = {"Authorization": f"Bearer {token}"}
    own = {"area": "reviews", "action": "decide", "requestedBy": email}
    h = await _headers(signin, await _admin_email(signin), team)

    before = await _check(signin, svc, email=email, **own)
    assert before["allowed"] is True, before
    async with seed_tx(signin.engine, signin.tenant) as c:
        await c.execute(users.update().where(users.c.id == person).values(status="suspended"))

    by_service = await signin.public.post("/v1/access/check", json={"email": email, **own}, headers=svc)
    by_person = await signin.public.post("/v1/access/check", json={"personId": person, **own}, headers=h)
    assert (by_service.status_code, by_person.status_code) == (404, 404), (by_service.text, by_person.text)
