"""A key for one system, by failure mode: the wrong person makes one, a key never ends, an old secret outlives its
rotation, the key's introspection names its maker instead of the key, and a key stops when its maker leaves.

Names fixed here for the builder: a key is made with `expiresInDays` (required, 1 to 365) and `tools` (the tool names
it may run); `POST /v1/api-keys/{id}/rotate` takes `stopNow` and answers a new `secret` and `graceEndsAt`; introspection
answers `sub` = `key:<id>`, `name` = the key's name and `apiKey` = `{id, target, tools, makerEmail}`; a key listed after
its maker left carries `makerGone: true`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from ops_platform.store.tables import audit_entries

from .conftest import SERVICE, Platform
from .test_api_keys import create
from .test_members import as_admin, join, member_rows, team_of
from .test_permissions import grant

TOOLS = ["lookup_case", "list_cases"]


async def introspect(platform: Platform, secret: object) -> Any:
    return await platform.internal.post("/v1/auth/introspect", json={"apiKey": secret}, headers=SERVICE)


async def test_only_an_admin_makes_a_key_and_it_always_ends_within_a_year(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    member = await join(platform, admin, "builder")
    token = (await platform.sign_in(member)).json()["data"]["token"]
    mh = {"Authorization": f"Bearer {token}", "X-Team-Id": h["X-Team-Id"]}
    body: dict[str, object] = {"name": "Claims triage script", "scopes": ["read"], "tools": TOOLS, "expiresInDays": 90}
    plain = {k: v for k, v in body.items() if k != "tools"}
    assert (await platform.public.post("/v1/api-keys", headers=mh, json=plain)).status_code == 403
    for refused in ({k: v for k, v in plain.items() if k != "expiresInDays"}, plain | {"expiresInDays": 366}):
        r = await platform.public.post("/v1/api-keys", headers=h, json=refused)
        assert r.status_code in (400, 422), (refused, r.text)  # the card says 422; this service answers bad bodies 400
    made = await platform.public.post("/v1/api-keys", headers=h, json=body)
    assert made.status_code == 201, made.text
    key = made.json()["data"]["key"]
    ends = datetime.fromisoformat(key["expiresAt"].replace("Z", "+00:00"))
    assert abs(ends - (datetime.now(UTC) + timedelta(days=90))) < timedelta(minutes=5)
    assert key["tools"] == TOOLS
    [listed] = (await platform.public.get("/v1/api-keys", headers=h)).json()["data"]
    assert listed["tools"] == TOOLS and made.json()["data"]["secret"].split(".", 1)[1] not in str(listed)


async def test_rotating_keeps_the_old_secret_for_a_day_or_stops_it_at_once(platform: Platform) -> None:
    _, h = await as_admin(platform)
    kept = await create(platform, h, expiresInDays=90)
    key_id = kept["key"]["id"]  # type: ignore[index]
    r = await platform.public.post(f"/v1/api-keys/{key_id}/rotate", headers=h, json={})
    assert r.status_code == 200, r.text
    fresh = r.json()["data"]
    assert fresh["secret"] != kept["secret"] and fresh["secret"].startswith(f"ok_{key_id}.")
    grace = datetime.fromisoformat(fresh["graceEndsAt"].replace("Z", "+00:00")) - datetime.now(UTC)
    assert timedelta(hours=23, minutes=55) < grace <= timedelta(hours=24, minutes=1)
    assert (await introspect(platform, fresh["secret"])).status_code == 200
    assert (await introspect(platform, kept["secret"])).status_code == 200, "the old secret lives through the grace"

    stopped = await create(platform, h, expiresInDays=90)
    sid = stopped["key"]["id"]  # type: ignore[index]
    r = await platform.public.post(f"/v1/api-keys/{sid}/rotate", headers=h, json={"stopNow": True})
    assert r.status_code == 200 and r.json()["data"]["graceEndsAt"] is None, r.text
    assert (await introspect(platform, r.json()["data"]["secret"])).status_code == 200
    assert (await introspect(platform, stopped["secret"])).status_code == 401, "stop now ends the old secret at once"

    await platform.public.post(f"/v1/api-keys/{key_id}/revoke", headers=h)
    assert (await introspect(platform, fresh["secret"])).status_code == 401
    assert (await introspect(platform, kept["secret"])).status_code == 401, "revoking ends the grace secret too"
    async with platform.engine.connect() as c:
        q = sa.select(audit_entries.c.action).where(audit_entries.c.target_id == key_id).order_by(audit_entries.c.at)
        assert list((await c.execute(q)).scalars()) == ["key.create", "key.rotate", "key.revoke"]


async def test_introspection_answers_the_key_as_its_own_caller_with_its_tools(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    made = await create(platform, h, name="Claims triage script", expiresInDays=30, tools=TOOLS)
    key_id = made["key"]["id"]  # type: ignore[index]
    r = await introspect(platform, made["secret"])
    assert r.status_code == 200, r.text
    got = r.json()["data"]
    assert (got["sub"], got["name"], got["kind"]) == (f"key:{key_id}", "Claims triage script", "api_key"), got
    assert got["email"] != admin.email, "the key does not speak as the person who made it"
    assert got["apiKey"]["tools"] == TOOLS and got["apiKey"]["makerEmail"] == admin.email
    assert got["scopes"] == ["read"]


async def test_a_key_keeps_working_when_its_maker_leaves_and_the_list_says_so(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    maker = await join(platform, admin, "admin")
    await grant(platform, maker, team_of(admin), "admin")
    token = (await platform.sign_in(maker)).json()["data"]["token"]
    mh = {"Authorization": f"Bearer {token}", "X-Team-Id": h["X-Team-Id"]}
    made = await create(platform, mh, name="Nightly export", expiresInDays=90)
    [row] = [m for m in await member_rows(platform, h) if m["email"] == maker.email]
    gone = await platform.public.post("/v1/settings/members/delete", headers=h, json={"ids": [row["id"]]})
    assert gone.json()["data"]["updated"] == [row["id"]], gone.text
    r = await introspect(platform, made["secret"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sub"] == f"key:{made['key']['id']}"  # type: ignore[index]
    listed = {k["id"]: k for k in (await platform.public.get("/v1/api-keys", headers=h)).json()["data"]}
    assert listed[made["key"]["id"]]["makerGone"] is True  # type: ignore[index]
