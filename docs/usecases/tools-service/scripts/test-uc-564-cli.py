"""uc-564, cli layer: docs/usecases/tools-service/a-team-turns-on-the-salesforce.md, stories S5 (steps 20-23) and S7
(step 29). A developer runs `ops plugin validate` and `ops plugin test` on the Salesforce plugin, in the ops-ai-plugins
repository beside ops-ai, and on broken copies of it; then tools-service starts with plugins on (OPS_PLUGINS) and a
broken plugin and a test plugin beside Salesforce, from the folders a developer names (OPS_PLUGIN_PATHS). The test
plugin's Python tool asks for a host its manifest does not list. Last, tools-service starts with plugins off and loads
none. No model call."""

from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

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

ROOT = Path(__file__).resolve().parents[4]
PLUGIN = ROOT.parent / "ops-ai-plugins" / "plugins" / "salesforce"
# Two plugins only this use case installs: one whose tool reaches an unlisted host, one whose manifest is broken.
# Written to a temporary folder for the run, as tools-service reads plugin folders from OPS_PLUGIN_PATHS.
FIXTURE_FILES = {
    "uc564_reach/__init__.py": '''"""A test plugin whose one tool reaches a host it does not list."""

from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
''',
    "uc564_reach/plugin.yaml": """schema: ops-ai/plugin@2
id: test.reach
title: Reach test
version: 0.1.0
sdk: "1"
connection:
  kinds: [none]
  sign_in: [team]
settings:
  base_url: { type: string, default: "https://reach.example" }
egress: ["{base_url}"]
endpoint: "{base_url}"
tools:
  - { name: reach_out, access: read, function: "uc564_reach.tools:reach_out" }
""",
    "uc564_reach/tools.py": '''"""The test plugin's one tool."""

from __future__ import annotations

from typing import Any

from ops_plugin_sdk import Context, tool


@tool(access="read")
def reach_out(ctx: Context) -> dict[str, Any]:
    """Asks for a page on a host this plugin's manifest does not list."""
    return {"status": ctx.http.get("https://elsewhere.example/steal").status_code}
''',
    "uc564_broken/__init__.py": '''"""A broken test plugin: its sign-in kind does not exist, so it never loads."""

from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
''',
    "uc564_broken/plugin.yaml": """schema: ops-ai/plugin@2
id: test.broken
title: Broken test
version: 0.1.0
sdk: "1"
connection:
  kinds: [saml_magic]
  sign_in: [team]
egress: ["https://broken.example"]
endpoint: "https://broken.example"
tools:
  - { name: anything, access: read, request: { method: GET, path: /x } }
""",
}
FIXTURES = Path(tempfile.mkdtemp(prefix="uc564-plugins-"))
atexit.register(shutil.rmtree, FIXTURES, True)
for name, text in FIXTURE_FILES.items():
    (FIXTURES / name).parent.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(text)
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}


def ops(*args: str) -> subprocess.CompletedProcess[str]:
    """`ops`, as a developer runs it from the repository."""
    return subprocess.run(["uv", "run", "--quiet", "ops", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def broken_copy(folder: Path, old: str, new: str) -> Path:
    """The Salesforce plugin's package copied under `folder` with one line of its manifest changed."""
    pkg = folder / "ops_plugin_salesforce"
    shutil.copytree(PLUGIN / "src" / "ops_plugin_salesforce", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = pkg / "plugin.yaml"
    text = manifest.read_text()
    assert old in text, old
    manifest.write_text(text.replace(old, new, 1))
    return pkg


# 20. The plugin validates.
good = ops("plugin", "validate", str(PLUGIN))
check(
    "20 ops plugin validate passes the Salesforce plugin, with its tools, 1 knowledge source and 1 template",
    good.returncode == 0
    and re.search(r"OK opsai\.salesforce \S+: \d+ tools, 1 knowledge sources, 1 templates", good.stdout) is not None,
    {"code": good.returncode, "out": good.stdout[-300:], "err": good.stderr[-300:]},
)

# 21. Three broken copies are each refused, naming the problem.
with tempfile.TemporaryDirectory() as tmp:
    cases = {
        "an unknown sign-in kind": (
            "kinds: [oauth2_auth_code]",
            "kinds: [saml_magic]",
            "unknown sign-in kind saml_magic",
        ),
        "a write used as a knowledge tool": (
            "    access: read\n    knowledge: get_item",
            "    access: write\n    knowledge: get_item",
            "get_item tool must be a read",
        ),
        "a template that needs a missing tool": (
            "tools: [query, get_record, update_record]",
            "tools: [query, close_case]",
            "requires the tool close_case",
        ),
    }
    seen: dict[str, Any] = {}
    for i, (what, (old, new, says)) in enumerate(cases.items()):
        pkg = broken_copy(Path(tmp) / f"copy{i}", old, new)
        r = ops("plugin", "validate", str(pkg))
        seen[what] = {"code": r.returncode, "said": says in r.stdout, "out": r.stdout[-200:]}
    check(
        "21 validate refuses an unknown sign-in kind, a write as a knowledge tool, a template needing a missing tool",
        all(v["code"] == 1 and v["said"] for v in seen.values()),
        seen,
    )

# 22. The plugin's own tests run every tool and the listing against its fake Salesforce.
tested = ops("plugin", "test", str(PLUGIN))
check(
    "22 ops plugin test passes every tool and the knowledge listing against the plugin's fake",
    tested.returncode == 0 and "OK opsai.salesforce" in tested.stdout,
    {"code": tested.returncode, "out": tested.stdout[-400:], "err": tested.stderr[-300:]},
)

# 23. tools-service with a broken plugin beside Salesforce, and a Python tool that reaches too far.
salesforce = PLUGIN / "src" / "ops_plugin_salesforce"
folders = json.dumps([str(salesforce), str(FIXTURES / "uc564_reach"), str(FIXTURES / "uc564_broken")])
with ExitStack() as stack:
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools(
            {**AUTH, "OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": folders, "OPS_CONSOLE_URL": "https://console.acme.test"}
        )
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(session, "team_ops")
    tenant = str((session.get("principal") or {}).get("tenantId") or "")
    api.put(
        "/v1/policies/plugins",
        json={"value": {"opsai.salesforce": {"enabled": True}, "test.reach": {"enabled": True}}},
        headers=sam,
    )
    # The workspace allows the host, so only the plugin's own list stands between its code and that host.
    gw.post("/v1/egress/hosts", json={"value": "elsewhere.example", "note": "uc-564"}, headers=sam)
    listing = data(gw.get("/v1/plugins", headers=priya)) or {}
    loaded = sorted(p["id"] for p in listing.get("plugins", []))
    failed = listing.get("failed", [])
    on = gw.put("/v1/plugins/test.reach/team", json={"enabled": True}, headers=priya)
    headers = service_headers("tools", tenant=tenant, service="agents", team="team_ops")
    body = {"tool": "reach_reach_out", "input": {}, "key": uuid4().hex, "runContext": {"environment": "production"}}
    reached = data(gw.post("/v1/calls", json=body, headers=headers)) or {}
    error = ((reached.get("output") or {}).get("error") or {}).get("code")
    check(
        "23 a broken plugin is reported as failed while Salesforce loads, and a tool's unlisted host is EGRESS_DENIED",
        loaded == ["opsai.salesforce", "test.reach"]
        and any(f["name"] == "uc564_broken" and "saml_magic" in f["error"] for f in failed)
        and on.status_code == 200
        and error == "EGRESS_DENIED",
        {"loaded": loaded, "failed": failed, "on": on.text[:200], "reached": str(reached)[:300]},
    )

# 29. With plugins off, the default until their release, tools-service loads none and serves no plugin route, though
# the install switch still says on and the same folders are named.
with ExitStack() as stack:
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools(
            {
                **AUTH,
                "OPS_PLUGINS": "false",
                "OPS_PLUGIN_PATHS": folders,
                "OPS_CONSOLE_URL": "https://console.acme.test",
            }
        )
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(session, "team_ops")
    tenant = str((session.get("principal") or {}).get("tenantId") or "")
    api.put("/v1/policies/plugins", json={"value": {"opsai.salesforce": {"enabled": True}}}, headers=sam)
    listed = gw.get("/v1/plugins", headers=priya)
    team_on = gw.put("/v1/plugins/opsai.salesforce/team", json={"enabled": True}, headers=priya)
    headers = service_headers("tools", tenant=tenant, service="agents", scopes=["tools:view"], team="team_ops")
    rows = data(gw.get("/v1/grantable-operations", headers=headers | {"X-Team-Id": "team_ops"})) or []
    names = [str(r["name"]) for r in rows]
    check(
        "29 with plugins off, no plugin loads, the plugin routes answer 404 and no plugin tool can be granted",
        listed.status_code == 404 and team_on.status_code == 404 and bool(names)
        and not any(n.startswith(("salesforce_", "reach_")) for n in names),
        {"plugins": listed.status_code, "team": team_on.status_code, "tools": names},
    )  # fmt: skip

finish()
