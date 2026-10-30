"""uc-581, api layer: docs/usecases/tools-service/agents-query-salesforce-many-ways.md, stories S1 (steps 1-4) and
S2 (steps 5-11). platform-service signs the seeded people in and holds the install switch; tools-service runs with
plugins on and the Salesforce plugin from the ops-ai-plugins repository beside ops-ai; the fake Salesforce
(docs/usecases/lib/fake_salesforce.py) holds one account's cases, one of them deleted, and records every query it
answers. Each call is a gateway read as agents-service makes it for a run. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
from fake_salesforce import ACCOUNT_ID, LIST_VIEW_ID, salesforce
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
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

PLUGIN = "opsai.salesforce"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
SALESFORCE = REPO.parent / "ops-ai-plugins/plugins/salesforce/src/ops_plugin_salesforce"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)])}
OPEN = ["5003000000E1aaaAAA", "5003000000E2bbbAAA", "5003000000E4dddAAA"]
DELETED = "5003000000E3cccAAA"
TENANT: dict[str, str] = {}


def call(gw: httpx.Client, tool: str, args: dict[str, Any]) -> httpx.Response:
    """A read as agents-service makes it for a run in team_ops: it runs at once."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team="team_ops")
    body = {
        "tool": f"salesforce_{tool}",
        "input": args,
        "key": uuid4().hex,
        "runContext": {"environment": "production"},
    }
    return gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"})


def out(r: httpx.Response) -> dict[str, Any]:
    """What the tool answered: the call's output, or {} for a refused call."""
    got = data(r) if r.status_code == 200 else None
    return dict((got or {}).get("output") or {}) if isinstance(got, dict) else {}


def code_of(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return ""
    error = body.get("error") or (body.get("data") or {}).get("output", {}).get("error") or {}
    return str(error.get("code") or "")


def ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("Id") or r.get("id")) for r in rows]


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **PLUGINS, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    fake = sf["fake"]

    # Set-up as uc-564's steps 1-5: the install switch, Salesforce's hosts, the team switch and the team's sign-in.
    on = api.put("/v1/policies/plugins", json={"value": {PLUGIN: {"enabled": True}}}, headers=sam)
    for h in sf["hosts"]:
        gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-581"}, headers=sam)
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-581"}, headers=sam)
    login = sf["authorize_url"].rsplit("/", 1)[0]
    team_on = {"enabled": True, "settings": {"login_url": login}, "clientId": "ops-ai-acme", "clientSecret": "s3"}
    turned = gw.put(f"/v1/plugins/{PLUGIN}/team", json=team_on, headers=priya)
    connection_id = str((data(turned) or {}).get("connectionId") or "con_missing")
    started = gw.post(f"/v1/connections/{connection_id}/sign-in", json={"environment": "production"}, headers=priya)
    back = sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), "acme.integration")
    done = gw.post(
        f"/v1/connections/{connection_id}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=priya,
    )
    check(
        "setup: Salesforce is on for the install and the team, and the team signed in",
        on.status_code == 200 and turned.status_code == 200 and done.status_code == 200,
        {"on": on.text[:200], "turned": turned.text[:200], "done": done.text[:200]},
    )

    # 1. An agent asks for escalated cases changed since a date: one page and a sealed cursor, from checked inputs.
    first = call(gw, "find_cases", {"status": "Escalated", "since": "2026-10-01T11:00:00+02:00"})
    page1, sent = out(first), (fake.queries[-1] if fake.queries else "")
    check(
        "1 the first page comes with a sealed cursor, and the status and date are written into the SOQL",
        ids(page1.get("records", [])) == OPEN[:2]
        and bool(page1.get("next_cursor"))
        and "nextRecordsUrl" not in page1
        and "/query/" not in str(page1.get("next_cursor"))
        and "Status = 'Escalated'" in sent
        and "LastModifiedDate > 2026-10-01T09:00:00Z" in sent,
        {"status": first.status_code, "page": page1, "sent": sent, "text": first.text[:300]},
    )

    # 2. The cursor gives the next page of the same query, and nothing after it.
    second = out(call(gw, "find_cases", {"cursor": page1.get("next_cursor")}))
    check(
        "2 the cursor reads the next page of the same query, which is the last",
        ids(second.get("records", [])) == OPEN[2:] and "next_cursor" not in second,
        second,
    )

    # 3. Values that would change the query never reach Salesforce.
    asked = len(fake.queries)
    bad = [
        call(gw, "find_cases", {"status": "Escalated' OR Status != '"}),
        call(gw, "find_cases", {"status": "New", "since": "2026' OR Name != '"}),
        call(gw, "account_cases", {"account_id": "001' OR Id != '"}),
    ]
    check(
        "3 a status outside the list, a date that is not a date and a bad id are refused before Salesforce",
        all(r.status_code != 200 or code_of(r) for r in bad) and len(fake.queries) == asked,
        {"codes": [(r.status_code, code_of(r), r.text[:160]) for r in bad], "queries": fake.queries[asked:]},
    )

    # 4. A cursor the caller changed, or one another tool gave, is refused and reads nothing.
    other = out(call(gw, "account_cases", {"account_id": ACCOUNT_ID})).get("next_cursor", "")
    asked = len(fake.queries)
    refused = [
        call(gw, "find_cases", {"cursor": str(page1.get("next_cursor"))[:-3] + "xyz"}),
        call(gw, "find_cases", {"cursor": other}),
    ]
    check(
        "4 a changed cursor and one from another tool are refused",
        bool(other) and all(code_of(r) == "INVALID_INPUT" for r in refused) and len(fake.queries) == asked,
        {"codes": [(r.status_code, code_of(r), r.text[:160]) for r in refused]},
    )

    # 5. queryAll includes the deleted case; the normal query never does.
    every = out(call(gw, "find_cases_with_deleted", {"status": "Escalated"}))
    rows = every.get("records", [])
    more = out(call(gw, "find_cases_with_deleted", {"cursor": every.get("next_cursor")})).get("records", [])
    check(
        "5 a query that includes deleted records shows the deleted case, marked, and the normal query did not",
        DELETED in ids(rows + more)
        and next(r for r in rows + more if r["Id"] == DELETED)["IsDeleted"] is True
        and DELETED not in ids(page1.get("records", []) + second.get("records", [])),
        {"rows": ids(rows + more)},
    )

    # 6. A search across objects finds the account, its contact and its cases; SOSL's reserved characters stay inside.
    found = out(call(gw, "search", {"term": "Acme"})).get("searchRecords", [])
    kinds = sorted({r["attributes"]["type"] for r in found})
    call(gw, "search", {"term": "card} RETURNING User(Email"})
    sosl = fake.queries[-1] if fake.queries else ""
    check(
        "6 a search across objects finds the account, contact and cases, and a term cannot add a clause",
        kinds == ["Account", "Case", "Contact"]
        and sosl.startswith("FIND {card\\} RETURNING User\\(Email} IN ALL FIELDS"),
        {"kinds": kinds, "sosl": sosl},
    )

    # 7. A structured search returns only the fields asked for, for cases in the status asked for.
    fields = out(call(gw, "search_by_fields", {"term": "card", "status": "Escalated", "fields": ["Id", "Subject"]}))
    rows = fields.get("searchRecords", [])
    check(
        "7 a search by fields returns the open escalated cases with only the fields asked for",
        sorted(ids(rows)) == sorted(OPEN) and all(set(r) <= {"attributes", "Id", "Subject"} for r in rows),
        rows,
    )

    # 8. An account's related cases page by link.
    a1 = out(call(gw, "account_cases", {"account_id": ACCOUNT_ID}))
    a2 = out(call(gw, "account_cases", {"cursor": a1.get("next_cursor")}))
    check(
        "8 an account's cases come a page at a time by Salesforce's next address",
        ids(a1.get("records", []) + a2.get("records", [])) == OPEN and "next_cursor" not in a2,
        {"first": ids(a1.get("records", [])), "second": ids(a2.get("records", []))},
    )

    # 9. The cases changed between two times, in UTC, without the deleted one.
    changed = out(call(gw, "cases_changed", {"start": "2026-10-04T00:00:00Z", "end": "2026-10-07T12:00:00Z"}))
    check("9 the cases changed between two times are listed by id", changed.get("ids") == OPEN[:2], changed)

    # 10. A list view pages by token and reads as flat fields.
    pages, cursor, guard = [], None, 0
    while guard < 5:
        guard += 1
        got = out(call(gw, "list_view", {"cursor": cursor} if cursor else {"list_view": LIST_VIEW_ID}))
        pages.append(got.get("records", []))
        cursor = got.get("next_cursor")
        if not cursor:
            break
    flat = [r for p in pages for r in p]
    check(
        "10 a list view comes a page at a time by token, each record with flat fields",
        ids(flat) == OPEN and len(pages) == 3 and flat[0].get("fields", {}).get("CaseNumber") == "00044901",
        {"pages": pages},
    )

    # 11. Every query tool is a data tool with a title, as the gateway lists it to agents.
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", scopes=["tools:view"], team="team_ops")
    listed = {
        r["name"]: r
        for r in data(gw.get("/v1/grantable-operations", headers=headers | {"X-Team-Id": "team_ops"})) or []
    }
    seven = [
        "find_cases",
        "find_cases_with_deleted",
        "search",
        "search_by_fields",
        "account_cases",
        "cases_changed",
        "list_view",
    ]
    titles = {t: (listed.get(f"salesforce_{t}") or {}).get("title") for t in seven}
    check(
        "11 the seven query tools are offered to agents, each with its title",
        all(titles.values()) and titles["find_cases"] == "Find cases",
        titles,
    )

finish()
