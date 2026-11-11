"""uc-590, sdk layer: docs/usecases/agents-service/plugin-templates.md, stories S5 and S7 (steps 21 and 22) and the
sdk steps of S10, S11 and S13 (steps 60 to 63), on the service desk plugin of resources_desk.py. A developer signed in
through the Python SDK in sdk/python lists the plugin's templates and installs one, and gets what the API gives:
the same list, a copy made once, and the same copy on a repeat. The stack is the api layer's: platform-service,
tools-service with the test plugin, agents-service reading tools-service. No model call."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))
from apps_walk import sdk_op, signed_sdk, target
from ops_ai import OpsAI
from resources_desk import AGENT, DOCUMENT_TYPE, KNOWLEDGE, SKILL, WORKFLOW, write_desk
from resources_desk import SOURCE as DESK
from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    agents,
    bearer,
    check,
    finish,
    kb,
    platform,
    signed_in,
    tools,
)

PLUGIN = "test.templates"
SOURCE = f"plugin:{PLUGIN}"
FOLDER = ROOT / "services/tools-service/tests/plugin_templates/templates_desk"
DESK_DIR = Path(tempfile.mkdtemp(prefix="uc590-sdk-"))
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(FOLDER), str(write_desk(DESK_DIR))])}
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}


def main() -> None:
    with (
        platform() as (accounts, _),
        tools({**AUTH, **PLUGINS}) as gw,
        # documents-service keeps the document type copies the app's resource list joins; it reads the team's
        # document type templates from this tools-service.
        kb(DESK_DIR / "kb", documents_env={**AUTH, "OPS_TOOLS_URL": str(gw.base_url).rstrip("/")}) as knowledge,
        agents(gateway_url=str(gw.base_url).rstrip("/"), kb_url=str(knowledge.base_url).rstrip("/"), env=AUTH) as api,
    ):
        priya = bearer(signed_in(accounts, "p.shah@harborpine.example"), "team_ops")
        gw.put(f"/v1/apps/plugin:{PLUGIN}/team", json={"enabled": True}, headers=priya)
        # A new app hands agents its read tools only; the team admin adds the write the agent template grants.
        gw.post(f"/v1/apps/plugin:{PLUGIN}/tools", json={"tools": ["templates_close_case"]}, headers=priya)
        ops = OpsAI.sign_in("p.shah@harborpine.example", "northfield-demo", team="team_ops", **CONN)

        # 21. The SDK's list matches the API's, and an install makes the copy once.
        through_sdk = ops.raw.agents.templates_list_templates(kind="agent")
        through_api = api.get("/v1/templates", params={"kind": "agent"}, headers=priya).json().get("data") or []
        first = ops.raw.agents.resources_copy_resource(f"{SOURCE}:case-helper", {})
        again = ops.raw.agents.resources_copy_resource(f"{SOURCE}:case-helper", {})
        check(
            "21 the SDK lists the same templates as the API and installs one copy, then answers the same copy",
            [t["id"] for t in through_sdk] == [t["id"] for t in through_api] == ["case-helper"]
            and first["created"] is True
            and again["created"] is False
            and first["copy"]["recordId"] == again["copy"]["recordId"],
            {"sdk": through_sdk, "api": through_api, "first": first, "again": again},
        )

        # 22 (group E). Add to team through the SDK's resources_copy_resource, generated from the copies route.
        copy_op = sdk_op(ops, "agents", "resources_copy_resource")
        copied = copy_op(f"{SOURCE}:close-politely", {}) if copy_op else None
        check(
            "22 the SDK's resources_copy_resource adds the skill to the team as its own copy",
            copied is not None and bool((copied.get("copy") or {}).get("recordId")),
            (target("S8 and K1"), copied),
        )

        desk_steps(gw, api, priya)
    finish()


def desk_steps(gw: Any, api: Any, priya: dict[str, str]) -> None:
    """Steps 60 to 63: a builder browses, previews, adds and removes the desk's resources through the SDK's words."""
    on = gw.put(f"/v1/apps/{DESK}/team", json={"enabled": True}, headers=priya)
    # A new app hands agents its read tools only; the team admin adds the write the agent template grants.
    gw.post(f"/v1/apps/{DESK}/tools", json={"tools": ["resources_close_ticket"]}, headers=priya)
    ops = signed_sdk("builder")

    # 60. The SDK's list says, for each resource, its state for the team; the knowledge source is one of them, with no
    # single copy to count, since a team adds it to any of its knowledge bases.
    listed = ops.resources.list(DESK)
    copied = [r for r in listed if r.get("kind") != "knowledge_source"]
    check(
        "60 the SDK lists the app's resources, each with its state for the team and the copies the team holds",
        on.status_code == 200
        and sorted(str(r.get("id")) for r in listed) == sorted([AGENT, SKILL, WORKFLOW, DOCUMENT_TYPE, KNOWLEDGE])
        and all(r.get("state") == "available" for r in listed)
        and all((r.get("installed") or {}).get("copies") == 0 for r in copied),
        [{k: r.get(k) for k in ("id", "kind", "state", "installed")} for r in listed],
    )

    # 61. A builder adds the agent from a listed item, filling the model alias; the knowledge base is named as left.
    aliases = api.get("/v1/model-aliases", headers=priya).json().get("data") or []
    alias = str((aliases[0] or {}).get("name") or "") if aliases else ""
    item = next((r for r in listed if r.get("id") == AGENT), f"{DESK}:{AGENT}")
    made = ops.resources.add(item, kind="agent", modelAlias=alias)
    agent_id = str((made.get("copy") or {}).get("recordId"))
    agent = api.get(f"/v1/agents/{agent_id}", headers=priya).json().get("data") or {}
    check(
        "61 the SDK adds the agent with the model alias it was given, and names the knowledge base left to bind",
        made.get("created") is True
        and agent.get("model") == alias
        and bool(alias)
        and made.get("needs") == [{"knowledgeBase": "Help articles"}],
        {"made": made, "model": agent.get("model"), "alias": alias},
    )

    # 62. The SDK previews several resources before adding them.
    plan = getattr(ops.resources, "plan", None)
    preview = plan([f"{DESK}:{WORKFLOW}", f"{DESK}:{SKILL}"]) if plan else None
    check(
        "62 the SDK previews the workflow and the skill: what each brings, what the team holds, what is left to bind",
        isinstance(preview, dict) and f"{DESK}:{AGENT}" in json.dumps(preview),
        preview if plan else "the SDK's resources offer no preview",
    )

    # 63. The SDK takes an update for, and removes, a copy it added.
    verbs = {v: getattr(ops.resources, v, None) for v in ("update", "remove")}
    removed = verbs["remove"](made) if verbs["remove"] else None
    check(
        "63 the SDK offers update and remove for an added copy, and remove deletes the agent",
        all(verbs.values()) and api.get(f"/v1/agents/{agent_id}", headers=priya).status_code == 404,
        {"verbs": sorted(v for v, f in verbs.items() if f), "removed": removed},
    )
    if api.get(f"/v1/agents/{agent_id}", headers=priya).status_code == 200:
        api.delete(f"/v1/agents/{agent_id}", headers=priya)


if __name__ == "__main__":
    main()
