"""uc-118 roles and permissions, api layer: docs/usecases/platform-service/roles-and-permissions.md."""

from __future__ import annotations

import base64
import json
from typing import Any

from usecase_harness import check, data, finish, platform

PASSWORD = "northfield-demo"


def sign_in(api, email: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    r = api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    check(f"{email} signs in", r.status_code == 200, r.status_code)
    return {"Authorization": f"Bearer {data(r)['token'] if r.status_code == 200 else ''}"}


def version(h: dict[str, str]) -> int:
    part = h["Authorization"].split(" ")[1].split(".")[1]
    return int(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("perm_version", -1))


def held(view: dict[str, Any], team: str) -> dict[str, dict[str, Any]]:
    rows = next((t["permissions"] for t in view.get("teams", []) if t["teamId"] == team), [])
    return {f"{p['area']}.{p['action']}": p for p in rows}


def names(p: dict[str, Any] | None) -> list[str]:
    return [r["name"] for r in (p or {}).get("roles", [])]


with platform() as (api, _internal):
    priya = sign_in(api, "p.shah@harborpine.example")
    r = api.get("/v1/roles", headers=priya)
    listed = [x["id"] for x in data(r)] if r.status_code == 200 else []
    check(
        # Owner, the workspace's own role (platform migration 0026), joins the six team roles.
        "seven built-in roles are listed",
        listed == ["admin", "builder", "reviewer", "viewer", "security_admin", "chat_user", "owner"],
        listed,
    )
    r = api.get("/v1/roles/chat_user", headers=priya)
    grid = {row["area"]: row["actions"] for row in data(r)["grid"]} if r.status_code == 200 else {}
    check(
        # Correcting one's own memories is memory.edit, own (platform migration 0015).
        "Chat user's grid holds chat, its own threads, and its own memories only",
        grid.get("chat", {}).get("view") == "own"
        and grid.get("chat", {}).get("run") == "all"
        and grid.get("memory", {}).get("edit") == "own"
        and all(v is None for area, acts in grid.items() if area not in ("chat", "memory") for v in acts.values())
        and all(v is None for action, v in grid.get("memory", {}).items() if action != "edit"),
        r.text[:200],
    )

    mine = held(data(api.get("/v1/me/permissions", headers=priya)), "team_ops")
    check(
        "Priya manages access in Operations as Admin",
        names(mine.get("access.manage")) == ["Admin"],
        mine.get("access.manage"),
    )
    # A team admin holds every cell (platform migration 0016); egress is a Security-team-only cell, so Priya's
    # holds only in the Security team, where she is not.
    check(
        "Priya changes egress only in the Security team, where she is not",
        (mine.get("secrets_egress.manage") or {}).get("securityTeamOnly") is True,
        mine.get("secrets_egress.manage"),
    )

    sam = sign_in(api, "s.adeyemi@harborpine.example")
    sec = held(data(api.get("/v1/me/permissions", headers=sam)), "team_security")
    check(
        "Sam changes egress as Security admin, in the Security team",
        "Security admin" in names(sec.get("secrets_egress.manage"))
        and sec.get("secrets_egress.manage", {}).get("securityTeamOnly") is True,
        sec.get("secrets_egress.manage"),
    )

    r = api.get("/v1/people/usr_builder/permissions", headers=priya)
    james = held(data(r), "team_ops") if r.status_code == 200 else {}
    check(
        # A builder changes any of the team's knowledge (platform migration 0009), not only their own.
        "James, a builder, creates agents, changes the team's knowledge and decides nothing",
        "agents.create" in james
        and james.get("knowledge.edit", {}).get("scope") == "all"
        and "agents.decide" not in james,
        r.text[:200],
    )
    r = api.get("/v1/people/usr_security_admin/permissions", headers=priya)
    check("a person who shares no team with Priya is not found", r.status_code == 404, r.status_code)

    # Non-vacuous: James creates agents before the change, so its absence after is the change's doing.
    before = sign_in(api, "j.richardson@harborpine.example")
    rows = data(api.get("/v1/settings/members", headers=priya))["data"]
    member = next(m["id"] for m in rows if m["email"] == "j.richardson@harborpine.example")
    r = api.post("/v1/settings/members/role", headers=priya, json={"ids": [member], "role": "viewer"})
    check("Priya makes James a viewer", r.status_code == 200 and data(r)["updated"] == [member], r.text[:200])
    after = sign_in(api, "j.richardson@harborpine.example")
    now = held(data(api.get("/v1/me/permissions", headers=after)), "team_ops")
    check(
        "James's next token carries a newer permission version",
        version(after) > version(before),
        (version(before), version(after)),
    )
    check(
        "James no longer creates agents and reads as Viewer",
        "agents.create" not in now and names(now.get("agents.view")) == ["Viewer"],
        names(now.get("agents.view")),
    )
    r = api.post("/v1/settings/members/role", headers=priya, json={"ids": [member], "role": "builder"})
    check("James is a builder again", r.status_code == 200 and data(r)["updated"] == [member], r.text[:200])

finish()
