# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-772 search a long document's pieces on the server, api layer: docs/usecases/kb-service/search-a-long-document-s-
pieces.md. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import tempfile
from pathlib import Path

from usecase_harness import check, data, finish, kb

OWNER = "maya@harborpine.example"
TOPICS = ["Escrow shortage", "Late fees", "Rate locks", "Payoff quotes", "Escrow surplus", "Hardship plans"]
HANDBOOK = {
    "name": "servicing-handbook",
    "title": "Servicing handbook",
    "text": "\n\n".join(f"## {t}\n\n{t} are handled by the servicing desk within five business days." for t in TOPICS),
}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-772-") as tmp, kb(Path(tmp) / "files") as k:
        base = data(k.post("/v1/knowledge-bases", json={"name": "Mortgage servicing", "owner": OWNER}))
        text = data(k.post("/v1/sources", json={"type": "text", "name": "Handbook", "kbIds": [base["id"]]}))
        item = data(k.post(f"/v1/sources/{text['id']}/items", json=HANDBOOK))["item"]
        whole = data(k.get(f"/v1/items/{item['id']}/chunks", params={"pageSize": 50}))
        check(
            "1 the pieces tab reads the document's pieces a page at a time, in reading order",
            whole["pagination"]["total"] >= 2 and [c["index"] for c in whole["data"]] == sorted(c["index"] for c in whole["data"]),
            {"total": whole["pagination"]["total"]},
        )
        first = data(k.get(f"/v1/items/{item['id']}/chunks", params={"search": "escrow", "pageSize": 1}))
        rest = data(k.get(f"/v1/items/{item['id']}/chunks", params={"search": "escrow", "pageSize": 1, "page": 2}))
        found = [c["text"] for c in first["data"] + rest["data"]]
        check(
            "2 a search typed in the tab is answered by the server, one page at a time",
            first["pagination"]["hasNext"]
            and all("scrow" in t for t in found)
            and len(found) == 2
            and not any("Late fees" in t for t in found),
            {"first": first["pagination"], "found": found},
        )
        missing = k.get("/v1/items/item_missing/chunks")
        check("3 a document that is not the team's has no pieces to read", missing.status_code == 404, missing.text)
    finish()


if __name__ == "__main__":
    main()
