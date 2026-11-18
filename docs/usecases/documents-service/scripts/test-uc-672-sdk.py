# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-672 every file is read once, sdk layer: docs/usecases/documents-service/files-read-once.md, story S5. A
developer asks for a scanned file's reading through the Python SDK in sdk/python and reads its OCR'd page. Own
files-service, documents-service and kb-service; Tesseract on this machine; no model is called."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, finish, kb, put_in_files, until

sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
from ops_ai import OpsAI
from ops_ai._transport import every_page

SCAN = ROOT / "packages" / "ops_ingest" / "tests" / "fixtures" / "scanned.pdf"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-672-sdk-") as tmp, kb(Path(tmp)) as k:
        fid = put_in_files(k.files_url, "scanned.pdf", SCAN.read_bytes())
        client = OpsAI(base_url="http://127.0.0.1", services={"documents": k.documents_url}, team="team_ops")
        asked: dict[str, Any] = client.raw.documents.documents_ask_reading({"fileId": fid, "ocr": "auto"})
        done = (
            until(
                lambda: (r := client.raw.documents.documents_get_reading(fid, ocr="auto"))["status"] == "done" and r,
                timeout=90,
            )
            or {}
        )
        page = (done.get("pages") or [{}])[0]
        check(
            "1 the SDK asks for a scan's reading, which is queued, then reads its page as OCR'd text",
            asked["status"] == "queued" and page.get("source") == "ocr" and "LATE PAYMENT FEE" in page.get("text", "").upper(),
            {"asked": asked["status"], "source": page.get("source"), "text": page.get("text", "")[:100]},
        )  # fmt: skip

        # 2. Files listed one row a page come back whole: the helper follows every page, whatever the size.
        for n in range(2):
            put_in_files(k.files_url, f"extra-{n}.pdf", SCAN.read_bytes() + bytes([n]))
        files = OpsAI(base_url="http://127.0.0.1", services={"files": k.files_url}, team="team_ops").raw.files
        small = every_page(files.files_list_files, page_size=1)
        whole = every_page(files.files_list_files)
        check(
            "2 files read one row a page and fifty a page are the same rows, three of them past the first page",
            len(small) >= 3 and [f["id"] for f in small] == [f["id"] for f in whole],
            {"small": len(small), "whole": len(whole)},
        )


main()
finish()
