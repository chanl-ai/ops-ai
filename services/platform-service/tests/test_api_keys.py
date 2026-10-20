"""API keys (P11, I4, I11, I12), by failure mode: a non-admin mints a key, the secret shows up again after creation,
a revoked or expired key still resolves, another team's key is revoked from this one, the hash is compared with
`==`, and secret material reaches a log line."""

from __future__ import annotations

import hmac
import logging

import pytest
import sqlalchemy as sa

from ops_platform.store.tables import api_keys, audit_entries

from .conftest import SERVICE, Platform
from .test_members import as_admin, join


async def create(platform: Platform, h: dict[str, str], **body: object) -> dict[str, object]:
    r = await platform.public.post("/v1/api-keys", headers=h, json={"name": "ci", "scopes": ["read"], **body})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def introspect(platform: Platform, secret: str) -> int:
    r = await platform.internal.post("/v1/auth/introspect", json={"apiKey": secret}, headers=SERVICE)
    return r.status_code


async def test_an_admin_creates_a_key_whose_secret_shows_once(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h, scopes=["read", "write"])
    secret = str(made["secret"])
    assert secret.startswith("ok_") and await introspect(platform, secret) == 200
    r = await platform.public.get("/v1/api-keys", headers=h)
    assert r.status_code == 200, r.text
    [listed] = r.json()["data"]
    assert listed["id"] == made["key"]["id"] and listed["scopes"] == ["read", "write"]  # type: ignore[index]
    assert secret.split(".", 1)[1] not in r.text and "secret" not in listed


async def test_only_an_admin_creates_or_revokes(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    made = await create(platform, h)
    builder = await join(platform, admin, "builder")
    token = (await platform.sign_in(builder)).json()["data"]["token"]
    bh = {"Authorization": f"Bearer {token}", "X-Team-Id": h["X-Team-Id"]}
    r = await platform.public.post("/v1/api-keys", headers=bh, json={"name": "x", "scopes": ["read"]})
    assert r.status_code == 403
    r = await platform.public.post(f"/v1/api-keys/{made['key']['id']}/revoke", headers=bh)  # type: ignore[index]
    assert r.status_code == 403


async def test_a_revoked_key_stops_at_once(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h)
    key_id = made["key"]["id"]  # type: ignore[index]
    r = await platform.public.post(f"/v1/api-keys/{key_id}/revoke", headers=h)
    assert r.status_code == 200 and r.json()["data"]["status"] == "revoked"
    assert await introspect(platform, str(made["secret"])) == 401


async def test_an_expired_key_is_refused(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h, expiresInDays=30)
    assert made["key"]["expiresAt"]  # type: ignore[index]
    async with platform.engine.begin() as c:
        await c.execute(
            api_keys.update().where(api_keys.c.id == made["key"]["id"]).values(expires_at="2020-01-01T00:00:00.000Z")  # type: ignore[index]
        )
    assert await introspect(platform, str(made["secret"])) == 401


async def test_use_moves_last_used_at(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h)
    assert made["key"].get("lastUsedAt") is None  # type: ignore[union-attr]
    await introspect(platform, str(made["secret"]))
    [listed] = (await platform.public.get("/v1/api-keys", headers=h)).json()["data"]
    assert listed["lastUsedAt"]


async def test_another_teams_key_is_not_found_here(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    neighbour = await platform.person(roles=("admin",), tenant_id=admin.tenant_id)
    token = (await platform.sign_in(neighbour)).json()["data"]["token"]
    other = {"Authorization": f"Bearer {token}", "X-Team-Id": next(iter(neighbour.teams))}
    theirs = await create(platform, other)
    r = await platform.public.post(f"/v1/api-keys/{theirs['key']['id']}/revoke", headers=h)  # type: ignore[index]
    assert r.status_code == 404
    assert await introspect(platform, str(theirs["secret"])) == 200


async def test_the_hash_is_compared_in_constant_time(platform: Platform, monkeypatch: pytest.MonkeyPatch) -> None:

    _, h = await as_admin(platform)
    made = await create(platform, h)
    seen: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a: object, b: object) -> bool:
        seen.append((a, b))
        return real(a, b)  # type: ignore[arg-type]

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert await introspect(platform, str(made["secret"])) == 200
    # Both sides are SHA-256 hex digests: the presented secret's hash against the stored one.
    assert any(len(str(a)) == 64 and len(str(b)) == 64 for a, b in seen)


async def test_no_secret_material_reaches_a_log(
    platform: Platform, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h)
    secret = str(made["secret"]).split(".", 1)[1]
    caplog.set_level(logging.DEBUG)
    for presented in (str(made["secret"]), str(made["secret"])[:-3] + "xyz", f"ok_key_nothere.{secret}"):
        await introspect(platform, presented)
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err
    for fragment in (secret, secret[:4], secret[-4:]):
        assert fragment not in logged


async def test_a_body_with_unknown_fields_or_scopes_is_refused(platform: Platform) -> None:
    _, h = await as_admin(platform)
    bodies: list[dict[str, object]] = [
        {"name": "x", "scopes": ["admin"]},
        {"name": "x", "scopes": ["read"], "teamId": h["X-Team-Id"]},
        {"name": "x", "scopes": []},
    ]
    for body in bodies:
        r = await platform.public.post("/v1/api-keys", headers=h, json=body)
        assert r.status_code == 400, body


async def test_creating_and_revoking_are_audited(platform: Platform) -> None:
    _, h = await as_admin(platform)
    made = await create(platform, h)
    key_id = str(made["key"]["id"])  # type: ignore[index]
    await platform.public.post(f"/v1/api-keys/{key_id}/revoke", headers=h)
    async with platform.engine.connect() as c:
        actions = (
            (
                await c.execute(
                    sa.select(audit_entries.c.action)
                    .where(audit_entries.c.target_id == key_id)
                    .order_by(audit_entries.c.at)
                )
            )
            .scalars()
            .all()
        )
    assert list(actions) == ["key.create", "key.revoke"]
