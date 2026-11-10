"""uc-590, cli layer: docs/usecases/agents-service/plugin-templates.md, story S7 (step 23).
The sdk layer's stack: platform-service, tools-service with the test plugin, documents-service (beside kb-service) whose
document type copies the resource list joins, agents-service reading tools-service.
A team admin lists the app's resources and adds the agent with `opsai resources`, signed in as their dev role the way
`make api` signs in (`opsai --as`). No model call."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from apps_walk import AUTH, ops_cli
from usecase_harness import ROOT, agents, as_role, check, finish, kb, platform, tools

PLUGIN = "test.templates"
FOLDER = ROOT / "services/tools-service/tests/plugin_templates/templates_desk"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(FOLDER)])}


def main() -> None:
    with (
        platform() as (accounts, _),
        tools({**AUTH, **PLUGINS}) as gw,
        kb(
            Path(tempfile.mkdtemp(prefix="uc590-cli-")),
            documents_env={**AUTH, "OPS_TOOLS_URL": str(gw.base_url).rstrip("/")},
        ) as knowledge,
        agents(gateway_url=str(gw.base_url).rstrip("/"), kb_url=str(knowledge.base_url).rstrip("/"), env=AUTH),
    ):
        admin = as_role(accounts, "admin", "team_ops")
        on = gw.put(f"/v1/apps/plugin:{PLUGIN}/team", json={"enabled": True}, headers=admin)
        check("set-up: the plugin is on for team_ops", on.status_code == 200, on.text[:200])

        # 23. opsai resources list and add, as the team admin.
        listed_code, listed = ops_cli("admin", "resources", "list", f"plugin:{PLUGIN}")
        added_code, added = ops_cli("admin", "resources", "add", f"plugin:{PLUGIN}", "case-helper")
        check(
            "23 `opsai resources list` names the plugin's four resources and `opsai resources add` copies the agent",
            listed_code == 0
            and isinstance(listed, list)
            and len(listed) == 4
            and added_code == 0
            and isinstance(added, dict)
            and bool((added.get("copy") or {}).get("recordId")),
            {"list": (listed_code, listed), "add": (added_code, added)},
        )
    finish()


if __name__ == "__main__":
    main()
