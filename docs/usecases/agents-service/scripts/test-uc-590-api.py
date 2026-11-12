"""uc-590, api layer: docs/usecases/agents-service/plugin-templates.md, stories S1 to S4 (steps 1 to 11).

tools-service runs with plugins on and the test plugin (services/tools-service/tests/plugin_templates/templates_desk);
installed, it is there for every team with no admin step, and the team switch is Priya's to turn for
team_ops. agents-service reads its operations and templates from that tools-service; documents-service sits beside a
files-service. Platform sign-in throughout, as a deployment runs: a dev session acts in no team, and templates are
installed into one, so the install refuses it. No model call."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

import httpx
from resources_desk import (
    AGENT,
    DOCUMENT_TYPE,
    INSTRUCTIONS,
    KNOWLEDGE,
    SKILL,
    WORKFLOW,
    change_agent_instructions,
    write_desk,
)
from resources_desk import PLUGIN as PLUGIN_DESK
from resources_desk import SOURCE as DESK
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
OWNER = "p.shah@harborpine.example"


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


def plugins(*folders: Path) -> dict[str, str]:
    return {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(f) for f in folders])}


def main() -> None:
    with ExitStack() as stack:
        tmp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="uc590-")))
        desk = write_desk(tmp / "v1")
        accounts, _ = stack.enter_context(platform())
        # tools-service has its own stack so the removed-upstream step can start it again on a later plugin version.
        gateway = ExitStack()
        stack.callback(gateway.close)
        gw = gateway.enter_context(tools({**AUTH, **plugins(FOLDER, desk)}))
        tools_url = str(gw.base_url).rstrip("/")
        # kb-service takes a plugin's knowledge source only on an install with plugins, reading them through this
        # tools-service; kb() passes on what the environment holds when it starts.
        os.environ.update({**plugins(desk), "OPS_TOOLS_URL": tools_url})
        # documents-service reads the team's document type templates from this tools-service.
        knowledge = stack.enter_context(kb(tmp / "kb", documents_env={**AUTH, "OPS_TOOLS_URL": tools_url}, env=AUTH))
        docs = stack.enter_context(httpx.Client(base_url=knowledge.documents_url, timeout=30))
        api = stack.enter_context(agents(gateway_url=tools_url, kb_url=str(knowledge.base_url).rstrip("/"), env=AUTH))
        OPS.update(bearer(signed_in(accounts, "p.shah@harborpine.example"), "team_ops"))
        OTHER.update(bearer(signed_in(accounts, "w.kamau@harborpine.example"), "team_platform"))
        # 1. Priya turns the plugin on for team_ops; team_platform leaves it off.
        on = gw.put(f"/v1/apps/plugin:{PLUGIN}/team", json={"enabled": True}, headers=OPS)
        # A new app hands agents its read tools only; the team admin adds the write the agent template grants.
        gw.post(f"/v1/apps/plugin:{PLUGIN}/tools", json={"tools": ["templates_close_case"]}, headers=OPS)
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

        def restart_tools(folder: Path) -> httpx.Client:
            gateway.close()
            return gateway.enter_context(tools({**AUTH, **plugins(FOLDER, folder)}))

        resource_stories(
            accounts=accounts,
            gw=gw,
            api=api,
            docs=docs,
            knowledge=knowledge,
            desk=desk,
            tmp=tmp,
            restart_tools=restart_tools,
        )
    finish()


def copy_id(r: httpx.Response) -> str | None:
    return ((data(r) or {}).get("copy") or {}).get("recordId") if r.status_code in (200, 201) else None


def rows(c: httpx.Client, who: dict[str, str]) -> list[dict[str, Any]]:
    """The desk's resources as a service lists them for `who`."""
    r = c.get("/v1/templates", params={"source": DESK}, headers=who)
    found = list(data(r) or []) if r.status_code == 200 else []
    # documents-service's list takes no source; the desk's are kept here.
    return [t for t in found if t.get("source") == DESK]


def row(c: httpx.Client, who: dict[str, str], tid: str) -> dict[str, Any]:
    return next((t for t in rows(c, who) if t.get("id") == tid), {})


def add(c: httpx.Client, tid: str, who: dict[str, str], **body: Any) -> httpx.Response:
    return c.post(f"/v1/resources/{DESK}:{tid}/copies", json=body, headers=who)


def nodes_of(definition: Any) -> list[dict[str, Any]]:
    """Every workflow node in a definition answer, wherever the answer nests them."""
    if isinstance(definition, dict):
        d = cast(dict[str, Any], definition)
        found = [n for n in d.get("nodes") or [] if isinstance(n, dict)]
        return found + [n for v in d.values() if isinstance(v, (dict, list)) for n in nodes_of(v)]
    if isinstance(definition, list):
        return [n for v in cast(list[Any], definition) for n in nodes_of(v)]
    return []


# Words a person should never read in a refusal: role grid cells, team ids, record kinds in code form.
INTERNAL = re.compile(r"\b(team_[a-z]+|[a-z_]+\.(create|edit|manage|view)|document_type|a agent)\b")


def resource_stories(
    *,
    accounts: httpx.Client,
    gw: httpx.Client,
    api: httpx.Client,
    docs: httpx.Client,
    knowledge: httpx.Client,
    desk: Path,
    tmp: Path,
    restart_tools: Any,
) -> None:
    """Stories S10 to S14 (steps 40 to 59) on the service desk plugin (resources_desk.py): its ticket helper agent,
    close-ticket skill, triage workflow whose agent step runs the ticket helper, ticket form, and help articles."""
    builder = bearer(signed_in(accounts, "j.richardson@harborpine.example"), "team_ops")
    viewer = bearer(signed_in(accounts, "r.menon@harborpine.example"), "team_ops")
    # kb-service signs people in through platform-service, as tools-service asks it to for a source's host.
    kb_ops, kb_other = OPS, OTHER
    made: list[tuple[httpx.Client, str]] = []

    # 40. Priya turns the desk on for team_ops; a viewer and a builder each see its four resources, none added.
    on = gw.put(f"/v1/apps/{DESK}/team", json={"enabled": True}, headers=OPS)
    # The ticket helper is granted a write; the team admin adds it, as from the app's Tools tab.
    gw.post(f"/v1/apps/{DESK}/tools", json={"tools": ["resources_close_ticket"]}, headers=OPS)
    seen = {who: rows(api, h) + rows(docs, h) for who, h in (("viewer", viewer), ("builder", builder))}
    check(
        "40 a viewer and a builder of the team each see the app's agent, skill, workflow and document type, none added",
        on.status_code == 200
        and all(
            sorted(str(t.get("id")) for t in s) == sorted([AGENT, SKILL, WORKFLOW, DOCUMENT_TYPE])
            and all((t.get("installed") or {}).get("copies") == 0 for t in s)
            for s in seen.values()
        ),
        {"team": said(on), "seen": {k: [(t.get("id"), t.get("installed")) for t in v] for k, v in seen.items()}},
    )

    # 41. Each resource says its state in one word and whether the caller may add it: the viewer may not add the
    # agent, skill or workflow, and may add the document type, since every member keeps the team's document types.
    check(
        "41 each resource reads available, and says the viewer may add none while the builder may add each",
        all(t.get("state") == "available" for s in seen.values() for t in s)
        and all(t.get("canAdd") is False for t in seen["viewer"])
        and all(t.get("canAdd") is True for t in seen["builder"]),
        {k: [{x: t.get(x) for x in ("id", "state", "canAdd")} for t in v] for k, v in seen.items()},
    )

    # 42. A viewer's add of the agent is refused in plain words, and nothing is made. (Every member holds the grid's
    # documents edit cell, so the roles grid lets a viewer add the document type; this step does not test it.)
    refused = add(api, AGENT, viewer)
    words = str(((refused.json() if refused.content else {}).get("error") or {}).get("message", ""))
    check(
        "42 a viewer's add of the agent is refused in plain words and makes nothing",
        refused.status_code == 403
        and not INTERNAL.search(words)
        and row(api, OPS, AGENT).get("installed", {}).get("copies") == 0,
        said(refused),
    )

    # 43. Before adding, the builder previews the workflow: what it brings with it and what it needs.
    plan = api.post("/v1/resources/plan", json={"resources": [f"{DESK}:{WORKFLOW}"]}, headers=builder)
    planned = data(plan) if plan.status_code == 200 else {}
    text = json.dumps(planned)
    check(
        "43 the preview of the workflow names the agent it runs, the tools both use and the bindings left to fill",
        plan.status_code == 200
        and f"{DESK}:{AGENT}" in text
        and "resources_get_ticket" in text
        and "knowledgeBase" in text
        and "modelAlias" in text,
        said(plan),
    )

    # 44. The workflow alone, before its agent is the team's, is refused naming the agent, and nothing is made.
    early = add(api, WORKFLOW, builder)
    early_id = copy_id(early)
    check(
        "44 adding the workflow before the agent it runs is refused naming that agent, and nothing is made",
        early.status_code == 422 and AGENT in early.text and early_id is None,
        said(early),
    )
    if early_id:
        api.delete(f"/v1/workflows/definitions/{early_id}", headers=OPS)

    # 45. A knowledge base of another team is not the team's to bind, and nothing is made.
    mine = data(knowledge.post("/v1/knowledge-bases", json={"name": "Help articles", "owner": OWNER}, headers=kb_ops))
    theirs = data(
        knowledge.post("/v1/knowledge-bases", json={"name": "Platform runbooks", "owner": OWNER}, headers=kb_other)
    )
    mine_id, theirs_id = str((mine or {}).get("id")), str((theirs or {}).get("id"))
    aliases = data(api.get("/v1/model-aliases", headers=OPS)) or []
    alias = str((aliases[0] or {}).get("name") or "") if aliases else ""
    crossed = add(api, AGENT, builder, knowledgeBases=[theirs_id], modelAlias=alias)
    crossed_id = copy_id(crossed)
    check(
        "45 binding another team's knowledge base is refused, and nothing is made",
        bool(mine and theirs) and crossed.status_code == 422 and crossed_id is None,
        {"bases": [mine_id, theirs_id], "install": said(crossed)},
    )
    if crossed_id:
        api.delete(f"/v1/agents/{crossed_id}", headers=OPS)

    # 46. The builder adds the agent with the team's knowledge base and a served model alias: nothing is left to bind.
    helper = add(api, AGENT, builder, knowledgeBases=[mine_id], modelAlias=alias)
    helper_id = copy_id(helper)
    agent = data(api.get(f"/v1/agents/{helper_id}", headers=OPS)) or {} if helper_id else {}
    check(
        "46 the builder adds the agent with the team's knowledge base and model alias, and nothing is left to bind",
        helper.status_code == 201
        and (data(helper) or {}).get("needs") == []
        and agent.get("collections") == [mine_id]
        and agent.get("model") == alias
        and bool(alias),
        {"install": said(helper), "agent": {k: agent.get(k) for k in ("collections", "model")}, "alias": alias},
    )
    if helper_id:
        made.append((api, f"/v1/agents/{helper_id}"))

    # 47. With the agent the team's own, the workflow's agent step runs the team's copy.
    flow = add(api, WORKFLOW, builder)
    flow_id = copy_id(flow)
    steps = nodes_of(data(api.get(f"/v1/workflows/definitions/{flow_id}", headers=OPS))) if flow_id else []
    runs = [(n.get("parameters") or {}).get("agent") for n in steps if n.get("type") == "ops.ai.agent"]
    check(
        "47 the workflow added after its agent runs the team's copy of that agent",
        flow.status_code == 201 and bool(helper_id) and runs[:1] == [helper_id],
        {"install": said(flow), "agent steps run": runs, "team's agent": helper_id},
    )
    if flow_id:
        made.insert(0, (api, f"/v1/workflows/definitions/{flow_id}"))

    # 48. The team already has a skill of the template's name: adding it as it is is refused, naming the clash.
    own = api.post(
        "/v1/skills",
        json={
            "name": "Close a ticket politely",
            "useWhen": "Someone asks to close a ticket",
            "instructions": "Close it.",
            "ownerTeam": "team_ops",
        },
        headers=OPS,
    )
    own_id = str((data(own) or {}).get("id")) if own.status_code == 201 else None
    clash = add(api, SKILL, builder)
    clash_id = copy_id(clash)
    check(
        "48 a skill whose name the team already uses is refused with name_taken, and nothing is made",
        own.status_code == 201 and clash.status_code == 409 and code(clash) == "name_taken" and clash_id is None,
        {"own skill": said(own), "install": said(clash)},
    )
    if clash_id:
        api.delete(f"/v1/skills/{clash_id}", headers=OPS)
    if own_id:
        api.delete(f"/v1/skills/{own_id}", headers=OPS)

    # 49. Named its own way, the skill is added under that name.
    named = add(api, SKILL, builder, name="Close a ticket, desk")
    named_id = copy_id(named)
    skill = data(api.get(f"/v1/skills/{named_id}", headers=OPS)) or {} if named_id else {}
    name = skill.get("name") or (skill.get("content") or {}).get("name")
    check(
        "49 the skill added with a name of its own carries that name",
        named.status_code == 201 and name == "Close a ticket, desk",
        {"install": said(named), "name": name},
    )
    if named_id:
        made.append((api, f"/v1/skills/{named_id}"))

    # 50. A document type of the same name is refused with name_taken; named its own way, the builder adds it.
    hand = docs.post(
        "/v1/document-types",
        json={"name": "Ticket form", "fields": [{"key": "ref", "label": "Reference", "type": "text"}]},
        headers=OPS,
    )
    taken = add(docs, DOCUMENT_TYPE, builder)
    form = add(docs, DOCUMENT_TYPE, builder, name="Ticket form, desk")
    form_id = copy_id(form)
    check(
        "50 a document type whose name the team uses is refused with name_taken, and named its own way it is added",
        hand.status_code == 201
        and taken.status_code == 409
        and code(taken) == "name_taken"
        and form.status_code == 201,
        {"hand-made": said(hand), "as it is": said(taken), "named": said(form)},
    )

    # 51. The plugin changes its agent template at the same version: the row says so, and the team's copy is as it was.
    change_agent_instructions(desk, "Read the ticket first, then answer only from the help articles.")
    listed = row(api, OPS, AGENT)
    kept = (data(api.get(f"/v1/agents/{helper_id}", headers=OPS)) or {}).get("instructions") if helper_id else None
    check(
        "51 a changed agent template reads update available, and the team's copy keeps the instructions it had",
        (listed.get("installed") or {}).get("changed") is True and kept == INSTRUCTIONS,
        {"row": listed, "copy's instructions": kept},
    )

    # 52. The team edits its copy, then takes the update: the team's edit is never overwritten.
    edit = "Read the ticket and answer in the team's own words."
    patched = api.patch(f"/v1/agents/{helper_id}", json={"instructions": edit}, headers=OPS) if helper_id else None
    take = api.post(f"/v1/resources/{DESK}:{AGENT}/copies/{helper_id}/update", json={}, headers=OPS)
    after = (data(api.get(f"/v1/agents/{helper_id}", headers=OPS)) or {}).get("instructions") if helper_id else None
    check(
        "52 taking an update on an edited copy answers what it would change and leaves the team's edit in place",
        patched is not None and patched.status_code == 200 and take.status_code in (200, 409) and after == edit,
        {"edit": said(patched) if patched else None, "update": said(take), "instructions": after},
    )

    # 53. Deleting the agent the team's workflow runs is refused first, naming that workflow.
    gone = api.delete(f"/v1/agents/{helper_id}", headers=OPS) if helper_id else None
    check(
        "53 deleting an added agent that the team's workflow runs names the workflow and deletes nothing",
        gone is not None and gone.status_code == 409 and "Ticket triage" in gone.text,
        said(gone) if gone else "no agent was added",
    )
    if gone is not None and gone.status_code == 204:
        made[:] = [m for m in made if m[1] != f"/v1/agents/{helper_id}"]

    # 54. The added document type can be deleted, and its row then offers Add again.
    dropped = docs.delete(f"/v1/document-types/{form_id}", headers=OPS) if form_id else None
    check(
        "54 an added document type is deleted, and the app's row reads not added again",
        dropped is not None
        and dropped.status_code == 204
        and row(docs, OPS, DOCUMENT_TYPE).get("installed", {}).get("copies") == 0,
        {"delete": said(dropped) if dropped else "no document type was added", "row": row(docs, OPS, DOCUMENT_TYPE)},
    )

    # 55. tools-service restarts on 0.2.0 of the desk, which no longer ships the skill: the team's copy stays, and the
    # app's list still shows it, marked as no longer offered.
    gw = restart_tools(write_desk(tmp / "v2", version="0.2.0", with_skill=False))
    gw.put(f"/v1/apps/{DESK}/team", json={"enabled": True}, headers=OPS)
    stays = api.get(f"/v1/skills/{named_id}", headers=OPS) if named_id else None
    upstream = row(api, OPS, SKILL)
    check(
        "55 a resource the app stops shipping stays the team's, and its row reads removed by the app",
        stays is not None and stays.status_code == 200 and upstream.get("state") == "removed_upstream",
        {"copy": said(stays) if stays else None, "row": upstream},
    )

    # 56. The app's resources include its knowledge source, beside its agent, skill, workflow and document type.
    offered = gw.get("/v1/plugin-templates", headers=OPS)
    kinds = sorted(str(t.get("kind")) for t in data(offered) or [] if t.get("source") == DESK)
    check(
        "56 the app's resources list its knowledge source with the agents, workflows and document types",
        offered.status_code == 200 and "knowledge_source" in kinds,
        {"kinds": kinds, "answer": said(offered)},
    )

    # 57. Priya adds the app's help articles to her knowledge base, and a sync brings both articles in.
    source = knowledge.post(
        "/v1/sources",
        json={
            "type": "tool",
            "name": "Help articles",
            "config": {"plugin": PLUGIN_DESK, "source": KNOWLEDGE},
            "kbIds": [mine_id],
        },
        headers=kb_ops,
    )
    sid = str((data(source) or {}).get("id")) if source.status_code == 201 else None
    synced = knowledge.post(f"/v1/sources/{sid}/sync", headers=kb_ops) if sid else None
    items = data(knowledge.get(f"/v1/sources/{sid}/items", headers=kb_ops)) or {} if sid else {}
    titles = sorted(str(i.get("title")) for i in (items.get("data") if isinstance(items, dict) else items) or [])
    check(
        "57 the app's knowledge source is added to the team's knowledge base and its sync reads both articles",
        source.status_code == 201
        and synced is not None
        and synced.status_code == 200
        and titles == ["Replace a meter", "Reset a password"],
        {"source": said(source), "sync": said(synced) if synced else None, "titles": titles},
    )

    # 58. A team with the app off cannot add its knowledge source, and is told the app is off.
    off = knowledge.post(
        "/v1/sources",
        json={
            "type": "tool",
            "name": "Help articles",
            "config": {"plugin": PLUGIN_DESK, "source": KNOWLEDGE},
            "kbIds": [theirs_id],
        },
        headers=kb_other,
    )
    check(
        "58 a team with the app off is refused the app's knowledge source, naming that it is off",
        off.status_code in (400, 422) and "turn it on" in off.text,
        said(off),
    )

    # Clean up what the steps made, dependents first.
    if sid:
        knowledge.delete(f"/v1/sources/{sid}", headers=kb_ops)
    for base in (mine_id, theirs_id):
        knowledge.delete(f"/v1/knowledge-bases/{base}", headers=kb_ops if base == mine_id else kb_other)
    for client, path in made:
        client.delete(path, headers=OPS)


if __name__ == "__main__":
    main()
