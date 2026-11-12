# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-676 typed text and pushed items become cited knowledge, sdk layer: docs/usecases/kb-service/typed-text-and-pushed-
items.md, story S5. A developer pushes an item through the Python SDK in sdk/python and the TypeScript SDK in
sdk/typescript, by their named knowledge calls. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from usecase_harness import ROOT, check, finish, kb

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI

OWNER = "maya@harborpine.example"
ITEM = {
    "name": "fees/overdraft",
    "title": "Overdraft fee",
    "text": "An overdraft fee of 25 dollars is waived once a year.",
}
TS_CHECK = """
import { OpsAI } from '%(sdk)s';
// Address, service and team come from the saved sign-in named by OPS_CONFIG, as the Python SDK and opsai read them.
const ops = new OpsAI({ profile: 'local' });
const base = await ops.knowledge.addBase('TS deposit fees', { owner: '%(owner)s' });
const feed = await ops.knowledge.addSource('TS fee feed', [base.id]);
const put = await ops.knowledge.push(feed.id, '%(name)s', { title: '%(title)s', text: '%(text)s' });
const page = await ops.knowledge.addPage(base.id, 'Opening hours', 'Branches open at nine.');
const found = await ops.knowledge.search({ kbIds: [base.id], question: 'overdraft fee waived' });
console.log(JSON.stringify({ outcome: put.outcome, page: page.status, text: found.passages.map((p) => p.text).join(' ') }));
"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-676-sdk-") as tmp, kb(Path(tmp) / "files") as k:
        url = str(k.base_url).rstrip("/")
        ops = OpsAI(base_url="http://127.0.0.1", services={"kb": url}, team="team_ops")
        base = ops.knowledge.add_base("Deposit fees", owner=OWNER)
        src = ops.knowledge.add_source("Fee schedule feed", [base["id"]])
        first = ops.knowledge.push(src["id"], ITEM["name"], title=ITEM["title"], text=ITEM["text"])
        check(
            "8 the Python SDK creates a base and a push source, then pushes an item, created and indexed",
            first["outcome"] == "created" and first["item"]["status"] == "indexed",
            first,
        )
        again = ops.knowledge.push(src["id"], ITEM["name"], title=ITEM["title"], text=ITEM["text"])
        check("9 the same call again is unchanged", again["outcome"] == "unchanged", again["outcome"])
        page = ops.knowledge.add_page(base["id"], "Opening hours", "Branches open at nine.")
        check("9b add_page writes a page into the base", page.get("status") == "indexed", page)

        config = Path(tmp) / "ops-config.json"
        config.write_text(
            json.dumps(
                {"profiles": {"local": {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": {"kb": url}}}}
            )
        )
        sdk = ROOT / "sdk" / "typescript"
        subprocess.run(["npx", "tsc", "-p", "tsconfig.json"], cwd=sdk, check=True, capture_output=True)
        script = TS_CHECK % {
            "sdk": (sdk / "dist" / "index.js").as_posix(),
            "owner": OWNER,
            **{key: ITEM[key] for key in ("name", "title", "text")},
        }
        env = {**os.environ, "OPS_CONFIG": str(config)}
        ran = subprocess.run(
            ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False, env=env
        )
        seen = json.loads(ran.stdout or "{}") if ran.returncode == 0 else {}
        check(
            "10 the TypeScript SDK, signed in from the saved profile, creates its own base and source, pushes the item "
            "and its search returns the pushed text",
            seen.get("outcome") == "created" and "25 dollars" in str(seen.get("text")),
            seen or ran.stderr[-600:],
        )
    finish()


main()
