"""Accuracy, time and cost of a read per path, on the shared stack with the real extract alias (c-255).

    uv run python experiments/measure_paths.py

Ten real model reads, the owner's cap: five levy fixtures and five that are not levies. A template is then suggested
from one real read of each non-levy master form, saved as a new version, and the rest of that form is read by it,
which calls no model. The script stops before an eleventh model call. Prints one JSON object per read and a summary
per path; the levy reads measured earlier the same day are added from the database, marked stored. The 2026-10-19
runs' output (run 1 the model reads, run 2 with --reuse the template reads and the summary) is
measure_paths_results.jsonl."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
from ops_documents.document_types import dated, matches  # noqa: E402
from ops_extract import templates  # noqa: E402
from ops_extract.layout import build_layout  # noqa: E402

DB = "postgresql://ops:ops@localhost:5477/ops_runtime"
CALLS = "select count(*), coalesce(sum(cost), 0), coalesce(sum(latency_ms), 0) from model_call_log where run_id = $1"
CAP = 10
REAL = [
    ("restraining_notice", "TEST001.pdf"),
    ("restraining_notice", "TEST003.pdf"),
    ("restraining_notice", "TEST009.pdf"),
    ("tax_levy", "TAXLEVY03.pdf"),
    ("tax_levy", "TAXLEVY04.pdf"),
    ("supplier_invoice", "INVA01.pdf"),
    ("supplier_invoice", "INVB01.pdf"),
    ("supplier_invoice", "INVA08_scan.pdf"),
    ("bank_statement", "STMTA01.pdf"),
    ("bank_statement", "STMTB01.pdf"),
]
TEMPLATE_READS = {
    "supplier_invoice": [
        "INVA02.pdf",
        "INVA03.pdf",
        "INVA04.pdf",
        "INVA05.pdf",
        "INVA06.pdf",
        "INVA07_scan.pdf",
        "INVA08_scan.pdf",
    ],
    "bank_statement": [
        "STMTA02.pdf",
        "STMTA03.pdf",
        "STMTA04.pdf",
        "STMTA05.pdf",
        "STMTA06.pdf",
        "STMTA07_scan.pdf",
        "STMTA08_scan.pdf",
    ],
}
MASTERS = {"supplier_invoice": "INVA01.pdf", "bank_statement": "STMTA01.pdf"}
# The five default-effort levy reads measured on 2026-10-19 before the cleanup rules (c-287): kept, not repeated, and
# reported as stored with the values they saved then.
STORED_SINCE, STORED_UNTIL = "2026-10-19T01:45:33Z", "2026-10-19T01:48:16Z"


def seeded() -> dict[str, tuple[dict[str, Any], Path]]:
    spec = importlib.util.spec_from_file_location("seed_document_types", ROOT / "scripts" / "seed_document_types.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_document_types"] = module
    spec.loader.exec_module(module)
    return {d["id"]: (d, folder) for d, _, folder in module.SEEDED.values()}


def client(base: str) -> httpx.Client:
    password = os.environ.get("OPS_PLATFORM_DEMO_PASSWORD", "northfield-demo")
    r = httpx.post(
        "http://127.0.0.1:8710/v1/auth/sign-in", json={"email": "j.richardson@harborpine.example", "password": password}
    )
    token = r.json()["data"]["token"]
    return httpx.Client(
        base_url=base, headers={"Authorization": f"Bearer {token}", "X-Team-Id": "team_ops"}, timeout=300
    )


def upload(files: httpx.Client, path: Path) -> str:
    body = path.read_bytes()
    meta = {"name": path.name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket = files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}).json()["data"]
    files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
    return str(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete").json()["data"]["file"]["id"])


async def calls(run_id: str) -> tuple[int, float, int]:
    c = await asyncpg.connect(DB)
    row = await c.fetchrow(
        CALLS,
        run_id,
    )
    await c.close()
    return int(row[0]), float(row[1]), int(row[2])


def scored(definition: dict[str, Any], expected: dict[str, Any], got: dict[str, Any]) -> tuple[int, int, list[str]]:
    fields = {f["key"]: f for f in dated(definition["fields"], definition.get("dateOrder"))}
    found = got.get("fields") or {}
    keys = [k for k in expected if k in fields]
    wrong = [k for k in keys if not matches(fields[k], expected[k], (found.get(k) or {}).get("value"))]
    return len(keys) - len(wrong), len(keys), wrong


def measure(
    documents: httpx.Client, files: httpx.Client, kinds: dict[str, Any], type_id: str, name: str
) -> dict[str, Any]:
    definition, folder = kinds[type_id]
    entry = json.loads((folder / "expected.json").read_text())[name]
    fid = upload(files, folder / name)
    started = time.monotonic()
    got = documents.post(
        "/v1/documents/extractions",
        json={"fileId": fid, "documentTypeId": type_id, "ocr": bool(entry.get("imageOnly"))},
    ).json()["data"]
    seconds = round(time.monotonic() - started, 2)
    n, cost, latency = asyncio.run(calls(got["id"]))
    right, total, wrong = scored(definition, entry["expected"], got)
    return {
        "file": name,
        "type": type_id,
        "path": got.get("path"),
        "right": right,
        "of": total,
        "wrong": wrong,
        "seconds": seconds,
        "modelCalls": n,
        "cost": round(cost, 6),
        "modelMs": latency,
        "id": got["id"],
    }


async def stored(kinds: dict[str, Any]) -> list[dict[str, Any]]:
    c = await asyncpg.connect(DB)
    since = datetime.fromisoformat(STORED_SINCE.replace("Z", "+00:00"))
    until = datetime.fromisoformat(STORED_UNTIL.replace("Z", "+00:00"))
    rows = await c.fetch(
        "select e.id, e.type_id, e.result, f.name from extractions e join files f on f.id = e.file_id "
        "where e.asked_at >= $1 and e.asked_at < $2 and e.status = 'done' order by e.asked_at",
        since,
        until,
    )
    out = []
    for r in rows:
        if r["type_id"] not in kinds:
            continue
        definition, folder = kinds[r["type_id"]]
        entry = json.loads((folder / "expected.json").read_text()).get(r["name"])
        if entry is None:
            continue
        log = await c.fetchrow(
            CALLS,
            r["id"],
        )
        right, total, wrong = scored(definition, entry["expected"], json.loads(r["result"]))
        out.append(
            {
                "file": r["name"],
                "type": r["type_id"],
                "path": "model",
                "right": right,
                "of": total,
                "wrong": wrong,
                "seconds": round(int(log[2]) / 1000, 2),
                "modelCalls": int(log[0]),
                "cost": round(float(log[1]), 6),
                "stored": True,
            }
        )
    await c.close()
    return out


def would_match(template: dict[str, Any], folder: Path, name: str, ocr: bool) -> bool:
    """Whether the template matches the file, checked here before the read so a miss never spends a model call."""
    layout = build_layout((folder / name).read_bytes(), filename=name, ocr=ocr)
    return isinstance(templates.match(template, layout), templates.Match)


def main() -> None:
    kinds = seeded()
    reads: list[dict[str, Any]] = []
    # `--reuse out.jsonl`: the model reads of an earlier run, so a second run measures the template path with no call.
    reuse = Path(sys.argv[sys.argv.index("--reuse") + 1]) if "--reuse" in sys.argv else None
    with client("http://127.0.0.1:8760") as documents, client("http://127.0.0.1:8750") as files:
        spent = 0
        if reuse is not None:
            for line in reuse.read_text().splitlines():
                row = json.loads(line) if line.startswith('{"file"') else None
                if row and row["path"] == "model":
                    reads.append({**row, "reused": True})
        for type_id, name in [] if reuse is not None else REAL:
            if spent >= CAP:
                sys.exit(f"stopping: {CAP} real model calls spent")
            row = measure(documents, files, kinds, type_id, name)
            spent += row["modelCalls"]
            reads.append(row)
            print(json.dumps(row))
        for type_id, master in MASTERS.items():
            definition, _ = kinds[type_id]
            source = next(r["id"] for r in reads if r["file"] == master)
            draft = documents.post(
                f"/v1/document-types/{type_id}/templates/suggest", json={"extractionIds": [source]}
            ).json()["data"]
            made = documents.post(
                f"/v1/document-types/{type_id}/versions",
                json={"fields": definition["fields"], "templates": [draft["template"]]},
            )
            print(
                json.dumps(
                    {
                        "template": type_id,
                        "saved": made.status_code,
                        "anchors": [a["text"] for p in draft["template"]["pages"] for a in p["anchors"]],
                    }
                )
            )
            _, folder = kinds[type_id]
            entries = json.loads((folder / "expected.json").read_text())
            for name in TEMPLATE_READS[type_id]:
                if not would_match(draft["template"], folder, name, bool(entries[name].get("imageOnly"))):
                    reads.append(
                        {
                            "file": name,
                            "type": type_id,
                            "path": "not read",
                            "right": 0,
                            "of": 0,
                            "wrong": [],
                            "seconds": 0,
                            "modelCalls": 0,
                            "cost": 0.0,
                            "note": "the template misses it; the model would read it",
                        }
                    )
                    print(json.dumps(reads[-1]))
                    continue
                row = measure(documents, files, kinds, type_id, name)
                if row["modelCalls"]:
                    sys.exit(f"{name} called the model on the template path: {row}")
                reads.append(row)
                print(json.dumps(row))
    reads += asyncio.run(stored(kinds))
    summary: dict[str, Any] = {}
    for key in ("model", "template"):
        rows = [r for r in reads if r["path"] == key]
        if rows:
            summary[key] = {
                "reads": len(rows),
                "stored": sum(1 for r in rows if r.get("stored")),
                "accuracy": f"{sum(r['right'] for r in rows)}/{sum(r['of'] for r in rows)}",
                "secondsMean": round(sum(r["seconds"] for r in rows) / len(rows), 2),
                "costMean": round(sum(r["cost"] for r in rows) / len(rows), 6),
            }
    print(json.dumps({"summary": summary}, indent=1))


if __name__ == "__main__":
    main()
