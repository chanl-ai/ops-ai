# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-677 a knowledge owner turns on rerank and query rewrite, sdk layer: docs/usecases/kb-service/rerank-and-query-
rewrite.md, story S5. Own kb-service, models-service and the fake OpenAI, as the api layer; no provider is called."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, data, fake_openai, finish, kb, models

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI

RULES = ROOT / "services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai"
PAGES = [
    ("wire-cutoff", "Wire cutoff", "## Cutoff\n\nA domestic wire sent after 5 pm goes out the next business day."),
    ("wire-fees", "Wire fees", "## Fees\n\nAn outgoing domestic wire costs 25 dollars."),
]
TS_CHECK = """
import { OpsAI } from '%(sdk)s';
const ops = new OpsAI({ baseUrl: 'http://127.0.0.1', services: { kb: '%(kb)s' }, team: 'team_ops' });
const found = await ops.raw.kb.knowledge_bases_search_knowledge({ body: { kbIds: ['%(base)s'], question: 'domestic wire' } });
console.log(JSON.stringify({ ran: found.rerank?.ran, order: found.passages.map((p) => [p.title, p.reranked]) }));
"""


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc-677-sdk-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", env={"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_kb"}) as k,
    ):
        ops = OpsAI(base_url="http://127.0.0.1", services={"kb": str(k.base_url).rstrip("/")}, team="team_ops")
        kb_api: Any = ops.raw.kb
        base = data(k.post("/v1/knowledge-bases", json={"name": "Payments", "owner": "maya@harborpine.example"}))
        src = data(k.post("/v1/sources", json={"type": "text", "name": "Payment pages", "kbIds": [base["id"]]}))
        for name, title, text in PAGES:
            kb_api.sources_put_item(src["id"], {"name": name, "title": title, "text": text})
        saved = kb_api.knowledge_bases_update_knowledge_base(
            base["id"], {"retrieval": {"rerank": True, "queryModel": "default"}}
        )
        found = kb_api.knowledge_bases_query_knowledge_base(base["id"], {"question": "domestic wire"})
        check(
            "5 the Python SDK saves rerank on and its query comes back reranked",
            saved["retrieval"]["rerank"] is True
            and found["rerank"]["ran"] is True
            and found["passages"][0]["reranked"] == 9,
            {"rerank": found.get("rerank"), "first": found["passages"][:1]},
        )
        sdk = ROOT / "sdk" / "typescript"
        subprocess.run(["npx", "tsc", "-p", "tsconfig.json"], cwd=sdk, check=True, capture_output=True)
        script = TS_CHECK % {
            "sdk": (sdk / "dist" / "index.js").as_posix(),
            "kb": str(k.base_url).rstrip("/"),
            "base": base["id"],
        }
        ran = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
        seen = json.loads(ran.stdout or "{}") if ran.returncode == 0 else {}
        check(
            "6 the TypeScript SDK's search has the same order and scores",
            seen.get("ran") is True and seen.get("order") == [["Wire fees", 9], ["Wire cutoff", 0]],
            seen or ran.stderr[-600:],
        )
    finish()


main()
