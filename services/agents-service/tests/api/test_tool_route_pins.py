"""The team assistant's app tools, tool uses, the Tools page and picker, routing to people and step-up, by failure
mode: a reply, status or error code changing as the routes move onto the kit's bodies and the request transaction.
Regenerate the pins only for an intended change: `AGENTS_REPIN=1` writes what the routes answer now to
`fixtures/reply-pins-tool-routes.json`."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from ops_agents.api.agent_registry import SEED_TEAM
from ops_agents.api.auth import DEV_PASSWORD, DEV_TOTP
from ops_identity import dev_service_signer, mint_service_token

from .test_reply_pins import FIXTURES, answer, compare


def service(name: str, scopes: list[str], team: str | None = SEED_TEAM) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service=name, audience="agents", tenant_id="local", scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


PERSON: dict[str, str] = {}
OTHER_TEAM = {"X-Team-Id": "team_nobody"}
DEV = "j.richardson@harborpine.example"
ROUTE = "/v1/threads:route-to-people"
STEP_UP = "/v1/auth/step-up"

# (name, method, path, body, caller): each answered value by value.
PINNED: list[tuple[str, str, str, dict[str, Any] | None, dict[str, str]]] = [
    ("assistant.none", "POST", "/v1/team-assistant/app-tools", {"moduleIds": ["mod_nothing"]}, PERSON),
    ("assistant.empty", "POST", "/v1/team-assistant/app-tools", {"moduleIds": []}, PERSON),
    ("assistant.unknown", "POST", "/v1/team-assistant/app-tools", {"moduleIds": ["m"], "agentId": "x"}, PERSON),
    ("uses", "GET", "/v1/tool-uses?tools=place_wire_hold,get_customer_profile,nothing_uses_it", None, PERSON),
    ("uses.otherTeam", "GET", "/v1/tool-uses?tools=place_wire_hold", None, OTHER_TEAM),
    ("uses.service", "GET", "/v1/tool-uses?tools=place_wire_hold", None, service("kb", ["agents:view"])),
    ("uses.serviceNoTeam", "GET", "/v1/tool-uses?tools=place_wire_hold", None, service("kb", ["agents:view"], None)),
    ("uses.noScope", "GET", "/v1/tool-uses?tools=place_wire_hold", None, service("kb", [])),
    ("uses.noTools", "GET", "/v1/tool-uses?tools=", None, PERSON),
    ("documentTypes", "GET", "/v1/document-type-uses?types=dt_missing", None, PERSON),
    ("documentTypes.noScope", "GET", "/v1/document-type-uses?types=dt_missing", None, service("documents", [])),
    ("accounts", "GET", "/v1/account-uses?app=salesforce&name=Main", None, service("tools", ["agents:view"])),
    ("accounts.noName", "GET", "/v1/account-uses?app=salesforce", None, PERSON),
    ("tools.search", "GET", "/v1/tools?search=wire&pageSize=5", None, PERSON),
    ("tools.kind", "GET", "/v1/tools?kind=workflow&kind=agent&pageSize=4", None, PERSON),
    ("tools.pastEnd", "GET", "/v1/tools?page=999&pageSize=10", None, PERSON),
    ("tools.one", "GET", "/v1/tools/place_wire_hold", None, PERSON),
    ("tools.missing", "GET", "/v1/tools/no_such_tool", None, PERSON),
    ("options.search", "GET", "/v1/tools/options?search=customer&limit=2", None, PERSON),
    ("options.next", "GET", "/v1/tools/options?search=customer&limit=2&cursor=Mg", None, PERSON),
    ("options.ids", "GET", "/v1/tools/options?ids=place_wire_hold&ids=gone_tool", None, PERSON),
    ("options.noAgents", "GET", "/v1/tools/options?agents=false&limit=2", None, PERSON),
    ("route.missing", "POST", "/v1/threads/th_missing/route-to-people", {"reason": "Needs a person"}, PERSON),
    ("route.noReason", "POST", "/v1/threads/th_missing/route-to-people", {"reason": ""}, PERSON),
    ("route.version", "POST", ROUTE, {"workflowId": "wire_hold_review", "versionNumber": 1, "reason": "x"}, PERSON),
    ("route.unknown", "POST", ROUTE, {"workflowId": "w", "versionNumber": 1, "reason": "x", "team": "t"}, PERSON),
    ("stepUp.wrongPassword", "POST", STEP_UP, {"password": "wrong"}, PERSON),
    ("stepUp.wrongCode", "POST", STEP_UP, {"password": DEV_PASSWORD, "code": "000 000"}, PERSON),
    ("stepUp.unknown", "POST", STEP_UP, {"password": DEV_PASSWORD, "otp": DEV_TOTP}, PERSON),
    ("sso.other", "POST", f"{STEP_UP}/sso", {"code": base64.b64encode(b"someone@else.example").decode()}, PERSON),
    ("sso.unreadable", "POST", f"{STEP_UP}/sso", {"code": "not base64!"}, PERSON),
]

# A step-up's token is signed at the moment it is asked for: its status and the keys of its reply are pinned.
MINTED: list[tuple[str, str, dict[str, Any]]] = [
    ("stepUp.ok", STEP_UP, {"password": DEV_PASSWORD, "code": DEV_TOTP}),
    ("sso.ok", f"{STEP_UP}/sso", {"code": base64.b64encode(DEV.upper().encode()).decode()}),
]


async def test_the_tool_and_step_up_routes_keep_every_key_value_and_error_object(client: AsyncClient) -> None:
    seen: dict[str, Any] = {}
    for name, method, path, body, headers in PINNED:
        seen[name] = answer(await client.request(method, path, json=body, headers=headers))
    for name, path, body in MINTED:
        r = await client.post(path, json=body)
        seen[name] = {"status": r.status_code, "keys": sorted(r.json()["data"])}
    compare(seen, FIXTURES / "reply-pins-tool-routes.json")


# (method, path, body, connections the request checks out). One: the route answers in the request transaction. Zero: it
# reads nothing from the database. More: it calls another service, so each read takes and returns its own connection
# and none is held while the other service answers.
CHECKOUTS: list[tuple[str, str, dict[str, Any] | None, int]] = [
    ("POST", "/v1/team-assistant/app-tools", {"moduleIds": ["mod_nothing"]}, 6),
]


async def test_each_route_checks_out_the_connections_it_should(client: AsyncClient) -> None:
    request_task = asyncio.current_task()
    counted: list[int] = []

    def checked_out(*_: object) -> None:
        # The app's loops check out connections too; only the request's own task counts.
        if asyncio.current_task() is request_task:
            counted[-1] += 1

    event.listen(Pool, "checkout", checked_out)
    seen: list[tuple[str, int]] = []
    try:
        for method, path, body, _ in CHECKOUTS:
            counted.append(0)
            r = await client.request(method, path, json=body)
            assert r.status_code < 300, r.text
            seen.append((path, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    assert seen == [(p, n) for _, p, _, n in CHECKOUTS], seen
