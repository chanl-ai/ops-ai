"""A SAML provider's certificates: read from its metadata, several at once through a rollover, an expired one named
as expired, a refresh that adds signers only for the same entity, and the daily watch that warns Security admins."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa

from ops_platform.signin_settings import ProviderMetadata
from ops_platform.signin_watch import SecurityNotices, SignInWatch
from ops_platform.sso import guarded_get
from ops_platform.store.holders import HolderStore
from ops_platform.store.identity import IdentityStore
from ops_platform.store.signin import SignInStore
from ops_platform.store.tables import signin_certificates
from ops_platform.store.workspace import WorkspaceStore
from ops_service_kit.public_address import PublicFetch

from .conftest import CONSOLE, IDP, SignInRig


async def _metadata_provider(rig: SignInRig, domain: str, name: str = "bank") -> tuple[str, httpx.Response]:
    provider = f"sip_{name}_{domain.split('.', maxsplit=1)[0]}"
    body = {
        "kind": "saml",
        "label": "Bank SAML",
        "domains": [domain],
        "saml": {
            "idpEntityId": f"{IDP}/saml/{name}",
            "ssoUrl": f"{IDP}/saml/{name}/sso",
            "metadataUrl": f"{IDP}/saml/{name}/metadata",
        },
        "jit": {"team": rig.ops_team, "role": "chat_user"},
    }
    return provider, await rig.configure(provider, body)


async def _saml_of(rig: SignInRig, provider: str) -> dict[str, Any]:
    listed = (await rig.public.get("/v1/settings/sign-in/providers", headers=rig.admin)).json()["data"]
    return next(p for p in listed if p["id"] == provider)["saml"]


@pytest.fixture
async def watch(signin: SignInRig, database_url: str) -> AsyncIterator[SignInWatch]:
    store = IdentityStore.open(database_url)
    signins = SignInStore(store.db)
    fetch = PublicFetch(resolver=signin.resolver, require_https=False)
    async with httpx.AsyncClient(transport=signin.idp._transport) as http:  # pyright: ignore[reportPrivateUsage]
        yield SignInWatch(
            signins,
            ProviderMetadata(signins, lambda url: guarded_get(http, fetch, url)),
            SecurityNotices(signins, HolderStore(store.db), WorkspaceStore(store.db), signin.mail, CONSOLE),
        )
    await store.close()


async def test_a_rollover_listed_in_metadata_signs_in_with_the_new_certificate(signin: SignInRig) -> None:
    await signin.idp.post("/saml/roll/rollover")
    provider, r = await _metadata_provider(signin, f"roll.{signin.zone}", name="roll")
    assert r.status_code == 200, r.text
    assert len((await _saml_of(signin, provider))["certificates"]) == 2
    done = await signin.sign_in_sso(f"ana@roll.{signin.zone}")
    assert done.completed is not None and done.completed.status_code == 200, done.location


async def test_a_response_signed_under_an_expired_certificate_says_so(signin: SignInRig) -> None:
    provider = await signin.saml(f"exp.{signin.zone}", name="exp")
    expired = (await signin.idp.post("/saml/exp/expire")).json()["certificate"]
    # The only trusted certificate is now one for the same key that ended yesterday.
    async with signin.engine.begin() as c:
        await c.execute(
            signin_certificates.update().where(signin_certificates.c.provider_id == provider).values(pem=expired)
        )
    done = await signin.sign_in_sso(f"ana@exp.{signin.zone}")
    assert done.query == {"error": "certificate_expired"} and done.completed is None


async def test_saving_only_expired_certificates_is_refused(signin: SignInRig) -> None:
    expired = (await signin.idp.post("/saml/old/expire")).json()["certificate"]
    body = {
        "kind": "saml",
        "label": "Old",
        "domains": [f"old.{signin.zone}"],
        "saml": {"idpEntityId": f"{IDP}/saml/old", "ssoUrl": f"{IDP}/saml/old/sso", "certificate": expired},
    }
    r = await signin.configure("sip_old", body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "certificate_expired", r.text


async def test_a_refresh_naming_another_entity_adds_no_signer(signin: SignInRig) -> None:
    provider, r = await _metadata_provider(signin, f"hij.{signin.zone}", name="hij")
    assert r.status_code == 200, r.text
    await signin.idp.put("/saml/hij/metadata-entity", json={"entityId": "https://attacker.example/saml"})
    r = await signin.public.post(f"/v1/settings/sign-in/providers/{provider}/refresh", headers=signin.admin)
    assert r.status_code == 200, r.text
    saml = r.json()["data"]["saml"]
    assert len(saml["certificates"]) == 1 and "attacker.example" in (saml["metadataError"] or "")


async def test_metadata_on_an_inside_address_is_refused(signin: SignInRig) -> None:
    signin.resolver.answers["idp.test"] = ["169.254.169.254"]
    r = await signin.public.post(
        "/v1/settings/sign-in/providers/metadata", json={"url": f"{IDP}/saml/bank/metadata"}, headers=signin.admin
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "metadata_address", r.text


async def test_the_daily_watch_adds_a_new_certificate_and_warns_at_30_and_7_days(
    signin: SignInRig, watch: SignInWatch
) -> None:
    provider, r = await _metadata_provider(signin, f"wat.{signin.zone}", name="wat")
    assert r.status_code == 200, r.text
    await signin.idp.post("/saml/wat/rollover")
    before = len(signin.mail.sent)
    await watch.once()
    assert len((await _saml_of(signin, provider))["certificates"]) == 2
    told = [m for m in list(signin.mail.sent.values())[before:] if "new signing certificate" in m.subject]
    assert told, [m.subject for m in signin.mail.sent.values()]

    async def ends_in(days: int) -> None:
        end = (datetime.now(UTC) + timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        async with signin.engine.begin() as c:
            await c.execute(
                signin_certificates.update().where(signin_certificates.c.provider_id == provider).values(not_after=end)
            )

    def ending() -> int:
        return sum("ends soon" in m.subject for m in signin.mail.sent.values())

    await ends_in(20)
    await watch.once()
    first = ending()
    assert first >= 1
    assert await watch.once() == 0, "a warning is sent once per threshold"
    assert ending() == first
    await ends_in(5)
    await watch.once()
    assert ending() > first
    async with signin.engine.begin() as c:
        warned = (
            await c.execute(
                sa.select(signin_certificates.c.warned).where(signin_certificates.c.provider_id == provider)
            )
        ).scalars().all()  # fmt: skip
    assert set(warned) == {"7"}
