"""An existing member of an SSO-only workspace with no provider link and no password, by failure mode: the members
list not telling them apart (`needsInvite`); a new invite that leaves them unable to sign in, or that a password
accept turns into another way in; a used invite linking a second account; the links route naming the wrong provider
or whether it is linked."""

from __future__ import annotations

import httpx
import sqlalchemy as sa

from ops_platform.keys import dev_signer
from ops_platform.store.tables import members, password_credentials, signin_identities
from ops_policy import Ed25519Verifier, verify
from ops_service_kit.ids import now_iso

from .conftest import DEMO_PASSWORD, SignInRig


def _claims(token: str) -> dict[str, object]:
    return verify(token, Ed25519Verifier.from_jwk(dev_signer().public_jwk(), "platform"))


async def _links(rig: SignInRig, user_id: str) -> int:
    async with rig.engine.connect() as c:
        q = sa.select(sa.func.count()).select_from(signin_identities).where(signin_identities.c.user_id == user_id)
        return int((await c.execute(q)).scalar_one())


async def _team_of(rig: SignInRig, user_id: str) -> tuple[str, str]:
    """Moves the person's membership into the team the rig's admin manages: its id and the member id."""
    async with rig.engine.begin() as c:
        await c.execute(members.update().where(members.c.user_id == user_id).values(team_id=rig.ops_team))
        found = (await c.execute(sa.select(members.c.id).where(members.c.user_id == user_id))).scalar_one()
    return rig.ops_team, str(found)


async def _listed(rig: SignInRig, team: str) -> dict[str, bool]:
    r = await rig.public.get("/v1/settings/members", headers={**rig.admin, "X-Team-Id": team})
    assert r.status_code == 200, r.text
    return {m["email"]: m["needsInvite"] for m in r.json()["data"]["data"]}


async def test_needs_invite_names_only_active_members_who_cannot_sign_in(signin: SignInRig) -> None:
    domain = f"needs.{signin.zone}"
    lost = await signin.person(f"lost@{domain}")
    team, _ = await _team_of(signin, lost)
    assert (await _listed(signin, team))[f"lost@{domain}"] is False  # password sign-in still on: not affected
    provider = await signin.oidc(domain, jit=False)
    keyed = await signin.person(f"keyed@{domain}")
    linked = await signin.person(f"linked@{domain}")
    for user in (keyed, linked):
        await _team_of(signin, user)
    now = now_iso()
    async with signin.engine.begin() as c:
        await c.execute(
            password_credentials.insert().values(user_id=keyed, tenant_id=signin.tenant, hash="x", updated_at=now)
        )
        await c.execute(
            signin_identities.insert().values(
                id="sid_t1", tenant_id=signin.tenant, provider_id=provider,
                subject="s-linked", user_id=linked, created_at=now, last_used_at=now,
            )
        )  # fmt: skip
    seen = {k: v for k, v in (await _listed(signin, team)).items() if k.endswith(domain)}
    assert seen == {f"lost@{domain}": True, f"keyed@{domain}": False, f"linked@{domain}": False}, seen


async def test_a_reinvite_signs_an_active_member_in_through_the_provider_once(signin: SignInRig) -> None:
    domain = f"again.{signin.zone}"
    email = f"cy@{domain}"
    person = await signin.person(email, role="builder")
    team, member = await _team_of(signin, person)
    await signin.oidc(domain, jit=False)
    h = {**signin.admin, "X-Team-Id": team}
    made = await signin.public.post("/v1/settings/members/reinvite", headers=h, json={})
    assert made.status_code == 200, made.text
    data = made.json()["data"]
    # Omitting ids reinvites every affected member of the team: the rig's own people with no password row too.
    # The rig's admin cannot sign in either, but a link invite never opens an admin's account.
    assert member in data["updated"] and {x["reason"] for x in data["skipped"]} <= {"links_own_session"}, data
    assert "token" not in made.text and "invites" not in data
    token = signin.mailed_invite(email)
    seen = (await signin.public.get(f"/v1/invites/{token}")).json()["data"]
    assert seen["state"] == "pending" and seen["existingAccount"] is True, seen
    # The link alone never sets a password on an existing account.
    accepted = await signin.public.post(f"/v1/invites/{token}/accept", json={"name": "Cy", "password": DEMO_PASSWORD})
    assert accepted.status_code == 401, accepted.text
    r = await signin.sign_in_sso(email, invite=token)
    assert r.completed is not None and r.completed.status_code == 200, r.location
    claims = _claims(r.completed.json()["data"]["token"])
    assert claims["sub"] == person
    assert await _links(signin, person) == 1
    assert (await signin.public.get(f"/v1/invites/{token}")).json()["data"]["state"] == "accepted"
    again = await signin.public.post("/v1/settings/members/reinvite", headers=h, json={"ids": [member]})
    assert again.json()["data"]["skipped"] == [{"id": member, "reason": "not_affected"}], again.text


async def test_a_link_invite_works_once_for_its_own_person_and_never_for_an_admin(signin: SignInRig) -> None:
    domain = f"used.{signin.zone}"
    await signin.saml(domain)
    email = f"di@{domain}"
    person = await signin.person(email)
    boss = await signin.person(f"boss@{domain}", role="admin")
    team, member = await _team_of(signin, person)
    _, boss_member = await _team_of(signin, boss)
    h = {**signin.admin, "X-Team-Id": team}
    shown = (await signin.public.get("/v1/settings/members", headers=h)).json()["data"]["data"]
    flags = {m["email"]: (m["needsInvite"], m["linksOwnSession"]) for m in shown}
    assert flags[email] == (True, False) and flags[f"boss@{domain}"] == (False, True), flags
    made = await signin.public.post("/v1/settings/members/reinvite", headers=h, json={"ids": [member, boss_member]})
    assert made.json()["data"]["skipped"] == [{"id": boss_member, "reason": "links_own_session"}], made.text
    token = signin.mailed_invite(email)
    # Another address at the provider holding the link opens nothing.
    eve = await signin.sign_in_sso(f"eve@{domain}", invite=token)
    assert eve.completed is None or _claims(eve.completed.json()["data"]["token"])["sub"] != person
    first = await signin.sign_in_sso(email, invite=token)
    assert first.completed is not None and first.completed.status_code == 200, first.location
    assert _claims(first.completed.json()["data"]["token"])["roles"] == {team: "viewer"}
    async with signin.engine.begin() as c:  # the person's link is gone, as after an admin removes it
        await c.execute(signin_identities.delete().where(signin_identities.c.user_id == person))
    used = await signin.sign_in_sso(email, invite=token)
    assert used.query == {"error": "link_required"} and await _links(signin, person) == 0
    # An expired link invite links nobody either.
    await signin.public.post("/v1/settings/members/reinvite", headers=h, json={"ids": [member]})
    async with signin.engine.begin() as c:
        await c.execute(members.update().where(members.c.id == member).values(invite_expires_at=now_iso()))
    late = await signin.sign_in_sso(email, invite=signin.mailed_invite(email))
    assert late.query == {"error": "link_required"} and await _links(signin, person) == 0


async def test_sso_links_name_the_workspace_provider_and_whether_it_is_linked(signin: SignInRig) -> None:
    domain = f"mine.{signin.zone}"
    email = f"ed@{domain}"
    await signin.person(email)
    auth, step_up = await signin.stepped_up(email)
    assert (await signin.public.get("/v1/auth/sso/links", headers=auth)).json()["data"] == []
    await signin.oidc(domain, jit=False)
    before = (await signin.public.get("/v1/auth/sso/links", headers=auth)).json()["data"]
    assert [(x["kind"], x["linked"], x["linkedAt"]) for x in before] == [("oidc", False, None)], before
    start = (await signin.public.post("/v1/auth/sso/link/start", json={"stepUp": step_up}, headers=auth)).json()["data"]
    location = await signin.answer(start["redirectUrl"], user=email, at_idp={"subject": "ed-1"})
    body = {"code": dict(httpx.URL(location).params)["code"], "flowKey": start["flowKey"]}
    assert (await signin.public.post("/v1/auth/sso/link/complete", json=body, headers=auth)).status_code == 200
    after = (await signin.public.get("/v1/auth/sso/links", headers=auth)).json()["data"]
    assert after[0]["linked"] is True and after[0]["linkedAt"] and after[0]["providerId"] == before[0]["providerId"]
