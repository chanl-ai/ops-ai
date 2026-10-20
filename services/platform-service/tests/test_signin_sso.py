"""SSO sign-in through the fake identity provider (c-188), by failure mode: the options route telling an account
apart (F10); a handoff completed by another browser or twice (F6); a first sign-in making two people, or one for an
email outside the provider's domains (F7); a step-up that passes on the provider's old login or for another person
(F8); an answer from another provider, or of another kind than the flow, signing anyone in (US4)."""

from __future__ import annotations

import asyncio
import html
import re
from urllib.parse import urlencode

import httpx
import sqlalchemy as sa

from ops_access import CHAT_USER
from ops_platform.keys import dev_signer
from ops_platform.store.tables import members, signin_flows, users
from ops_policy import Ed25519Verifier, verify

from .conftest import DEMO_PASSWORD, SignInRig


def _claims(token: str, audience: str = "platform") -> dict[str, object]:
    return verify(token, Ed25519Verifier.from_jwk(dev_signer().public_jwk(), audience))


async def _people(rig: SignInRig, email: str) -> int:
    async with rig.engine.connect() as c:
        q = sa.select(sa.func.count()).select_from(users).where(users.c.email == email, users.c.tenant_id == rig.tenant)
        return int((await c.execute(q)).scalar_one())


async def test_options_name_the_domains_method_and_never_whether_an_account_exists(signin: SignInRig) -> None:
    await signin.oidc(f"opts.{signin.zone}")
    await signin.person(f"known@opts.{signin.zone}")
    known = await signin.public.post("/v1/auth/options", json={"email": f"known@opts.{signin.zone}"})
    unknown = await signin.public.post("/v1/auth/options", json={"email": f"nobody@opts.{signin.zone}"})
    assert known.status_code == 200 and known.json() == unknown.json()
    assert known.json()["data"] == {"password": False, "sso": {"kind": "oidc", "label": "Bank SSO"}}
    other = await signin.public.post("/v1/auth/options", json={"email": "x@elsewhere.test"})
    assert other.json()["data"] == {"password": True, "sso": None}


async def test_a_first_oidc_sign_in_makes_one_chat_only_member(signin: SignInRig) -> None:
    await signin.oidc(f"jit.{signin.zone}")
    email = f"new.teller@jit.{signin.zone}"
    first = await signin.sign_in_sso(email)
    assert first.completed is not None and first.completed.status_code == 200, first.location
    data = first.completed.json()["data"]
    claims = _claims(data["token"])
    assert claims["auth_method"] == "oidc" and claims["roles"] == {signin.ops_team: "chat_user"}
    assert claims["access"] == {signin.ops_team: ["chat_user"]}
    perms = await signin.public.get(
        "/v1/me/permissions", headers={"Authorization": f"Bearer {data['token']}", "X-Team-Id": signin.ops_team}
    )
    granted = {(a["area"], a["action"]) for t in perms.json()["data"]["teams"] for a in t["permissions"]}
    # Exactly the Chat user role's cells, whatever the catalogue gives it: nothing a viewer or builder has.
    assert granted == {(a, x) for a, x, _ in CHAT_USER.grants}, perms.text
    members = await signin.public.get(
        "/v1/settings/members", headers={"Authorization": f"Bearer {data['token']}", "X-Team-Id": signin.ops_team}
    )
    assert members.status_code == 403, members.text
    second = await signin.sign_in_sso(email)
    assert second.completed is not None and second.completed.status_code == 200
    assert _claims(second.completed.json()["data"]["token"])["sub"] == claims["sub"]
    assert await _people(signin, email) == 1


async def test_two_first_sign_ins_at_once_make_one_person(signin: SignInRig) -> None:
    await signin.oidc(f"race.{signin.zone}")
    email = f"racer@race.{signin.zone}"
    rounds = await asyncio.gather(signin.sign_in_sso(email), signin.sign_in_sso(email))
    subs = {_claims(r.completed.json()["data"]["token"])["sub"] for r in rounds if r.completed is not None}
    assert len(subs) == 1 and await _people(signin, email) == 1
    async with signin.engine.connect() as c:
        q = sa.select(sa.func.count()).select_from(members).where(members.c.email == email)
        assert int((await c.execute(q)).scalar_one()) == 1


async def test_an_email_outside_the_providers_domains_makes_nobody(signin: SignInRig) -> None:
    await signin.oidc(f"dom.{signin.zone}")
    # The provider vouches for an address on a domain this provider was not given.
    r = await signin.sign_in_sso(f"someone@dom.{signin.zone}", user=f"ceo@other.{signin.zone}")
    assert r.query == {"error": "sign_in_refused"} and r.completed is None
    assert await _people(signin, f"ceo@other.{signin.zone}") == 0


async def test_a_provider_with_no_first_sign_in_team_signs_in_only_people_it_knows(signin: SignInRig) -> None:
    await signin.oidc(f"nojit.{signin.zone}", jit=False)
    unknown = await signin.sign_in_sso(f"stranger@nojit.{signin.zone}")
    assert unknown.query == {"error": "sign_in_refused"}
    await signin.person(f"member@nojit.{signin.zone}", role="builder")
    known = await signin.sign_in_sso(f"member@nojit.{signin.zone}")
    assert known.completed is not None and known.completed.status_code == 200


async def test_the_handoff_works_once_and_only_for_the_browser_that_started(signin: SignInRig) -> None:
    await signin.oidc(f"hand.{signin.zone}")
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"h@hand.{signin.zone}"})).json()["data"]
    location = await signin.answer(start["redirectUrl"], user=f"h@hand.{signin.zone}")
    code = httpx.URL(location).params["code"]
    stranger = await signin.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": "x" * 43})
    assert stranger.status_code == 401
    mine = await signin.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": start["flowKey"]})
    assert mine.status_code == 200, mine.text
    again = await signin.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": start["flowKey"]})
    assert again.status_code == 401


async def test_an_expired_flow_signs_nobody_in(signin: SignInRig) -> None:
    await signin.oidc(f"late.{signin.zone}")
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"l@late.{signin.zone}"})).json()["data"]
    async with signin.engine.begin() as c:
        await c.execute(signin_flows.update().values(expires_at="2000-01-01T00:00:00.000Z"))
    location = await signin.answer(start["redirectUrl"], user=f"l@late.{signin.zone}")
    assert dict(httpx.URL(location).params) == {"error": "sign_in_refused"}


async def test_saml_signs_in_and_refuses_an_answer_signed_by_another_provider(signin: SignInRig) -> None:
    await signin.saml(f"saml.{signin.zone}")
    ok = await signin.sign_in_sso(f"s@saml.{signin.zone}")
    assert ok.completed is not None and ok.completed.status_code == 200, ok.location
    assert _claims(ok.completed.json()["data"]["token"])["auth_method"] == "saml"
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"t@saml.{signin.zone}"})).json()["data"]
    # The same request answered by another provider's key: the configured certificate does not match.
    forged = await signin.answer(start["redirectUrl"], user=f"t@saml.{signin.zone}", idp_path="/saml/other/sso")
    assert dict(httpx.URL(forged).params) == {"error": "sign_in_refused"}
    assert await _people(signin, f"t@saml.{signin.zone}") == 0


async def test_a_saml_answer_for_an_oidc_flow_is_refused(signin: SignInRig) -> None:
    await signin.oidc(f"mix.{signin.zone}")
    await signin.saml(f"mix-saml.{signin.zone}")
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"m@mix.{signin.zone}"})).json()["data"]
    oidc_state = httpx.URL(start["redirectUrl"]).params["state"]
    saml_start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"m@mix-saml.{signin.zone}"})).json()[
        "data"
    ]
    # A valid SAML answer, posted with the OIDC flow's state as its RelayState.
    url = httpx.URL(saml_start["redirectUrl"])
    page = await signin.idp.get(url.path, params=dict(url.params) | {"user": f"m@mix-saml.{signin.zone}"})
    response = re.search(r'name="SAMLResponse" value="([^"]*)"', page.text)
    assert response is not None
    r = await signin.public.post(
        "/v1/auth/saml/acs",
        content=urlencode({"SAMLResponse": html.unescape(response.group(1)), "RelayState": oidc_state}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 303 and dict(httpx.URL(r.headers["location"]).params) == {"error": "sign_in_refused"}


async def test_password_sign_in_is_refused_in_an_sso_only_workspace(signin: SignInRig) -> None:
    await signin.saml(f"only.{signin.zone}")
    await signin.person(f"p@only.{signin.zone}")
    r = await signin.public.post("/v1/auth/sign-in", json={"email": f"p@only.{signin.zone}", "password": DEMO_PASSWORD})
    assert r.status_code == 401


async def test_sso_step_up_goes_back_to_the_provider_and_asks_again(signin: SignInRig) -> None:
    await signin.saml(f"step.{signin.zone}")
    first = await signin.sign_in_sso(f"s@step.{signin.zone}")
    assert first.completed is not None
    session = first.completed.json()["data"]
    auth = {"Authorization": f"Bearer {session['token']}"}
    wrong_method = await signin.public.post("/v1/auth/step-up", json={"password": DEMO_PASSWORD}, headers=auth)
    assert wrong_method.status_code == 401 and wrong_method.json()["error"]["code"] == "wrong_method"

    async def step_up(*, user: str, stale: bool = False) -> httpx.Response | dict[str, str]:
        start = await signin.public.post("/v1/auth/step-up/sso/start", json={"next": "/reviews"}, headers=auth)
        assert start.status_code == 200, start.text
        data = start.json()["data"]
        location = await signin.answer(data["redirectUrl"], user=user, stale=stale)
        query = dict(httpx.URL(location).params)
        if "code" not in query:
            return query
        return await signin.public.post(
            "/v1/auth/step-up/sso/complete", json={"code": query["code"], "flowKey": data["flowKey"]}, headers=auth
        )

    # The provider reused its earlier login instead of asking again.
    assert await step_up(user=f"s@step.{signin.zone}", stale=True) == {
        "error": "sign_in_refused",
        "stepUp": "1",
        "next": "/reviews",
    }
    # Someone else signed in at the provider.
    other = await signin.sign_in_sso(f"o@step.{signin.zone}")
    assert other.completed is not None
    assert (await step_up(user=f"o@step.{signin.zone}"))["error"] == "sign_in_refused"  # type: ignore[index]
    done = await step_up(user=f"s@step.{signin.zone}")
    assert isinstance(done, httpx.Response) and done.status_code == 200, done
    claims = _claims(done.json()["data"]["token"], "agents")
    assert claims["typ"] == "step_up" and claims["sub"] == _claims(session["token"])["sub"]


async def test_a_password_session_cannot_start_an_sso_step_up(signin: SignInRig) -> None:
    await signin.person(f"pw@{signin.zone}")
    token = (
        await signin.public.post("/v1/auth/sign-in", json={"email": f"pw@{signin.zone}", "password": DEMO_PASSWORD})
    ).json()["data"]["token"]
    r = await signin.public.post("/v1/auth/step-up/sso/start", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "wrong_method"
