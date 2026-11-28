"""Scores the sample base: loads the 40 files make_base.py wrote into a new knowledge base on a running stack, waits
for them to be read and indexed, asks the 40 questions in questions.json and counts a question answered when one of
the first three citations is a document it expects (at the page it names, when it names one). Prints the score per
kind, each miss, and the model the stack reads pictures with, since a scripted model's descriptions say nothing real.

    make up OPS_PORT_OFFSET=N DEMO_MODEL=fake ...
    OPS_PORT_OFFSET=N uv run python services/kb-service/experiments/sample_base/score.py [BASE_DIR] [--as james]

Run from the repository root; it signs in as a seeded person through scripts/api_as.py, as `make api` does."""

from __future__ import annotations

import argparse
import importlib
import json
import mimetypes
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from ops_ai import OpsAI

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
# A script beside the repo's others, not a package, so it is loaded by name and typed loosely.
api_as: Any = importlib.import_module("api_as")

QUESTIONS = Path(__file__).with_name("questions.json")
WAIT_S = 600


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=str(ROOT / ".run" / "sample-base"))
    ap.add_argument("--as", dest="who", default="james")
    ap.add_argument("--model", default="scripted (DEMO_MODEL=fake)", help="what reads pictures on this stack")
    a = ap.parse_args(argv[1:])
    files = sorted(Path(a.base).iterdir())
    urls: dict[str, str] = api_as.addresses("local")
    session: dict[str, str] = api_as.token("local", a.who, urls)
    with OpsAI(base_url=urls["platform"], services=urls, access_token=session["token"], team=session["team"]) as ops:
        kb = ops.knowledge.add_base(f"Sample project base {time.strftime('%Y-%m-%d %H:%M:%S')}", owner=session["email"])
        ids: list[str] = []
        for f in files:
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            made = ops.upload(f.name, f.read_bytes(), mime=mime, purpose="knowledge_source")
            ids.append(str(made.get("id") or made.get("fileId")))
        ops.raw.kb.knowledge_bases_add_documents(kb["id"], {"fileIds": ids})
        names = _wait_indexed(ops, kb["id"], len(files))
        asked = json.loads(QUESTIONS.read_text())["questions"]
        hits: Counter[str] = Counter()
        misses: list[dict[str, Any]] = []
        for q in asked:
            answer = ops.raw.kb.knowledge_bases_query_knowledge_base(kb["id"], {"question": q["question"]})
            top = [(names.get(c["documentId"], "?"), c.get("page")) for c in answer["citations"][:3]]
            ok = any(n in q["expect"] and (q["page"] is None or p == q["page"]) for n, p in top)
            hits[q["kind"]] += ok
            if not ok:
                misses.append({"id": q["id"], "kind": q["kind"], "question": q["question"], "got": top})
    total = sum(hits.values())
    print(f"base {kb['id']}: {len(files)} documents; pictures read by {a.model}")
    print(f"score: {total} of {len(asked)} answered with a correct citation in the first three")
    print("by kind: " + ", ".join(f"{k} {hits[k]} of 10" for k in ("who", "how", "why", "changed")))
    for m in misses:
        print(
            f"miss {m['id']} {m['kind']}: {m['question']} -> " + "; ".join(f"{n} p{p}" if p else n for n, p in m["got"])
        )
    return 0


def _wait_indexed(ops: OpsAI, kb_id: str, expected: int) -> dict[str, str]:
    """Each indexed document's id to its file name, once every document has left processing."""
    deadline = time.monotonic() + WAIT_S
    while True:
        rows = ops.raw.kb.knowledge_bases_list_documents(kb_id, page_size=100)["data"]
        settled = [r for r in rows if r["status"] not in ("pending", "processing")]
        if len(settled) >= expected or time.monotonic() > deadline:
            not_indexed = [r["path"] for r in rows if r["status"] != "indexed"]
            if not_indexed:
                print(f"not indexed: {not_indexed}", file=sys.stderr)
            return {r["id"]: r["path"].split("/")[-1] for r in rows}
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
