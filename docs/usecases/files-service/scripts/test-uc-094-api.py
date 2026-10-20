"""uc-094 another team's file is missing on every files-service route, api layer:
docs/usecases/files-service/file-team-boundary.md. platform-service and files-service run on the use case's own ports
and database; files-service verifies platform tokens locally. No model is called."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
from usecase_harness import check, data, files, finish, platform, service_headers

PASSWORD = "northfield-demo"
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n"


def person(public: httpx.Client, email: str, team: str) -> dict[str, str]:
    token = data(public.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD}))["token"]
    return {"Authorization": f"Bearer {token}", "X-Team-Id": team}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc094-") as tmp, platform() as (public, _), files(Path(tmp), scanning="off") as f:
        priya = person(public, "p.shah@northfieldbank.com", "team_ops")
        sam = person(public, "s.adeyemi@northfieldbank.com", "team_security")
        body = {"name": "branch audit.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "case_attachment"}
        ticket = data(f.post("/v1/files/uploads", json=body, headers=priya))
        file_id = ticket["fileId"]
        early = [
            f.put(ticket["uploadUrl"], content=PDF, headers={**sam, "Content-Type": "application/pdf"}),
            f.post(f"/v1/files/uploads/{file_id}/complete", headers=sam),
        ]
        f.put(ticket["uploadUrl"], content=PDF, headers={**priya, **ticket["headers"]})
        owned = data(f.post(f"/v1/files/uploads/{file_id}/complete", headers=priya))
        check("the owning team's admin stores the file", owned["file"]["scan"]["status"] == "clean", owned)

        answers = early + [
            f.get(f"/v1/files/{file_id}", headers=sam),
            f.post(f"/v1/files/{file_id}/download-url", headers=sam),
            f.get(f"/v1/files/{file_id}/content", headers=sam),
            f.delete(f"/v1/files/{file_id}", headers=sam),
            f.post("/v1/files/legal-hold", json={"ids": [file_id], "hold": True, "reason": "probe"}, headers=sam),
        ]
        codes = [r.status_code for r in answers]
        check("another team's admin gets 404 on content, complete, get, download link, download and delete", codes[:6] == [404] * 6, codes)
        hold = data(answers[6])
        check("a hold on another team's file is skipped as not found", hold["skipped"] == [{"id": file_id, "reason": "not found"}], hold)
        listed = data(f.get("/v1/files", headers=sam))
        check("the other team's list does not show it", file_id not in [r["id"] for r in listed["data"]], listed)
        posing = f.get(f"/v1/files/{file_id}", headers={**sam, "X-Team-Id": "team_ops"})
        check("naming the owning team without membership is refused", posing.status_code in (401, 403), posing.text)
        tenant = service_headers("files", tenant="another-tenant", service="agents")
        other = f.get(f"/v1/internal/files/{file_id}", params={"team": "team_ops"}, headers=tenant)
        check("a service acting for another tenant gets 404", other.status_code == 404, other.text)
        still = f.get(f"/v1/files/{file_id}", headers=priya)
        check("the owner still reads it", still.status_code == 200, still.text)
    finish()


if __name__ == "__main__":
    main()
