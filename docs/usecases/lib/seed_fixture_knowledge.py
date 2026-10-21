"""Puts the agents-service fixture knowledge into a use case's kb-service, through kb-service's own API: each
knowledge base under the id the seeded agents were granted (kb_people, kb_eng, ...), one file source per base, and each
fixture passage put in Files as a markdown document under its title and section, added to the source by id, then
synced. Both harnesses run it.

    uv run python docs/usecases/lib/seed_fixture_knowledge.py --kb http://127.0.0.1:8793 --files http://127.0.0.1:8794
    uv run python docs/usecases/lib/seed_fixture_knowledge.py --kb ... --platform http://127.0.0.1:8810  # signs in
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "agents-service" / "tests" / "fixtures" / "seed"
# platform-service's dev seed (James Richardson, builder); the password is the dev seed's.
EMAIL, PASSWORD = "j.richardson@harborpine.example", "northfield-demo"


def headers(platform: str | None) -> dict[str, str]:
    if not platform:
        return {}
    r = httpx.post(f"{platform}/v1/auth/sign-in", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"seed_fixture_knowledge: sign-in failed: {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def ok(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        sys.exit(f"seed_fixture_knowledge: {r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}")
    return r.json()["data"] if r.content else None


def put_in_files(files: httpx.Client, name: str, body: bytes) -> str:
    """The console's upload: a ticket, the bytes, then complete; returns the file id."""
    meta = {"name": name, "size": len(body), "mime": "text/markdown", "purpose": "knowledge_source"}
    ticket = ok(files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
    ok(files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body))
    return str(ok(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def seed(kb: httpx.Client, files: httpx.Client, owner: str) -> dict[str, int]:
    bases = json.loads((FIXTURES / "knowledge_bases.json").read_text())
    passages = json.loads((FIXTURES / "passages.json").read_text())
    indexed: dict[str, int] = {}
    for base in bases:
        made = kb.post("/v1/knowledge-bases", json={"id": base["id"], "name": base["name"], "owner": owner})
        if made.status_code == 409:
            # Seeded by an earlier use case on the same run database: already indexed.
            continue
        ok(made)
        source = ok(
            kb.post(
                "/v1/sources",
                # The source is owned by whoever seeds it, so the same caller may upload and sync into it.
                json={"type": "file", "name": f"{base['name']} documents", "kbIds": [base["id"]]},
            )
        )
        ids = [
            put_in_files(
                files, f"{p['document_id']}.md", f"# {p['title']}\n\n## {p['section']}\n\n{p['text']}\n".encode()
            )
            for p in passages
            if p["kb_id"] == base["id"]
        ]
        if ids:
            ok(kb.post(f"/v1/sources/{source['id']}/files", json={"fileIds": ids}))
        run = ok(kb.post(f"/v1/sources/{source['id']}/sync"))
        indexed[base["id"]] = int(run["counts"]["upserted"])
    return indexed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", required=True, help="kb-service base URL")
    ap.add_argument("--files", required=True, help="files-service base URL; kb-service reads its files there")
    ap.add_argument("--platform", help="platform-service base URL: sign in as James; omitted, kb-service runs dev auth")
    args = ap.parse_args()
    auth = headers(args.platform)
    with (
        httpx.Client(base_url=args.kb, headers=auth, timeout=120) as kb,
        httpx.Client(base_url=args.files, headers=auth, timeout=120) as files,
    ):
        # Each base is owned by whoever seeds it: kb-service links a source to a base only for its owner or an admin of
        # its team (c-115). Under dev auth that is the dev user, James unless OPS_DEV_USER_EMAIL names another.
        owner = EMAIL if args.platform else os.environ.get("OPS_DEV_USER_EMAIL", EMAIL)
        print(json.dumps(seed(kb, files, owner)))


if __name__ == "__main__":
    main()
