# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-672 every file is read once, api layer: docs/usecases/documents-service/files-read-once.md.

Own files-service (scanning off), documents-service and kb-service on the run's database. Tesseract on this machine
reads the scans; no model is called."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import ROOT, check, data, finish, kb, put_in_files, until

FIXTURES = ROOT / "packages" / "ops_ingest" / "tests" / "fixtures"
OPS = {"X-Team-Id": "team_ops"}
RUN = int(time.time())


def reading(documents: httpx.Client, file_id: str) -> dict[str, Any]:
    """The finished reading, waited for in the background."""
    found = until(
        lambda: (
            (r := data(documents.get(f"/v1/documents/readings/{file_id}"))) and r["status"] in ("done", "failed") and r
        ),
        timeout=90,
    )
    return found or {}


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc-672-") as tmp,
        kb(Path(tmp)) as k,
        httpx.Client(base_url=k.documents_url, headers=OPS, timeout=120) as documents,
    ):
        ids = {
            name: put_in_files(k.files_url, name, (FIXTURES / name).read_bytes())
            for name in ("scanned.pdf", "half_scan.pdf", "form.pdf")
        }

        asked = documents.post("/v1/documents/readings", json={"fileId": ids["scanned.pdf"], "ocr": "auto"})
        check(
            "1 a scan is queued, not read inside the request",
            asked.status_code == 202 and data(asked)["status"] == "queued",
            asked.text[:300],
        )
        scan = reading(documents, ids["scanned.pdf"])
        page = (scan.get("pages") or [{}])[0]
        check(
            "2 the scan's page is read by OCR, with its words and a confidence",
            scan.get("status") == "done"
            and page.get("source") == "ocr"
            and "LATE PAYMENT FEE" in page.get("text", "").upper()
            and bool(page.get("ocr")),
            {
                "status": scan.get("status"),
                "source": page.get("source"),
                "text": page.get("text", "")[:120],
                "ocr": page.get("ocr"),
            },
        )

        documents.post("/v1/documents/readings", json={"fileId": ids["half_scan.pdf"]})
        half = (reading(documents, ids["half_scan.pdf"]).get("pages") or [{}])[0]
        wanted = ["+1 415 555 0142", "m.okonkwo@example.org", "2026-02-19"]
        check(
            "3 a half-scanned page reads as mixed, with the values only in its picture",
            half.get("source") == "mixed" and all(v in half.get("text", "") for v in wanted),
            {"source": half.get("source"), "missing": [v for v in wanted if v not in half.get("text", "")]},
        )

        form = documents.post("/v1/documents/readings", json={"fileId": ids["form.pdf"]})
        fields = {f["name"]: f["value"] for p in data(form).get("pages") or [] for f in p.get("formFields") or []}
        check(
            "4 a filled form reads at once with its typed values",
            form.status_code == 200 and len(fields) == 8 and fields.get("policy_number") == "PL-90385217",
            {"status": form.status_code, "fields": fields},
        )

        again = documents.post("/v1/documents/readings", json={"fileId": ids["scanned.pdf"], "ocr": "auto"})
        check(
            "5 a second ask for the scan answers at once from the stored reading",
            again.status_code == 200
            and data(again)["status"] == "done"
            and data(again)["pages"][0]["text"] == page.get("text"),
            {"status": again.status_code, "reading": data(again).get("status")},
        )
        other = documents.post(
            "/v1/documents/readings", json={"fileId": ids["scanned.pdf"]}, headers={"X-Team-Id": "team_cards"}
        )
        check(
            "6 another team cannot read the scan, though its reading is stored",
            other.status_code == 404,
            other.text[:200],
        )

        base = data(
            k.post("/v1/knowledge-bases", json={"name": f"Member forms {RUN}", "owner": "maya@harborpine.example"})
        )
        source = data(
            k.post(
                "/v1/sources",
                json={"type": "file", "name": f"Member files {RUN}", "collection": "Members", "kbIds": [base["id"]]},
            )
        )
        data(k.post(f"/v1/sources/{source['id']}/files", json={"fileIds": list(ids.values())}))
        synced = data(k.post(f"/v1/sources/{source['id']}/sync"))
        items = (
            until(
                lambda: (
                    (rows := data(k.get(f"/v1/sources/{source['id']}/items"))["data"])
                    and all(i["status"] == "indexed" for i in rows)
                    and rows
                ),
                timeout=90,
            )
            or data(k.get(f"/v1/sources/{source['id']}/items"))["data"]
        )
        check(
            "7 the knowledge base indexes all three files from their readings",
            len(items) == 3 and all(i["status"] == "indexed" for i in items),
            {"sync": synced["counts"], "items": [(i["path"], i["status"], i.get("error")) for i in items]},
        )
        fee = data(
            k.post(f"/v1/knowledge-bases/{base['id']}/query", json={"question": "What is the late payment fee?"})
        )
        policy = data(k.post(f"/v1/knowledge-bases/{base['id']}/query", json={"question": "policy_number PL-90385217"}))
        scan_item = next((i for i in items if i["path"] == "scanned.pdf"), {})
        top = (fee.get("citations") or [{}])[0]
        check(
            "8 the answer cites the scanned page, the item says OCR read it, and the form's policy number is found",
            top.get("title") == scan_item.get("title") and top.get("page") == 1 and "read by OCR" in (scan_item.get("warning") or "")
            and any("PL-90385217" in c.get("snippet", "") for c in policy.get("citations") or []),
            {"cited": top, "warning": scan_item.get("warning"), "policy": [c.get("snippet", "")[:80] for c in policy.get("citations") or []]},
        )  # fmt: skip


main()
finish()
