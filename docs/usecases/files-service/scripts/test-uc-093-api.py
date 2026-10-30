"""uc-093 a member stores a file once in files-service and it is downloaded, held and deleted under its rules, api
layer: docs/usecases/files-service/file-lifecycle.md. platform-service and files-service run on the use case's own
ports and database; files-service verifies platform tokens locally, keeps bytes on the local backend and leaves files
pending until the scan hook reports. No model is called."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import check, data, files, finish, platform, service_headers

PASSWORD = "northfield-demo"
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n"


def person(public: httpx.Client, email: str, team: str) -> dict[str, str]:
    token = data(public.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": team}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc093-") as tmp, platform() as (public, _), files(Path(tmp)) as f:
        james = person(public, "j.richardson@harborpine.example", "team_ops")
        priya = person(public, "p.shah@harborpine.example", "team_ops")
        scanner = service_headers("files", service="scanner", scopes=["files:decide"])
        kb = service_headers("files", service="kb")

        body = {"name": "Q3 statement.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "case_attachment"}
        ticket: dict[str, Any] = data(f.post("/v1/files/uploads", json=body, headers=james))
        check(
            "the local backend's ticket is files-service's own content route",
            ticket["uploadUrl"].endswith(f"/v1/files/uploads/{ticket['fileId']}/content"),
            ticket,
        )
        put = f.put(ticket["uploadUrl"], content=PDF, headers={**james, **ticket["headers"]})
        done = data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=james))
        stored = done["file"]
        check(
            "complete stores it once with its sha256, the sniffed type and its retention class",
            put.status_code == 204
            and stored["digest"] == hashlib.sha256(PDF).hexdigest()
            and stored["retention"]["classId"] == "standard"
            and done["deduplicated"] is False,
            done,
        )
        file_id = stored["id"]
        got = data(f.get(f"/v1/files/{file_id}", headers=james))
        check(
            "get returns its metadata, pending a scan",
            got["scan"]["status"] == "pending" and got["versionCount"] == 1,
            got,
        )

        locked = f.post(f"/v1/files/{file_id}/download-url", headers=james)
        check("a file not yet scanned clean cannot be downloaded (423)", locked.status_code == 423, locked.text)
        verdict = {"fileId": file_id, "status": "clean", "engine": "clamav"}
        refused = f.post("/v1/files/scan-results", json=verdict, headers=kb)
        check("a service without files:decide records no verdict", refused.status_code == 403, refused.status_code)
        scanned = data(f.post("/v1/files/scan-results", json=verdict, headers=scanner))
        check("the scan hook records the scanner's verdict", scanned["scan"]["status"] == "clean", scanned)
        link = data(f.post(f"/v1/files/{file_id}/download-url", headers=james))
        content = f.get(link["url"], headers=james)
        check(
            "once clean, the download link returns the same bytes as an attachment",
            content.status_code == 200
            and content.content == PDF
            and "attachment" in content.headers["content-disposition"],
            content.status_code,
        )
        mine = data(f.get("/v1/files", params={"uploadedBy": "me"}, headers=james))
        check("list by owner finds it among the uploader's files", file_id in [r["id"] for r in mine["data"]], mine)

        hold = {"ids": [file_id], "hold": True, "reason": "Litigation hold, matter 2026-114"}
        refused = f.post("/v1/files/legal-hold", json=hold, headers=james)
        check("a builder cannot place a legal hold (403)", refused.status_code == 403, refused.text)
        placed = data(f.post("/v1/files/legal-hold", json=hold, headers=priya))
        check("the team admin places it", placed["updated"] == [file_id], placed)
        held = f.delete(f"/v1/files/{file_id}", headers=james)
        check("a held file cannot be deleted (409)", held.status_code == 409, held.text)
        release = {**hold, "hold": False, "reason": "Matter closed"}
        released = data(f.post("/v1/files/legal-hold", json=release, headers=priya))
        check("the team admin releases it", released["updated"] == [file_id], released)
        deleted = f.delete(f"/v1/files/{file_id}", headers=james)
        gone = f.get(f"/v1/files/{file_id}", headers=james)
        check("released, it deletes, and is gone", deleted.status_code == 204 and gone.status_code == 404, gone.text)
    finish()


if __name__ == "__main__":
    main()
