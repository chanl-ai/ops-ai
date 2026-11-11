"""Each SAML provider has its own consumer address, and an app-portal tile never signs anyone in from a response
nobody asked for: it is checked, discarded, and the browser goes round a normal sign-in."""

from __future__ import annotations

from typing import Any

import httpx
import sqlalchemy as sa

from ops_platform.store.tables import sessions, signin_providers, users

from .conftest import CONSOLE, SignInRig


async def _saml_of(rig: SignInRig, provider: str) -> dict[str, Any]:
    listed = (await rig.public.get("/v1/settings/sign-in/providers", headers=rig.admin)).json()["data"]
    return next(p for p in listed if p["id"] == provider)["saml"]


async def _counts(rig: SignInRig, email: str) -> tuple[int, int]:
    async with rig.engine.begin() as c:
        people = (await c.execute(sa.select(sa.func.count()).where(users.c.email == email))).scalar_one()
        live = (
            await c.execute(
                sa.select(sa.func.count()).select_from(sessions.join(users, users.c.id == sessions.c.user_id))
                .where(users.c.email == email)
            )
        ).scalar_one()  # fmt: skip
    return int(people), int(live)


async def _unsolicited(rig: SignInRig, saml: dict[str, Any], email: str, *, name: str = "bank") -> httpx.Response:
    page = await rig.idp.get(
        f"/saml/{name}/unsolicited", params={"user": email, "acs": saml["acsUrl"], "audience": saml["spEntityId"]}
    )
    return await rig.post_form(page.text)


async def test_a_new_provider_gets_its_own_addresses_and_metadata(signin: SignInRig) -> None:
    provider = await signin.saml(f"own.{signin.zone}")
    saml = await _saml_of(signin, provider)
    assert saml["acsUrl"].startswith("http://platform/v1/auth/saml/acs/ssp")
    assert saml["signOnUrl"] == f"{CONSOLE}/sso?provider={saml['acsUrl'].rsplit('/', 1)[1]}"
    metadata = await signin.public.get(httpx.URL(saml["spMetadataUrl"]).path)
    assert metadata.status_code == 200 and saml["acsUrl"] in metadata.text and saml["spEntityId"] in metadata.text


async def test_an_unsolicited_response_signs_nobody_in_and_goes_round_a_normal_sign_in(signin: SignInRig) -> None:
    provider = await signin.saml(f"tile.{signin.zone}")
    saml = await _saml_of(signin, provider)
    email = f"teller@tile.{signin.zone}"
    r = await _unsolicited(signin, saml, email)
    assert r.status_code == 303, r.text
    sp_id = saml["acsUrl"].rsplit("/", 1)[1]
    assert r.headers["location"] == f"{CONSOLE}/sso?provider={sp_id}"
    assert await _counts(signin, email) == (0, 0)
    # The console starts a normal round trip for the provider the tile named, and that one signs in.
    start = await signin.public.post("/v1/auth/sso/start", json={"provider": sp_id})
    assert start.status_code == 200, start.text
    started = start.json()["data"]
    location = await signin.answer(started["redirectUrl"], user=email)
    code = dict(httpx.URL(location).params)["code"]
    done = await signin.public.post("/v1/auth/sso/complete", json={"code": code, "flowKey": started["flowKey"]})
    assert done.status_code == 200, done.text
    assert await _counts(signin, email) == (1, 1)


async def test_a_response_from_another_provider_posted_to_this_address_is_refused(signin: SignInRig) -> None:
    mine = await _saml_of(signin, await signin.saml(f"a.{signin.zone}", name="bank"))
    other = await _saml_of(signin, await signin.saml(f"b.{signin.zone}", name="other"))
    # Provider "other" signs a tile response addressed to provider "bank"'s consumer URL.
    page = await signin.idp.get(
        "/saml/other/unsolicited",
        params={"user": f"x@a.{signin.zone}", "acs": mine["acsUrl"], "audience": mine["spEntityId"]},
    )
    r = await signin.post_form(page.text)
    assert dict(httpx.URL(r.headers["location"]).params) == {"error": "sign_in_refused"}
    # An answer to a flow of provider "bank" posted to provider "other"'s address.
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"y@a.{signin.zone}"})).json()["data"]
    url = httpx.URL(start["redirectUrl"])
    at_idp = await signin.idp.get(url.path, params=dict(url.params) | {"user": f"y@a.{signin.zone}"})
    r = await signin.post_form(at_idp.text, to=httpx.URL(other["acsUrl"]).path)
    assert dict(httpx.URL(r.headers["location"]).params) == {"error": "sign_in_refused"}
    assert await _counts(signin, f"y@a.{signin.zone}") == (0, 0)


async def test_a_tile_for_a_provider_with_tiles_off_is_refused(signin: SignInRig) -> None:
    provider = await signin.saml(f"notile.{signin.zone}")
    async with signin.engine.begin() as c:
        row = (await c.execute(sa.select(signin_providers.c.config).where(signin_providers.c.id == provider))).one()
        await c.execute(
            signin_providers.update().where(signin_providers.c.id == provider).values(config={**row[0], "tiles": False})
        )
    saml = await _saml_of(signin, provider)
    r = await _unsolicited(signin, saml, f"z@notile.{signin.zone}")
    assert dict(httpx.URL(r.headers["location"]).params) == {"error": "sign_in_refused"}
    sp_id = saml["acsUrl"].rsplit("/", 1)[1]
    start = await signin.public.post("/v1/auth/sso/start", json={"provider": sp_id})
    assert start.status_code == 400 and start.json()["error"]["code"] == "sso_not_enabled", start.text


async def test_the_shared_address_still_refuses_a_response_nobody_asked_for(signin: SignInRig) -> None:
    provider = await signin.saml(f"shared.{signin.zone}")
    saml = await _saml_of(signin, provider)
    page = await signin.idp.get(
        "/saml/bank/unsolicited",
        params={"user": f"s@shared.{signin.zone}", "acs": saml["acsUrl"], "audience": saml["spEntityId"]},
    )
    r = await signin.post_form(page.text, to="/v1/auth/saml/acs")
    assert dict(httpx.URL(r.headers["location"]).params) == {"error": "sign_in_refused"}
