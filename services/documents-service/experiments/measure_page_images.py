"""Field accuracy of scans read with and without the page image, on the shared stack with the real extract alias
(c-295).

    uv run python experiments/measure_page_images.py
    uv run python experiments/measure_page_images.py --images-only < earlier.jsonl   # reuses its text reads

Two levy scans that take the model path are read text-only, then again with page images on: a version of their type
with pageImages (by a team admin), the team's pageImages policy (by the workspace's Security admin) and an extract
alias version cleared for images. One invoice scan read by its template, with a review threshold above its OCR
confidence, shows a doubtful field's crop on the re-read. The team policy is turned off again at the end. A guard stops
before any read that could take the run past 10 provider calls. Prints one JSON object per read and a summary; the
2026-10-19 run's output is measure_page_images_results.jsonl."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg
import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
from ops_documents.document_types import dated, matches  # noqa: E402
from ops_identity import mint_service_token  # noqa: E402
from ops_identity.service_keys import dev_service_signer  # noqa: E402

DB = "postgresql://ops:ops@localhost:5477/ops_runtime"
PLATFORM, FILES, DOCS, MODELS = (f"http://127.0.0.1:{p}" for p in (8710, 8750, 8760, 8730))
CAP = 10
# The most provider calls one read makes here: the first read and its one re-read.
PER_READ = 2
SCANS = [("restraining_notice", "TEST001_scan.pdf"), ("tax_levy", "TAXLEVY03_scan.pdf")]
DOUBTFUL = ("supplier_invoice", "INVA07_scan.pdf", 0.99)
SENT = (
    "select count(*), coalesce(sum(cost), 0), coalesce(sum(images), 0) from model_call_log"
    " where run_id = any($1) and outcome <> 'denied'"
)


def seeded() -> dict[str, tuple[dict[str, Any], Path]]:
    spec = importlib.util.spec_from_file_location("seed_document_types", ROOT / "scripts" / "seed_document_types.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_document_types"] = module
    spec.loader.exec_module(module)
    return {d["id"]: (d, folder) for d, _, folder in module.SEEDED.values()}


def person(email: str, base: str) -> httpx.Client:
    password = os.environ.get("OPS_PLATFORM_DEMO_PASSWORD", "northfield-demo")
    token = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": password}).json()["data"][
        "token"
    ]
    headers = {"Authorization": f"Bearer {token}", "X-Team-Id": "team_ops"}
    return httpx.Client(base_url=base, headers=headers, timeout=300)


def upload(files: httpx.Client, path: Path) -> str:
    body = path.read_bytes()
    meta = {"name": path.name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket = files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}).json()["data"]
    files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
    return str(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete").json()["data"]["file"]["id"])


async def sent(runs: list[str]) -> tuple[int, float, int]:
    c = await asyncpg.connect(DB)
    row = await c.fetchrow(SENT, runs)
    await c.close()
    assert row is not None
    return int(row[0]), float(row[1]), int(row[2])


def scored(fields: list[dict[str, Any]], order: str | None, expected: dict[str, Any], got: dict[str, Any]) -> list[str]:
    by_key = {f["key"]: f for f in dated(fields, order)}
    found = got.get("fields") or {}
    return [
        k for k in expected if k in by_key and not matches(by_key[k], expected[k], (found.get(k) or {}).get("value"))
    ]


def latest(documents: httpx.Client, type_id: str) -> dict[str, Any]:
    found = documents.get(f"/v1/document-types/{type_id}").json()["data"]
    return next(v for v in found["versions"] if v["version"] == found["latestVersion"])


def main() -> None:
    kinds = seeded()
    builder_docs, files = (
        person("j.richardson@northfieldbank.com", DOCS),
        person("j.richardson@northfieldbank.com", FILES),
    )
    admin_docs = person("p.shah@northfieldbank.com", DOCS)
    security = person("w.kamau@northfieldbank.com", PLATFORM)
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    models = httpx.Client(base_url=MODELS, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    runs: list[str] = []
    rows: list[dict[str, Any]] = []

    def read(type_id: str, name: str, mode: str, review_below: float | None = None) -> None:
        used = asyncio.run(sent(runs))[0] if runs else 0
        if used + PER_READ > CAP:
            print(json.dumps({"stopped": f"{name} {mode}: {used} calls used, a read may take {PER_READ}"}))
            return
        _, folder = kinds[type_id]
        expected = json.loads((folder / "expected.json").read_text())[name]["expected"]
        version = latest(builder_docs, type_id)
        body: dict[str, Any] = {"fileId": upload(files, folder / name), "documentTypeId": type_id, "ocr": True}
        if review_below is not None:
            body["reviewBelow"] = review_below
        started = time.monotonic()
        got = builder_docs.post("/v1/documents/extractions", json=body).json()["data"]
        seconds = round(time.monotonic() - started, 2)
        runs.append(got["id"])
        calls, cost, images = asyncio.run(sent([got["id"]]))
        wrong = scored(version["fields"], version.get("dateOrder"), expected, got)
        row = {
            "file": name, "mode": mode, "path": got.get("path"), "right": len(expected) - len(wrong),
            "total": len(expected), "wrong": wrong, "calls": calls, "images": images, "cost": round(cost, 6),
            "seconds": seconds, "imageCalls": got.get("imageCalls"), "imageRefused": got.get("imageRefused"),
            "extraction": got["id"],
        }  # fmt: skip
        rows.append(row)
        print(json.dumps(row), flush=True)

    if "--images-only" in sys.argv:
        # The text reads of an earlier run, from its output on stdin; their calls count toward the cap.
        for line in sys.stdin:
            row = json.loads(line)
            if row.get("mode") == "text":
                rows.append(row)
                runs.append(row["extraction"])
                print(json.dumps(row), flush=True)
    else:
        for type_id, name in SCANS:
            read(type_id, name, "text")
    current = models.get("/v1/models/aliases").json()["data"]
    extract = next(a for a in current if a["name"] == "extract")
    keep = ("providerId", "modelId", "clearedSensitivity", "inputPerMillion", "outputPerMillion", "reasoningEffort")
    version = {k: extract[k] for k in keep if extract.get(k) is not None} | {"images": True}
    if not extract.get("images"):
        models.post("/v1/models/aliases/extract/versions", json=version).raise_for_status()
    # pageImages is per team: a true or false put with X-Team-Id sets that team's part only.
    security.put("/v1/policies/pageImages", json={"value": True}).raise_for_status()
    types = sorted({t for t, _ in SCANS} | {DOUBTFUL[0]})

    def switch(on: bool) -> None:
        # Templates, checks and offerAt carry forward when left out, so only the switch changes.
        for type_id in types:
            v = latest(admin_docs, type_id)
            keep = {
                "fields": v["fields"],
                "many": v["many"],
                "reviewBelow": v["reviewBelow"],
                "dateOrder": v["dateOrder"],
            }
            body = keep | {"pageImages": on, "note": f"c-295 measurement: page images {'on' if on else 'off'}"}
            admin_docs.post(f"/v1/document-types/{type_id}/versions", json=body).raise_for_status()

    try:
        switch(True)
        for type_id, name in SCANS:
            read(type_id, name, "images")
        read(DOUBTFUL[0], DOUBTFUL[1], "doubtful crop", DOUBTFUL[2])
    finally:
        switch(False)
        security.put("/v1/policies/pageImages", json={"value": False}).raise_for_status()
    calls, cost, images = asyncio.run(sent(runs))
    summary: dict[str, Any] = {"calls": calls, "cost": round(cost, 6), "imageParts": images}
    for mode in ("text", "images"):
        of = [r for r in rows if r["mode"] == mode]
        summary[mode] = f"{sum(r['right'] for r in of)}/{sum(r['total'] for r in of)}"
    print(json.dumps({"summary": summary}))


if __name__ == "__main__":
    main()
