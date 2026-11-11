# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-676 typed text and pushed items become cited knowledge, sdk layer: docs/usecases/kb-service/typed-text-and-pushed-
items.md, story S5. A developer pushes an item through the Python SDK in sdk/python and the TypeScript SDK in
sdk/typescript. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, data, finish, kb

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
const ops = new OpsAI({ baseUrl: 'http://127.0.0.1', services: { kb: '%(kb)s' }, team: 'team_ops' });
const put = await ops.raw.kb.sources_put_item({ path: { source_id: '%(source)s' }, body: %(item)s });
const found = await ops.raw.kb.knowledge_bases_search_knowledge({ body: { kbIds: ['%(base)s'], question: 'overdraft fee waived' } });
console.log(JSON.stringify({ outcome: put.outcome, text: found.passages.map((p) => p.text).join(' ') }));
"""


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-676-sdk-") as tmp, kb(Path(tmp) / "files") as k:
        ops = OpsAI(base_url="http://127.0.0.1", services={"kb": str(k.base_url).rstrip("/")}, team="team_ops")
        kb_api: Any = ops.raw.kb
        base = data(k.post("/v1/knowledge-bases", json={"name": "Deposit fees", "owner": OWNER}))
        src = kb_api.sources_create_source({"type": "push", "name": "Fee schedule feed", "kbIds": [base["id"]]})
        first = kb_api.sources_put_item(src["id"], ITEM)
        check(
            "8 the Python SDK pushes an item, which is created and indexed",
            first["outcome"] == "created" and first["item"]["status"] == "indexed",
            first,
        )
        again = kb_api.sources_put_item(src["id"], ITEM)
        check("9 the same call again is unchanged", again["outcome"] == "unchanged", again["outcome"])

        sdk = ROOT / "sdk" / "typescript"
        subprocess.run(["npx", "tsc", "-p", "tsconfig.json"], cwd=sdk, check=True, capture_output=True)
        script = TS_CHECK % {
            "sdk": (sdk / "dist" / "index.js").as_posix(),
            "kb": str(k.base_url).rstrip("/"),
            "source": src["id"],
            "base": base["id"],
            "item": json.dumps(ITEM),
        }
        ran = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
        seen = json.loads(ran.stdout or "{}") if ran.returncode == 0 else {}
        check(
            "10 the TypeScript SDK pushes the same item, unchanged, and its search returns the pushed text",
            seen.get("outcome") == "unchanged" and "25 dollars" in str(seen.get("text")),
            seen or ran.stderr[-600:],
        )
    finish()


main()
