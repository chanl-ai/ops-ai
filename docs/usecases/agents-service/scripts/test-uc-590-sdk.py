"""uc-590, sdk layer: docs/usecases/agents-service/plugin-templates.md, story S5 (step 21). A developer signed in
through the Python SDK in sdk/python lists the plugin's templates and installs one, and gets what the API gives:
the same list, a copy made once, and the same copy on a repeat. The stack is the api layer's: platform-service,
tools-service with the test plugin, agents-service reading tools-service. No model call."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))
from apps_walk import sdk_op, target
from ops_ai import OpsAI
from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    agents,
    bearer,
    check,
    finish,
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
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}


def main() -> None:
    with (
        platform() as (accounts, _),
        tools({**AUTH, **PLUGINS}) as gw,
        agents(gateway_url=str(gw.base_url).rstrip("/"), env=AUTH) as api,
    ):
        sam = bearer(signed_in(accounts, "s.adeyemi@harborpine.example"), "team_security")
        priya = bearer(signed_in(accounts, "p.shah@harborpine.example"), "team_ops")
        accounts.put("/v1/policies/plugins", json={"value": {PLUGIN: {"enabled": True}}}, headers=sam)
        gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": True}, headers=priya)
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
    finish()


if __name__ == "__main__":
    main()
