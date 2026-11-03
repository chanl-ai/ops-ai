"""uc-590, api layer: docs/usecases/agents-service/plugin-templates.md, stories S1 to S4 (steps 1 to 11).

tools-service runs with plugins on and the test plugin (services/tools-service/tests/plugin_templates/templates_desk);
installed, it is there for every team with no admin step, and the team switch is Priya's to turn for
team_ops. agents-service reads its operations and templates from that tools-service; documents-service sits beside a
files-service. Platform sign-in throughout, as a deployment runs: a dev session acts in no team, and templates are
installed into one, so the install refuses it. No model call."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    agents,
    bearer,
    check,
    data,
    finish,
    kb,
    platform,
    signed_in,
    tools,
)

PLUGIN = "test.templates"
SOURCE = f"plugin:{PLUGIN}"
FOLDER = ROOT / "services/tools-service/tests/plugin_templates/templates_desk"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(FOLDER)])}
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
OPS: dict[str, str] = {}
OTHER: dict[str, str] = {}
TOOLS = ["templates_get_case", "templates_close_case"]


def code(r: httpx.Response) -> str | None:
    try:
        return str(r.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def said(r: httpx.Response) -> str:
    return f"{r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}"


def install(c: httpx.Client, tid: str, who: dict[str, str] = OPS, **body: Any) -> httpx.Response:
    return c.post(f"/v1/resources/{SOURCE}:{tid}/copies", json=body, headers=who)


def listed(c: httpx.Client, who: dict[str, str], kind: str | None = None) -> list[dict[str, Any]]:
    r = c.get("/v1/templates", params={"kind": kind} if kind else None, headers=who)
    return list(data(r) or []) if r.status_code == 200 else [{"error": said(r)}]


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc590-") as tmp,
        platform() as (accounts, _),
        tools({**AUTH, **PLUGINS}) as gw,
        # documents-service reads the team's document type templates from this tools-service.
        kb(Path(tmp) / "kb", documents_env={**AUTH, "OPS_TOOLS_URL": str(gw.base_url).rstrip("/")}) as knowledge,
        httpx.Client(base_url=knowledge.documents_url, timeout=30) as docs,
        agents(gateway_url=str(gw.base_url).rstrip("/"), kb_url=str(knowledge.base_url).rstrip("/"), env=AUTH) as api,
    ):
        OPS.update(bearer(signed_in(accounts, "p.shah@harborpine.example"), "team_ops"))
        OTHER.update(bearer(signed_in(accounts, "w.kamau@harborpine.example"), "team_platform"))
        # 1. Priya turns the plugin on for team_ops; team_platform leaves it off.
        on = gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": True}, headers=OPS)
        check("1 the plugin is on for team_ops", on.status_code == 200, {"team": said(on)})

        # 2. team_ops sees the four templates, none installed; team_platform sees none.
        mine = listed(api, OPS) + listed(docs, OPS)
        theirs = listed(api, OTHER) + listed(docs, OTHER)
        check(
            "2 team_ops sees the agent, skill, workflow and document type, none installed, and team_platform none",
            sorted((str(t.get("kind")), str(t.get("id"))) for t in mine)
            == [
                ("agent", "case-helper"),
                ("document_type", "case-letter"),
                ("skill", "close-politely"),
                ("workflow", "case-review"),
            ]
            and all((t.get("installed") or {}).get("copies") == 0 for t in mine)
            and theirs == [],
            {"mine": mine, "theirs": theirs},
        )

        # 3. The agent installs as team_ops's draft, granting the plugin's tools, naming what is left to bind.
        first = install(api, "case-helper")
        made = (data(first) or {}) if first.status_code == 201 else {}
        aid = str((made.get("copy") or {}).get("recordId"))
        agent = data(api.get(f"/v1/agents/{aid}", headers=OPS)) or {}
        check(
            "3 the agent installs as the team's draft granting the plugin's tools",
            first.status_code == 201
            and agent.get("teamId") == "team_ops"
            and agent.get("availability") != "published"
            and agent.get("toolIds") == TOOLS
            and made.get("needs") == [{"knowledgeBase": "Case articles"}, {"modelAlias": "chat"}],
            {"install": said(first), "agent": {k: agent.get(k) for k in ("teamId", "availability", "toolIds")}},
        )

        # 4. The same version again answers that copy.
        again = install(api, "case-helper")
        check(
            "4 the same version again answers the copy the team holds",
            again.status_code == 200 and ((data(again) or {}).get("copy") or {}).get("recordId") == aid,
            said(again),
        )

        # 5. Once the agent is deleted, an install makes a new one.
        gone = api.delete(f"/v1/agents/{aid}", headers=OPS)
        fresh = install(api, "case-helper")
        fresh_id = str(((data(fresh) or {}).get("copy") or {}).get("recordId"))
        check(
            "5 after the copy is deleted a new install makes a new agent",
            gone.status_code == 204 and fresh.status_code == 201 and fresh_id not in ("None", aid),
            {"delete": said(gone), "install": said(fresh)},
        )

        # 6. The skill and the workflow install as team_ops's drafts.
        skill_r, flow_r = install(api, "close-politely"), install(api, "case-review")
        sid = str(((data(skill_r) or {}).get("copy") or {}).get("recordId"))
        wid = str(((data(flow_r) or {}).get("copy") or {}).get("recordId"))
        skill = data(api.get(f"/v1/skills/{sid}", headers=OPS)) or {}
        flow = data(api.get(f"/v1/workflows/definitions/{wid}", headers=OPS)) or {}
        check(
            "6 the skill and the workflow install as the team's drafts",
            skill_r.status_code == 201
            and flow_r.status_code == 201
            and skill.get("status") == "draft"
            and [t.get("toolId") for t in (skill.get("content") or {}).get("tools") or []] == TOOLS[1:]
            and wid.startswith("case_review_")
            and flow.get("stage") != "live",
            {"skill": said(skill_r), "workflow": said(flow_r), "stage": flow.get("stage")},
        )

        # 7. The document type installs on documents-service, ready to read.
        doc_r = install(docs, "case-letter")
        tid = str(((data(doc_r) or {}).get("copy") or {}).get("recordId"))
        doc_type = data(docs.get(f"/v1/document-types/{tid}", headers=OPS)) or {}
        # A type's fields live on its versions; a copy is made at version 1, ready to read.
        newest = (doc_type.get("versions") or [{}])[-1]
        keys = [f.get("key") for f in (newest.get("fields") or [])]
        check(
            "7 the document type installs as the team's type with the template's fields",
            doc_r.status_code == 201 and keys == ["case_number", "letter_date"],
            {"install": said(doc_r), "fields": keys},
        )

        # 8. team_platform never sees team_ops's copies.
        seen = [
            api.get(f"/v1/agents/{fresh_id}", headers=OTHER).status_code,
            api.get(f"/v1/skills/{sid}", headers=OTHER).status_code,
            api.get(f"/v1/workflows/definitions/{wid}", headers=OTHER).status_code,
            docs.get(f"/v1/document-types/{tid}", headers=OTHER).status_code,
        ]
        made_all = all(x not in ("None", "") for x in (fresh_id, sid, wid, tid))
        check(
            "8 another team never sees the copies",
            made_all and all(s in (403, 404) for s in seen),
            {"made": [fresh_id, sid, wid, tid], "seen": seen},
        )

        # 9. A team with the plugin off cannot install its templates.
        off = install(api, "case-helper", OTHER)
        check(
            "9 a team with the plugin off is told the template is not found",
            off.status_code == 404 and code(off) == "template_not_found",
            said(off),
        )

        # 10. A version the plugin does not ship.
        old = install(api, "case-helper", version=1)
        check(
            "10 a version the plugin does not ship is not found",
            old.status_code == 404 and code(old) == "template_version_not_found",
            said(old),
        )

        # 11. A model alias nobody serves is refused as on create, and no agent is made.
        api.delete(f"/v1/agents/{fresh_id}", headers=OPS)
        before = len((data(api.get("/v1/agents", params={"pageSize": 100}, headers=OPS)) or {}).get("data") or [])
        bad = install(api, "case-helper", modelAlias="nobody-serves-this")
        after = len((data(api.get("/v1/agents", params={"pageSize": 100}, headers=OPS)) or {}).get("data") or [])
        check(
            "11 a model alias nobody serves is refused as on create, and nothing is made",
            bad.status_code == 422 and code(bad) == "unknown_model_alias" and after == before,
            {"install": said(bad), "before": before, "after": after},
        )

        # 30-31 (group E): an app's resources, and Add to team.
        offered = gw.get("/v1/plugin-templates", headers=OPS)
        ids = (
            sorted(f"{r.get('source')}:{r.get('id')}" for r in data(offered) or [])
            if offered.status_code == 200
            else []
        )
        check(
            "30 the app's resources list its agent, skill, workflow and document type, each named <source>:<id>",
            ids == sorted(f"{SOURCE}:{t}" for t in ("case-helper", "close-politely", "case-review", "case-letter")),
            said(offered),
        )

        # 31. Add to team is one route per service: agents-service copies the agent, documents-service the document
        # type; a second copy of the same version answers the copy the team holds.
        copy = api.post(f"/v1/resources/{SOURCE}:case-helper/copies", json={}, headers=OPS)
        copy_again = api.post(f"/v1/resources/{SOURCE}:case-helper/copies", json={}, headers=OPS)
        doc_copy = docs.post(f"/v1/resources/{SOURCE}:case-letter/copies", json={}, headers=OPS)
        copy_id = ((data(copy) or {}).get("copy") or {}).get("recordId")
        check(
            "31 Add to team copies the agent once on agents-service and the document type on documents-service",
            copy.status_code == 201
            and copy_again.status_code == 200
            and ((data(copy_again) or {}).get("copy") or {}).get("recordId") == copy_id
            and doc_copy.status_code == 200
            and ((data(doc_copy) or {}).get("copy") or {}).get("recordId") == tid,
            ("target: waits on S8", {"agent": said(copy), "again": said(copy_again), "document type": said(doc_copy)}),
        )
    finish()


if __name__ == "__main__":
    main()
