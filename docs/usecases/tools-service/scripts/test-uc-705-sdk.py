"""uc-705, sdk layer: docs/usecases/tools-service/callers-from-before-several-accounts-keep-working.md.

The Python SDK as it was before several accounts per app (git 13ada62b, unpacked into a temporary folder) reads an
app's accounts, which now carry `identity`, and adds a person's second account with its bodyless call, against the
services as they are now (lib/several_accounts.py)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from several_accounts import MAYA, PRIYA, SF, add_org, retail_on, rig
from usecase_harness import AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, finish

BEFORE = "13ada62b"

with tempfile.TemporaryDirectory() as tmp, rig("uc-705s") as r:
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", BEFORE, "sdk/python/src"], capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
    sys.path.insert(0, str(Path(tmp) / "sdk/python/src"))
    from ops_ai import OpsAI  # the SDK from before the change

    services = {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "tools": f"http://127.0.0.1:{TOOLS_PORT}",
                "agents": f"http://127.0.0.1:{AGENTS_PORT}"}  # fmt: skip
    sf = r.sf
    retail_on(r, sign_in="person_or_team")
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    priya = OpsAI.sign_in(PRIYA, "northfield-demo", team="team_ops", base_url="http://127.0.0.1", services=services)
    page = priya.apps.get(SF)
    names = sorted(str(a["name"]) for a in page.get("accounts") or [] if a.get("kind") == "team")
    check(
        "1 the older SDK reads Salesforce's page, whose account rows now carry identity",
        names == ["EU org", "Retail org"] and all("identity" in a for a in page.get("accounts") or []),
        names,
    )
    maya = OpsAI.sign_in(MAYA, "northfield-demo", team="team_ops", base_url="http://127.0.0.1", services=services)
    started = maya.raw.tools.apps_add_own_account(r.ids["retail"])
    check(
        "2 the older SDK's bodyless add of Maya's second account starts a sign-in",
        str(started.get("authorizeUrl") or "").startswith(f"{sf['login_url']}/authorize"),
        started,
    )

finish()
