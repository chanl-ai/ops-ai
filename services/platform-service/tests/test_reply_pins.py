"""The replies of the sign-in, session, member, team, role and key routes, key by key and value by value, by failure
mode: a store row that changes its shape (a column renamed, a JSON column left as text, a time written another way)
changing what a caller is sent, or a token carrying other claims or another lifetime. Generated ids, times and this
run's addresses are replaced by their kind; a token is compared as its decoded claims, with its lifetime kept."""

from __future__ import annotations

import base64
import json
import re
import secrets
from pathlib import Path
from typing import Any, cast

import httpx

from ops_identity import mint_service_token

from .conftest import CALLER, DEMO_PASSWORD, Platform
from .test_permissions import grant

PINS = Path(__file__).parent / "fixtures" / "reply-pins.json"
_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
_ID = re.compile(r"([a-z]+)_[0-9a-f]{12}(?![0-9a-f])")
_TIME_CLAIMS = {"iat", "exp", "nbf", "auth_time"}
# The random half of a refresh token or key secret.
_SECRET = re.compile(r"\.[A-Za-z0-9_-]{32,}$")
# An invitation token: its kind, then random text.
_TOKEN = re.compile(r"^([a-z]+)_[A-Za-z0-9_-]{24,}$")


def _claims(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    held = cast(dict[str, Any], body)
    out: dict[str, Any] = {k: "<epoch>" if k in _TIME_CLAIMS else v for k, v in held.items()}
    if "exp" in held and "iat" in held:
        out["<lifetime>"] = int(held["exp"]) - int(held["iat"])
    return out


def scrubbed(value: Any, run: str) -> Any:
    """`value` with every time and generated id replaced by its kind, this run's zone by `<run>`, and a signed token
    by its claims, so two runs answer the same."""
    if isinstance(value, dict):
        return {scrubbed(k, run): scrubbed(v, run) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [scrubbed(v, run) for v in cast(list[Any], value)]
    if isinstance(value, str):
        if (claims := _claims(value)) is not None:
            return {"<token>": scrubbed(claims, run)}
        if m := _TIME.match(value):
            return f"<time{m.group(2) or ''}>"
        if m := _TOKEN.match(value):
            return f"<{m.group(1)}-token>"
        value = _SECRET.sub(".<secret>", value.replace(run, "<run>"))
        return _ID.sub(lambda m: f"<{m.group(1)}>", value)
    return value


def data(r: httpx.Response, run: str, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return scrubbed(r.json()["data"], run) if r.content else None


async def test_the_identity_member_role_and_key_replies_keep_every_key_and_value(platform: Platform) -> None:
    run = secrets.token_hex(4)
    owner = await platform.person(roles=("admin",), email=f"owner@{run}.bank.test")
    await grant(platform, owner, "*", "admin")
    team = next(iter(owner.teams))
    # Made before the owner signs in: a workspace admin's token reaches the teams that exist at sign-in.
    member = await platform.person(roles=("viewer",), tenant_id=owner.tenant_id, email=f"member@{run}.bank.test")
    seen: dict[str, Any] = {}
    c = platform.public
    signed = await c.post("/v1/auth/sign-in", json={"email": owner.email, "password": DEMO_PASSWORD})
    seen["signIn"] = data(signed, run)
    session = signed.json()["data"]
    h = {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}
    seen["session"] = data(await c.get("/v1/auth/session", headers=h), run)
    refreshed = await c.post("/v1/auth/refresh", json={"refreshToken": session["refreshToken"]})
    seen["refresh"] = data(refreshed, run)
    h["Authorization"] = f"Bearer {refreshed.json()['data']['token']}"
    seen["me"] = data(await c.get("/v1/me", headers=h), run)
    seen["permissions"] = data(await c.get("/v1/me/permissions", headers=h), run)
    # The shell reads what a person may do from /v1/me, the same answer the permissions route gives.
    assert seen["me"]["permissions"] == seen["permissions"]
    seen["teams"] = data(await c.get("/v1/teams", headers=h), run)
    invite = {"emails": [f"new.one@{run}.bank.test"], "role": "viewer"}
    seen["invite"] = data(await c.post("/v1/settings/members/invite", headers=h, json=invite), run)
    listed = await c.get("/v1/settings/members", headers=h)
    seen["members"] = data(listed, run)
    invited = next(m["id"] for m in listed.json()["data"]["data"] if m["email"] != owner.email)
    change = {"ids": [invited], "role": "builder"}
    seen["memberRole"] = data(await c.post("/v1/settings/members/role", headers=h, json=change), run)
    seen["roles"] = data(await c.get("/v1/roles", headers=h), run)
    seen["role"] = data(await c.get("/v1/roles/builder", headers=h), run)
    desk = {"name": "Case desk", "permissions": [{"area": "agents", "action": "view", "scope": "all"}]}
    made = await c.post("/v1/roles", headers=h, json=desk)
    seen["roleCreate"] = data(made, run, 201)
    th = {**h, "X-Team-Id": next(iter(member.teams))}
    path = f"/v1/people/{member.user_id}/role-grants"
    given = await c.post(path, headers=th, json={"roleId": made.json()["data"]["id"]})
    seen["roleGive"] = data(given, run, 201)
    seen["roleGrants"] = data(await c.get(path, headers=th), run)
    seen["roleTake"] = data(await c.delete(f"{path}/{given.json()['data']['id']}", headers=th), run, 204)
    seen["roleGrantsAfter"] = data(await c.get(path, headers=th), run)
    key = await c.post("/v1/api-keys", headers=h, json={"name": "ci", "scopes": ["read"]})
    seen["keyCreate"] = data(key, run, 201)
    seen["keys"] = data(await c.get("/v1/api-keys", headers=h), run)
    seen["keySummaries"] = data(await c.get("/v1/api-key-summaries", headers=h), run)
    revoked = await c.post(f"/v1/api-keys/{key.json()['data']['key']['id']}/revoke", headers=h)
    seen["keyRevoke"] = data(revoked, run)
    service = mint_service_token(CALLER, service="agents", audience="platform", tenant_id=owner.tenant_id, ttl_s=60)
    version = await platform.internal.get("/v1/permission-version", headers={"Authorization": f"Bearer {service}"})
    seen["permissionVersion"] = data(version, run)
    seen["signOut"] = data(await c.post("/v1/auth/sign-out", headers=h), run, 204)
    gone = await c.get("/v1/auth/session", headers=h)
    seen["sessionAfter"] = [gone.status_code, scrubbed(gone.json(), run)]
    assert seen == json.loads(PINS.read_text()), json.dumps(seen, indent=2, sort_keys=True)
