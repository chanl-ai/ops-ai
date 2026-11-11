"""uc-609, api layer: docs/usecases/tools-service/plugin-updates.md, stories S1 to S4.

platform-service signs the seeded people in; agents-service holds the team's agents;
tools-service runs with plugins on and the plugin_updates flag on, first with the fields desk at 0.1.0
(services/tools-service/tests/plugin_fields/fields_desk), then restarted on the same database with it at 0.2.0
(services/tools-service/tests/plugin_versions/fields_desk): find takes pending and moves, post_message moves, transfer
is gone and close_case is new. The fake system (docs/usecases/lib/fake_multi_auth.py) records the path each call
reached. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
from fake_multi_auth import SECRETS, multi_auth
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
)
from usecase_harness import ROOT as REPO

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
ID = "test.fields"
V1 = REPO / "services/tools-service/tests/plugin_fields/fields_desk"
V2 = REPO / "services/tools-service/tests/plugin_versions/fields_desk"
TENANT: dict[str, str] = {}


def call(gw: httpx.Client, tool: str, args: dict[str, Any], team: str = "team_ops") -> httpx.Response:
    """A call as agents-service makes it for a run in `team` with nobody behind it."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team=team)
    body = {"tool": f"fields_{tool}", "input": args, "key": uuid4().hex, "runContext": {"environment": "live"}}
    return gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": team})


def output(r: httpx.Response) -> dict[str, Any]:
    got = data(r) if r.status_code == 200 else None
    return dict((got or {}).get("output") or {}) if isinstance(got, dict) else {}


def error(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        return {}
    found = (body.get("data") or {}).get("output", {}).get("error") if body.get("data") else body.get("error")
    return dict(found or {})


def reached(fake: Any) -> str:
    rows = [c for c in fake.state()["calls"] if c["method"] == "fields"]
    return str(rows[-1].get("path") or "") if rows else ""


def review(gw: httpx.Client, who: dict[str, str]) -> dict[str, Any]:
    return dict(data(gw.get(f"/v1/apps/plugin:{ID}/update", headers=who)) or {})


with ExitStack() as stack:
    m = stack.enter_context(multi_auth())
    fake = m["fake"]
    api, _ = stack.enter_context(platform())
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_platform")
    base = {**m["settings"], **AUTH, "OPS_PLUGINS": "true", "OPS_FLAGS": '["plugin_updates"]'}

    with tools({**base, "OPS_PLUGIN_PATHS": json.dumps([str(V1)])}) as gw:
        # 1. Both teams turn the fields desk on at 0.1.0; each records the version it took.
        for h in m["hosts"]:
            gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-609"}, headers=sam)
        gw.post("/v1/egress/ranges", json={"value": m["range"], "note": "uc-609"}, headers=sam)
        on = [
            gw.put(
                f"/v1/apps/plugin:{ID}/team",
                json={"enabled": True, "credentials": {"token": SECRETS["token"]}},
                headers=who,
            )
            for who in (priya, wanjiru)
        ]
        # A new app starts with its reads added; each team adds the two writes it calls, as an admin does from the Tools tab.
        for who in (priya, wanjiru):
            added = gw.post(
                f"/v1/apps/plugin:{ID}/tools", json={"tools": ["fields_post_message", "fields_transfer"]}, headers=who
            )
            check("1 the team adds the two write tools (200)", added.status_code == 200, added.text[:200])
        first = [review(gw, priya), review(gw, wanjiru)]
        check(
            "1 both teams turn the fields desk on and each runs 0.1.0 with no update waiting",
            all(r.status_code == 200 for r in on)
            and all(
                r.get("version") == "0.1.0" and r.get("available") is False and r.get("tools") == [] for r in first
            ),
            {"on": [r.text[:200] for r in on], "review": first},
        )

    ag = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}", env=AUTH))
    with tools({**base, "OPS_PLUGIN_PATHS": json.dumps([str(V2)])}) as gw:
        # 2. The operator installs 0.2.0. Team ops keeps calling 0.1.0's tools exactly as that version declared them.
        posted = call(gw, "post_message", {"channel": "C1", "text": "Card 1042"})
        posted_at = reached(fake)
        moved = call(gw, "transfer", {"amount": 25, "to": "acct-7"})
        listed = call(gw, "find", {"status": "open"})
        found_at = reached(fake)
        check(
            "2 after the upgrade team ops' changed tool sends 0.1.0's request, its removed tool still answers, and its "
            "query tool reads the old address",
            output(posted).get("ok") is True and posted_at == "/fields/chat.postMessage"
            and output(moved).get("amount") == 25 and len(fake.state()["transfers"]) == 1
            and output(listed).get("method") == "fields" and found_at == "/fields/search",
            {"posted": (posted.text[:200], posted_at), "moved": moved.text[:200],
             "found": (listed.text[:200], found_at)},
        )  # fmt: skip

        # 3. A value only 0.2.0 allows, and a tool only 0.2.0 has, are refused for team ops; nothing reaches the system.
        before = len(fake.state()["calls"])
        pending = call(gw, "find", {"status": "pending"})
        closing = call(gw, "close_case", {"id": "case-1"})
        check(
            "3 a status only 0.2.0 allows and a tool only 0.2.0 has are refused for team ops, naming the update",
            error(pending).get("code", "").lower() == "invalid_input"
            and error(closing).get("code") == "operation_hidden" and "takes the update" in str(error(closing))
            and len(fake.state()["calls"]) == before,
            {"pending": pending.text[:300], "closing": closing.text[:300]},
        )  # fmt: skip

        # 4. Team ops' tool list matches its calls: the removed tool is listed, the new one is not.
        # Asked as agents-service for team ops, as an agent's grant list is.
        as_agents = service_headers(
            "tools", tenant=TENANT["id"], service="agents", scopes=["tools:view"], team="team_ops"
        ) | {"X-Team-Id": "team_ops"}
        listing = gw.get("/v1/grantable-operations", headers=as_agents)
        names = {t["name"] for t in (data(listing) or []) if str(t["name"]).startswith("fields_")}
        check(
            "4 team ops' tool list keeps fields_transfer and does not offer fields_close_case",
            "fields_transfer" in names and "fields_close_case" not in names,
            {"names": sorted(names), "status": listing.status_code, "text": listing.text[:300]},
        )

        # 5. The review lists each new, changed and removed tool with its input changes.
        r = review(gw, priya)
        tools_seen = {t["name"]: t for t in r.get("tools", [])}
        check(
            "5 the review shows 0.1.0 to 0.2.0: find's status changed, post_message's request changed, transfer "
            "removed and close_case new",
            r.get("available") is True and r.get("version") == "0.1.0"
            and (r.get("installed") or {}).get("version") == "0.2.0"
            and tools_seen.get("fields_find", {}).get("inputs", {}).get("changed") == ["status"]
            and "request" in tools_seen.get("fields_post_message", {}).get("changed", [])
            and tools_seen.get("fields_transfer", {}).get("change") == "removed"
            and tools_seen.get("fields_close_case", {}).get("change") == "new",
            r,
        )  # fmt: skip

        # 6. Who uses the changed and removed tools: an agent of team ops granted post_message and transfer.
        agents_list = (data(ag.get("/v1/agents", params={"pageSize": 200}, headers=priya)) or {}).get("data", [])
        agent = next((a for a in agents_list if a.get("teamId", "team_ops") == "team_ops"), {})
        granted = ag.patch(
            f"/v1/agents/{agent.get('id')}",
            json={"toolIds": [*agent.get("toolIds", []), "fields_post_message", "fields_transfer"]},
            headers=priya,
        )
        uses = (
            data(ag.get("/v1/tool-uses", params={"tools": "fields_post_message,fields_transfer"}, headers=priya)) or {}
        )
        named = {t: [u["id"] for u in us] for t, us in uses.items()}
        check(
            "6 the team's agent that holds post_message and transfer is named for both",
            granted.status_code == 200
            and agent.get("id") in named.get("fields_post_message", [])
            and agent.get("id") in named.get("fields_transfer", []),
            {"granted": granted.text[:300], "uses": uses},
        )

        # 7. A review another upgrade replaced is refused; the take records 0.2.0.
        stale = gw.post(f"/v1/apps/plugin:{ID}/update", json={"digest": "0" * 64}, headers=priya)
        taken = gw.post(
            f"/v1/apps/plugin:{ID}/update", json={"digest": (r.get("installed") or {}).get("digest")}, headers=priya
        )
        check(
            "7 a stale review is refused with update_changed, and taking the update records 0.2.0 with nothing waiting",
            stale.status_code == 409 and error(stale).get("code") == "update_changed"
            and (data(taken) or {}).get("version") == "0.2.0" and (data(taken) or {}).get("available") is False,
            {"stale": stale.text[:200], "taken": taken.text[:300]},
        )  # fmt: skip

        # The update brings close_case into the catalog; team ops adds it as it adds any tool.
        gw.post(f"/v1/apps/plugin:{ID}/tools", json={"tools": ["fields_close_case"]}, headers=priya)

        # 8. Team ops now runs 0.2.0; team platform is still on 0.1.0.
        new_post = call(gw, "post_message", {"channel": "C1", "text": "Card 1043"})
        new_at = reached(fake)
        closed = call(gw, "close_case", {"id": "case-1"})
        gone = call(gw, "transfer", {"amount": 25, "to": "acct-7"})
        other = call(gw, "post_message", {"channel": "C2", "text": "Card 7"}, team="team_platform")
        other_at = reached(fake)
        check(
            "8 team ops' calls run 0.2.0 (new path, close_case works, transfer refused), and team platform still runs "
            "0.1.0",
            new_at == "/fields/chat.post" and output(new_post).get("ok") is True
            and output(closed).get("closed") == "case-1" and error(gone).get("code") == "operation_hidden"
            and other_at == "/fields/chat.postMessage" and output(other).get("ok") is True,
            {"new": (new_post.text[:200], new_at), "closed": closed.text[:200], "gone": gone.text[:200],
             "other": (other.text[:200], other_at)},
        )  # fmt: skip

finish()
