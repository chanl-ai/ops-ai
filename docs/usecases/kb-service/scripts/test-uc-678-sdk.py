# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-678 a team takes in SharePoint libraries and Confluence spaces, sdk layer:
docs/usecases/kb-service/sharepoint-and-confluence-sources.md, story S6. A developer asks a plugin source's pickers
through the Python SDK in sdk/python and the TypeScript SDK in sdk/typescript, on the same stack as the api layer: the
plugins in tools-service against their fakes (docs/usecases/lib/fake_sharepoint_confluence.py), signed in as the team.
No model is called."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fake_sharepoint_confluence import connect, stack
from usecase_harness import ROOT, check, finish

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI

OPS = {"X-Team-Id": "team_ops"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
TS_CHECK = """
import { OpsAI } from '%(sdk)s';
const ops = new OpsAI({ baseUrl: 'http://127.0.0.1', services: { kb: '%(kb)s' }, team: 'team_ops' });
const libs = await ops.raw.kb.sources_source_scopes({ body: { plugin: 'opsai.sharepoint', source: 'files', parent: '%(site)s' } });
const spaces = await ops.raw.kb.sources_source_scopes({ body: { plugin: 'opsai.confluence', source: 'spaces', query: 'eng' } });
console.log(JSON.stringify({ libraries: libs.scopes.map((s) => [s.id, s.kind, s.parent]), spaces: spaces.scopes.map((s) => s.id) }));
"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-678-sdk-") as tmp, stack(Path(tmp)) as (k, gw, systems):
        ids = systems.graph_ids
        done = connect(gw, systems, OPS, SECURITY)
        if done["sharepoint"]["done"] != 200 or (done["confluence"]["health"] or {}).get("status") != "ok":
            raise SystemExit(f"FAIL the apps did not connect: {done}")
        kb_url = str(k.base_url).rstrip("/")
        ops = OpsAI(base_url="http://127.0.0.1", services={"kb": kb_url}, team="team_ops")
        kb_api: Any = ops.raw.kb
        sites = kb_api.sources_source_scopes({"plugin": "opsai.sharepoint", "source": "files", "query": "human"})
        found = [(s["id"], s["kind"]) for s in sites["scopes"]]
        check(
            "8 the Python SDK's sources_source_scopes searches SharePoint's sites by name",
            found == [(ids.SITE_HR, "site")],
            sites,
        )

        sdk = ROOT / "sdk" / "typescript"
        subprocess.run(["npx", "tsc", "-p", "tsconfig.json"], cwd=sdk, check=True, capture_output=True)
        script = TS_CHECK % {"sdk": (sdk / "dist" / "index.js").as_posix(), "kb": kb_url, "site": ids.SITE_HR}
        ran = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
        seen = json.loads(ran.stdout or "{}") if ran.returncode == 0 else {}
        libraries = {tuple(row) for row in seen.get("libraries", [])}
        check(
            "9 the TypeScript SDK lists a site's libraries and Confluence's spaces through the same method",
            libraries == {(ids.LIB_POLICIES, "library", ids.SITE_HR), (ids.LIB_HANDBOOK, "library", ids.SITE_HR)}
            and "ENG" in seen.get("spaces", []),
            seen or ran.stderr[-600:],
        )
    finish()


main()
