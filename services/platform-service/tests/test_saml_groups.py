"""Group rules at sign-in (decision D4): a group gives the membership it maps to, at the highest role any of the
person's groups gives in that team; with removal on, signing in without a group ends only what groups gave. A
membership given by hand or by a first sign-in stays, and a missing, empty or Entra overage groups claim removes
nothing."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa

from ops_platform.store.roles import mirror_membership
from ops_platform.store.tables import audit_entries, members, users
from ops_service_kit.ids import new_id, now_iso

from .conftest import IDP, SignInRig
from .test_workspace_teams import _team  # pyright: ignore[reportPrivateUsage]


async def _provider(rig: SignInRig, domain: str, rules: list[dict[str, str]], **groups: Any) -> str:
    provider = new_id("sip")
    cert = (await rig.idp.get("/saml/bank/certificate")).text
    body = {
        "kind": "saml",
        "label": "Bank SAML",
        "domains": [domain],
        "saml": {"idpEntityId": f"{IDP}/saml/bank", "ssoUrl": f"{IDP}/saml/bank/sso", "certificate": cert},
        "jit": {"team": rig.ops_team, "role": "chat_user"},
        "groups": {"map": rules, **groups},
    }
    r = await rig.configure(provider, body)
    assert r.status_code == 200, r.text
    return provider


async def _sign_in(rig: SignInRig, email: str, extra: str) -> dict[str, str]:
    """Signs `email` in with the identity provider sending `extra` (e.g. `&groups=a,b`); returns their roles."""
    start = (await rig.public.post("/v1/auth/sso/start", json={"email": email})).json()["data"]
    location = await rig.answer(start["redirectUrl"] + extra, user=email)
    code = httpx.URL(location).params["code"]
    done = await rig.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": start["flowKey"]})
    assert done.status_code == 200, done.text
    return dict(done.json()["data"]["principal"]["roles"])


async def _hand_member(rig: SignInRig, email: str, team: str, role: str) -> None:
    """An admin adds the person to `team` by hand (no sign-in grant behind it)."""
    now = now_iso()
    async with rig.engine.begin() as c:
        user = (await c.execute(sa.select(users.c.id).where(users.c.email == email))).scalar_one()
        await c.execute(
            members.insert().values(
                id=new_id("mem"), tenant_id=rig.tenant, team_id=team, user_id=user, email=email, role=role,
                status="active", created_at=now, updated_at=now,
            )
        )  # fmt: skip
        await mirror_membership(
            c, tenant_id=rig.tenant, team_id=team, user_id=user, member_role=role, security_team=rig.security_team,
            granted_by="test", at=now,
        )  # fmt: skip


async def _audited(rig: SignInRig, action: str, email: str) -> int:
    async with rig.engine.connect() as c:
        rows = (
            await c.execute(
                sa.select(audit_entries.c.detail).where(
                    audit_entries.c.tenant_id == rig.tenant, audit_entries.c.action == action
                )
            )
        ).all()
    return sum(1 for r in rows if r.detail.get("email") == email)


async def test_leaving_a_group_ends_only_what_that_group_gave(signin: SignInRig) -> None:
    tellers, desk, audit = await _team(signin, "Tellers"), await _team(signin, "Desk"), await _team(signin, "Audit")
    domain = f"leave.{signin.zone}"
    await _provider(
        signin,
        domain,
        [{"group": "tellers", "team": tellers, "role": "viewer"}, {"group": "desk", "team": desk, "role": "builder"}],
        onMissing="remove",
    )
    email = f"ana@{domain}"
    first = await _sign_in(signin, email, "&groups=tellers,desk")
    assert first == {signin.ops_team: "chat_user", tellers: "viewer", desk: "builder"}, first
    await _hand_member(signin, email, audit, "viewer")
    # Ana left "desk" at the provider: the Desk membership it gave ends; JIT, Tellers and the hand-given Audit stay.
    after = await _sign_in(signin, email, "&groups=tellers")
    assert after == {signin.ops_team: "chat_user", tellers: "viewer", audit: "viewer"}, after
    assert await _audited(signin, "member.group_removed", email) == 1
    assert await _audited(signin, "member.group", email) == 2


async def test_a_missing_empty_or_overage_groups_claim_removes_nothing(signin: SignInRig) -> None:
    tellers = await _team(signin, "Tellers")
    domain = f"over.{signin.zone}"
    await _provider(signin, domain, [{"group": "tellers", "team": tellers, "role": "viewer"}], onMissing="remove")
    email = f"bo@{domain}"
    assert tellers in await _sign_in(signin, email, "&groups=tellers")
    for extra in ("", "&groups=", "&groups=tellers&overage=1"):
        roles = await _sign_in(signin, email, extra)
        assert roles.get(tellers) == "viewer", (extra, roles)
    assert await _audited(signin, "member.group_removed", email) == 0


async def test_removal_never_ends_a_first_sign_in_or_hand_given_membership(signin: SignInRig) -> None:
    tellers, branch = await _team(signin, "Tellers"), await _team(signin, "Branch")
    domain = f"keep.{signin.zone}"
    # Ana's first sign-in lands her in Ops (JIT); an admin also adds her to Branch by hand; a rule maps "branch" there.
    await _provider(
        signin,
        domain,
        [
            {"group": "tellers", "team": tellers, "role": "viewer"},
            {"group": "branch", "team": branch, "role": "viewer"},
        ],
        onMissing="remove",
    )
    email = f"cy@{domain}"
    await _sign_in(signin, email, "&groups=other")
    await _hand_member(signin, email, branch, "builder")
    assert (await _sign_in(signin, email, "&groups=tellers,branch")).get(branch) == "builder"
    # Leaving both groups ends only Tellers, the one membership a group gave.
    after = await _sign_in(signin, email, "&groups=other")
    assert after == {signin.ops_team: "chat_user", branch: "builder"}, after


async def test_two_rules_into_one_team_give_the_higher_role(signin: SignInRig) -> None:
    desk = await _team(signin, "Desk")
    domain = f"rank.{signin.zone}"
    await _provider(
        signin,
        domain,
        # The lower role first, so a first-match rule would give it.
        [{"group": "readers", "team": desk, "role": "viewer"}, {"group": "builders", "team": desk, "role": "builder"}],
    )
    roles = await _sign_in(signin, f"di@{domain}", "&groups=readers,builders")
    assert roles.get(desk) == "builder", roles
    async with signin.engine.connect() as c:
        count = (
            await c.execute(sa.select(sa.func.count()).select_from(members).where(members.c.email == f"di@{domain}"))
        ).scalar_one()
    assert count == 2


async def test_a_new_provider_removes_by_default_and_reads_its_rules_back(signin: SignInRig) -> None:
    tellers = await _team(signin, "Tellers")
    domain = f"old.{signin.zone}"
    provider = await _provider(signin, domain, [{"group": "tellers", "team": tellers, "role": "viewer"}])
    r = await signin.public.get("/v1/settings/sign-in/providers", headers=signin.admin)
    saved = next(p for p in r.json()["data"] if p["id"] == provider)
    # A new provider removes by default; the choice is shown with the rules read back from their own rows.
    assert saved["groups"]["onMissing"] == "remove"
    assert saved["groups"]["map"] == [{"group": "tellers", "team": tellers, "role": "viewer"}]
