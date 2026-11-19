"""Whoever controls an identity provider cannot become an admin here: a group never gives Admin, and a first SSO
sign-in never links by email to a person who holds Admin anywhere."""

from __future__ import annotations

import sqlalchemy as sa

from ops_platform.store.tables import signin_identities

from .conftest import IDP, SignInRig


async def _links(rig: SignInRig, user: str) -> int:
    async with rig.engine.begin() as c:
        q = sa.select(sa.func.count()).where(signin_identities.c.user_id == user)
        return int((await c.execute(q)).scalar_one())


async def test_a_provider_cannot_sign_in_as_an_admin_by_email(signin: SignInRig) -> None:
    await signin.saml(f"adm.{signin.zone}")
    admin = await signin.person(f"boss@adm.{signin.zone}", role="admin")
    viewer = await signin.person(f"viewer@adm.{signin.zone}", role="viewer")
    refused = await signin.sign_in_sso(f"boss@adm.{signin.zone}")
    assert refused.query == {"error": "no_access"} and refused.completed is None
    assert await _links(signin, admin) == 0
    # Someone who is no admin is linked by email as before.
    ok = await signin.sign_in_sso(f"viewer@adm.{signin.zone}")
    assert ok.completed is not None and ok.completed.status_code == 200, ok.location
    assert await _links(signin, viewer) == 1


async def test_a_group_rule_never_gives_admin(signin: SignInRig) -> None:
    cert = (await signin.idp.get("/saml/bank/certificate")).text
    body = {
        "kind": "saml",
        "label": "Bank SAML",
        "domains": [f"grp.{signin.zone}"],
        "saml": {"idpEntityId": f"{IDP}/saml/bank", "ssoUrl": f"{IDP}/saml/bank/sso", "certificate": cert},
        "groups": {"map": [{"group": "it-admins", "team": signin.ops_team, "role": "admin"}]},
    }
    r = await signin.configure("sip_grp", body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "group_role", r.text
