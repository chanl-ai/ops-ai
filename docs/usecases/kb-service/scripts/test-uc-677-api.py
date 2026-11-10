# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-677 a knowledge owner turns on rerank and query rewrite, api layer: docs/usecases/kb-service/rerank-and-query-
rewrite.md. Own kb-service with its files-service and documents-service, and models-service with the fake OpenAI
answering the rewrite and rerank prompts by services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai; no
provider is called."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, data, fake_openai, finish, kb, models

OWNER = "maya@harborpine.example"
RULES = ROOT / "services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai"
PAGES = [
    ("wire-cutoff", "Wire cutoff", "## Cutoff\n\nA domestic wire sent after 5 pm goes out the next business day."),
    ("wire-fees", "Wire fees", "## Fees\n\nAn outgoing domestic wire costs 25 dollars."),
]


def search(k: Any, kb_id: str, question: str) -> dict[str, Any]:
    return data(k.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question})) or {}


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc-677-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", env={"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_kb"}) as k,
    ):
        base = data(k.post("/v1/knowledge-bases", json={"name": "Payments", "owner": OWNER}))
        src = data(k.post("/v1/sources", json={"type": "text", "name": "Payment pages", "kbIds": [base["id"]]}))
        for name, title, text in PAGES:
            data(k.post(f"/v1/sources/{src['id']}/items", json={"name": name, "title": title, "text": text}))
        plain = search(k, base["id"], "domestic wire")
        check(
            "1 by default a search runs neither step and names neither",
            plain.get("passages") and "rerank" not in plain and "rewrite" not in plain,
            {k2: plain.get(k2) for k2 in ("rerank", "rewrite")},
        )
        fused = [p["title"] for p in plain["passages"]]
        retrieval = {"rerank": True, "queryModel": "default"}
        data(k.patch(f"/v1/knowledge-bases/{base['id']}", json={"retrieval": retrieval}))
        ranked = search(k, base["id"], "domestic wire")
        check(
            "2 with rerank on, the agents' search follows the model's scores and says it reranked",
            ranked.get("rerank", {}).get("ran") is True
            and ranked["passages"][0]["title"] == "Wire fees"
            and ranked["passages"][0]["reranked"] == 9
            and ranked["passages"][-1]["reranked"] == 0,
            {
                "fused": fused,
                "rerank": ranked.get("rerank"),
                "ranked": [(p["title"], p.get("reranked")) for p in ranked.get("passages", [])],
            },
        )
        rewrite = {"rerank": False, "rewrite": "rewrite", "rewriteInstructions": "Use the bank's payment terms."}
        data(k.patch(f"/v1/knowledge-bases/{base['id']}", json={"retrieval": rewrite}))
        asked = data(k.post(f"/v1/knowledge-bases/{base['id']}/query", json={"question": "how late can money leave"}))
        check(
            "3 with rewrite on, the Playground's query shows the question as asked and as searched, and finds the cutoff",
            asked["rewrite"]["asked"] == "how late can money leave"
            and asked["rewrite"]["rewritten"] == "domestic wire cutoff"
            and asked["passages"][0]["title"] == "Wire cutoff",
            {"rewrite": asked.get("rewrite"), "titles": [p["title"] for p in asked.get("passages", [])]},
        )
        refused = k.patch(f"/v1/knowledge-bases/{base['id']}", json={"retrieval": {"rewrite": "expand"}})
        check(
            "4 a rewrite mode that is not built is refused",
            refused.status_code == 400 and refused.json()["error"]["code"] == "invalid_retrieval",
            refused.text[:300],
        )
    finish()


main()
