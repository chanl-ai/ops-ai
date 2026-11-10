# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-676 typed text and pushed items become cited knowledge, api layer: docs/usecases/kb-service/typed-text-and-pushed-
items.md. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import check, data, finish, kb, put_in_files

OWNER = "maya@harborpine.example"
ESCROW = {
    "name": "escrow-analysis",
    "title": "Escrow analysis",
    "text": "## Shortage\n\nAn escrow shortage is spread over twelve payments.",
}


def search(k: Any, kb_id: str, question: str) -> list[dict[str, Any]]:
    return (data(k.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question})) or {}).get(
        "passages"
    ) or []


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-676-") as tmp, kb(Path(tmp) / "files") as k:
        kinds = data(k.get("/v1/knowledge/source-kinds")) or []
        check(
            "1 Add source lists typed text and push beside files, each starting with a manual schedule",
            [(x["type"], x["defaults"]["schedule"]["kind"]) for x in kinds if x["group"] == "built_in"]
            == [("file", "manual"), ("text", "manual"), ("push", "manual")],
            kinds,
        )
        base = data(k.post("/v1/knowledge-bases", json={"name": "Mortgage servicing", "owner": OWNER}))
        text = data(k.post("/v1/sources", json={"type": "text", "name": "Servicing notes", "kbIds": [base["id"]]}))
        page = data(k.post(f"/v1/sources/{text['id']}/items", json=ESCROW))
        check(
            "2 a typed page is stored as a file and indexed at once",
            page["outcome"] == "created" and page["item"]["status"] == "indexed" and page["item"]["fileId"],
            page,
        )
        found = search(k, base["id"], "escrow shortage payments")
        check(
            "3 the agents' search returns the page's section with its version",
            bool(found) and "twelve payments" in found[0]["text"] and found[0]["version"] == "v1",
            found[:1],
        )
        push = data(k.post("/v1/sources", json={"type": "push", "name": "Rate desk feed", "kbIds": [base["id"]]}))
        rate = {
            "name": "rates/fixed-30",
            "title": "Thirty-year fixed",
            "text": "The thirty-year fixed rate is 6.1 percent.",
        }
        first = data(k.post(f"/v1/sources/{push['id']}/items", json=rate))
        runs = (data(k.get(f"/v1/sources/{push['id']}/runs")) or {}).get("pagination", {}).get("total")
        again = data(k.post(f"/v1/sources/{push['id']}/items", json=rate))
        runs_after = (data(k.get(f"/v1/sources/{push['id']}/runs")) or {}).get("pagination", {}).get("total")
        check(
            "4 a pushed item sent twice is unchanged the second time and starts no sync",
            (first["outcome"], again["outcome"]) == ("created", "unchanged")
            and again["item"]["id"] == first["item"]["id"]
            and runs == runs_after,
            {"first": first["outcome"], "again": again["outcome"], "runs": [runs, runs_after]},
        )
        moved = data(
            k.post(
                f"/v1/sources/{push['id']}/items", json={**rate, "text": "The thirty-year fixed rate is 5.9 percent."}
            )
        )
        found = search(k, base["id"], "thirty-year fixed rate")
        check(
            "5 the same name with new content is its next version, and search quotes the new text",
            moved["outcome"] == "updated"
            and moved["item"]["version"] == "v2"
            and bool(found)
            and "5.9 percent" in found[0]["text"]
            and "6.1" not in " ".join(p["text"] for p in found),
            {"moved": moved["outcome"], "found": [p["text"][:60] for p in found]},
        )
        pdf = (Path(__file__).parents[4] / "services/kb-service/seed/pdfs/retail-product-sheet.pdf").read_bytes()
        sheet = data(
            k.post(
                f"/v1/sources/{push['id']}/items",
                json={
                    "name": "product-sheet.pdf",
                    "content": base64.b64encode(pdf).decode(),
                    "mime": "application/pdf",
                },
            )
        )
        check(
            "6 a pushed PDF is read like an upload and indexed with its pages",
            sheet and sheet["item"]["status"] == "indexed" and sheet["item"].get("pageCount", 0) >= 1,
            sheet,
        )
        fid = put_in_files(k.files_url, "policy.pdf", pdf)
        files_src = data(k.post("/v1/sources", json={"type": "file", "name": "Policy PDFs", "fileIds": [fid]}))
        refused = k.post(f"/v1/sources/{files_src['id']}/items", json=rate)
        check(
            "7 an item cannot be written into a source that takes its items from Files",
            refused.status_code == 400 and refused.json()["error"]["code"] == "source_not_written",
            refused.text[:300],
        )
    finish()


main()
