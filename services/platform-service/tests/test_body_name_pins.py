"""The body names the sign-in, session, member, role, grant and key routes accept, by failure mode: a body model moved
onto another base that stops taking the snake name a caller sends today, or starts taking a field it refused. Each
route is sent its camel names, its snake names, and one unknown field; the status and error code of each are pinned."""

from __future__ import annotations

import secrets
from typing import Any, cast

import httpx

from .conftest import DEMO_PASSWORD, Platform
from .test_permissions import grant


def _seen(r: httpx.Response) -> list[Any]:
    if r.status_code < 400:
        return [r.status_code, None]
    body = cast(dict[str, Any], r.json())
    return [r.status_code, cast(dict[str, Any], body["error"])["code"]]


async def test_each_route_takes_camel_and_snake_names_and_refuses_an_unknown_field(platform: Platform) -> None:
    run = secrets.token_hex(4)
    owner = await platform.person(roles=("admin",), email=f"owner@{run}.bank.test")
    await grant(platform, owner, "*", "admin")
    team = next(iter(owner.teams))
    member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id, email=f"member@{run}.bank.test")
    c = platform.public
    seen: dict[str, list[Any]] = {}

    login = {"email": owner.email, "password": DEMO_PASSWORD}
    seen["signIn.unknown"] = _seen(await c.post("/v1/auth/sign-in", json={**login, "remember": True}))
    signed = await c.post("/v1/auth/sign-in", json=login)
    seen["signIn"] = _seen(signed)
    refresh = signed.json()["data"]["refreshToken"]
    seen["refresh.unknown"] = _seen(await c.post("/v1/auth/refresh", json={"refreshToken": refresh, "x": 1}))
    snake = await c.post("/v1/auth/refresh", json={"refresh_token": refresh})
    seen["refresh.snake"] = _seen(snake)
    camel = await c.post("/v1/auth/refresh", json={"refreshToken": snake.json()["data"]["refreshToken"]})
    seen["refresh.camel"] = _seen(camel)
    h = {"Authorization": f"Bearer {camel.json()['data']['token']}", "X-Team-Id": team}

    invite = {"emails": [f"a@{run}.bank.test"], "role": "viewer"}
    seen["invite.unknown"] = _seen(await c.post("/v1/settings/members/invite", headers=h, json={**invite, "x": 1}))
    seen["invite"] = _seen(await c.post("/v1/settings/members/invite", headers=h, json=invite))
    listed = (await c.get("/v1/settings/members", headers=h)).json()["data"]["data"]
    invited = next(m["id"] for m in listed if m["email"] == f"a@{run}.bank.test")
    change = {"ids": [invited], "role": "builder"}
    seen["memberRole.unknown"] = _seen(await c.post("/v1/settings/members/role", headers=h, json={**change, "x": 1}))
    seen["memberRole"] = _seen(await c.post("/v1/settings/members/role", headers=h, json=change))

    cells = [{"area": "agents", "action": "view", "scope": "all"}]
    seen["roleCreate.unknown"] = _seen(await c.post("/v1/roles", headers=h, json={"name": "A", "x": 1}))
    seen["roleCreate.camel"] = _seen(await c.post("/v1/roles", headers=h, json={"name": "B", "copyOf": "viewer"}))
    seen["roleCreate.snake"] = _seen(await c.post("/v1/roles", headers=h, json={"name": "C", "copy_of": "viewer"}))
    made = await c.post("/v1/roles", headers=h, json={"name": "D", "permissions": cells})
    role_id = made.json()["data"]["id"]

    th = {**h, "X-Team-Id": next(iter(member.teams))}
    path = f"/v1/people/{member.user_id}/role-grants"
    seen["roleGive.unknown"] = _seen(await c.post(path, headers=th, json={"roleId": role_id, "x": 1}))
    snake_grant = await c.post(path, headers=th, json={"role_id": role_id})
    seen["roleGive.snake"] = _seen(snake_grant)
    await c.delete(f"{path}/{snake_grant.json()['data']['id']}", headers=th)
    seen["roleGive.camel"] = _seen(await c.post(path, headers=th, json={"roleId": role_id}))

    key = {"name": "ci", "scopes": ["read"]}
    seen["keyCreate.unknown"] = _seen(await c.post("/v1/api-keys", headers=h, json={**key, "x": 1}))
    seen["keyCreate.camel"] = _seen(await c.post("/v1/api-keys", headers=h, json={**key, "expiresInDays": 30}))
    seen["keyCreate.snake"] = _seen(await c.post("/v1/api-keys", headers=h, json={**key, "expires_in_days": 30}))

    assert seen == {
        "signIn.unknown": [400, "validation_failed"],
        "signIn": [200, None],
        "refresh.unknown": [400, "validation_failed"],
        "refresh.snake": [200, None],
        "refresh.camel": [200, None],
        "invite.unknown": [400, "validation_failed"],
        "invite": [200, None],
        "memberRole.unknown": [400, "validation_failed"],
        "memberRole": [200, None],
        "roleCreate.unknown": [400, "validation_failed"],
        "roleCreate.camel": [201, None],
        "roleCreate.snake": [201, None],
        "roleGive.unknown": [400, "validation_failed"],
        "roleGive.snake": [201, None],
        "roleGive.camel": [201, None],
        "keyCreate.unknown": [400, "validation_failed"],
        "keyCreate.camel": [201, None],
        "keyCreate.snake": [201, None],
    }, seen
