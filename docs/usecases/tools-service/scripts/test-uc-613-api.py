# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-613 An agent reads a team's file and a document's fields by its type, api layer:
docs/usecases/tools-service/an-agent-reads-a-team-file.md.

Own services, no real model: models-service on documents-service's fake model (an answer per fixture), files-service
with scanning off, documents-service with the seeded document types, and tools-service reading through those two.
Calls go through the gateway's /v1/calls as an agent run of team_ops would; team_retail holds a file of its own."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import ROOT, check, data, fake_openai, finish, kb, models, service_headers, tools

DOCS = ROOT / "services" / "documents-service"
RULES = DOCS / "tests" / "fixtures" / "fake-model"
LEVY = DOCS / "tests" / "fixtures" / "tax_levy" / "TAXLEVY01.pdf"
OPS, RETAIL = "team_ops", "team_retail"
BUILT_IN = ("builtin:files", "builtin:document-types")


def upload(files_url: str, team: str, name: str, body: bytes) -> str:
    with httpx.Client(base_url=files_url, headers={"X-Team-Id": team}, timeout=60) as f:
        meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
        ticket = data(f.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
        f.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
        return str(data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def call(gw: httpx.Client, tool: str, step: str, team: str = OPS, **arguments: Any) -> httpx.Response:
    return gw.post(
        "/v1/calls",
        headers=service_headers("tools", team=team),
        json={"tool": tool, "input": arguments, "key": step, "runContext": {"thread": "uc613", "step": step}},
    )


def output(r: httpx.Response) -> dict[str, Any]:
    body = r.json()
    return dict((body.get("data") or {}).get("output") or body.get("error") or {})


def rows(gw: httpx.Client, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """A list route's rows as a person of team_ops sees them (dev auth)."""
    got = data(gw.get(path, params=params or {}, headers={"X-Team-Id": OPS}))
    found = got.get("data", got.get("items")) if isinstance(got, dict) else got
    return list(found or [])


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc613-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, document_types=True) as knowledge,
    ):
        files_url, documents_url = knowledge.files_url, knowledge.documents_url
        body = LEVY.read_bytes()
        # A trailing comment makes the bytes the team's own: the seeded samples hold the same fixture, and a team's
        # identical bytes are stored once under the first name.
        mine = upload(files_url, OPS, "levy-uc613.pdf", body + b"\n%uc613")
        upload(files_url, RETAIL, "retail-only-uc613.pdf", body + b"\n%retail")
        with httpx.Client(base_url=documents_url, headers={"X-Team-Id": OPS}, timeout=30) as docs:
            kinds = data(docs.get("/v1/document-types"))["items"]
        levy_name = next(k["name"] for k in kinds if k["id"] == "tax_levy")
        reach = {"OPS_FILES_URL": files_url, "OPS_DOCUMENTS_URL": documents_url}

        with tools(reach) as gw:
            text = call(gw, "read_file", "s1", file="levy-uc613.pdf")
            out = output(text)
            check(
                "1 the agent reads the team's file by name: its name, type and full text, through the gateway",
                text.status_code == 200 and out.get("fileId") == mine and "SYN-TL-2026-0101" in str(out.get("text")),
                {"status": text.status_code, "out": {k: str(v)[:120] for k, v in out.items()}},
            )
            fields = call(gw, "read_document", "s2", file=mine, documentType=levy_name)
            got = output(fields).get("fields") or {}
            check(
                "2 it reads the document's fields with the team's document type: the amount due is 7482.19",
                fields.status_code == 200 and (got.get("amount_due") or {}).get("value") == 7482.19,
                {"status": fields.status_code, "fields": {k: (v or {}).get("value") for k, v in got.items()}},
            )
            logged = [rows(gw, "/v1/executions", {"tool": t}) for t in ("read_file", "read_document")]
            # A built-in app has its own menu, not a card on the Apps grid (2026-11-01); its page answers.
            pages = {a: data(gw.get(f"/v1/apps/{a}", headers={"X-Team-Id": OPS})) or {} for a in BUILT_IN}
            names = {(p.get("card") or {}).get("name") for p in pages.values()}
            check(
                "3 each read is in the call log, and Files and Document types are the team's built-in apps",
                all(logged) and {"Files", "Document types"} <= names,
                {"logged": [len(x) for x in logged], "names": sorted(str(n) for n in names)},
            )
            elsewhere = call(gw, "read_file", "s4", file="retail-only-uc613.pdf")
            check(
                "4 another team's file is never found, by name, and nothing is read",
                "no file named" in str(output(elsewhere).get("error")),
                {"status": elsewhere.status_code, "out": output(elsewhere)},
            )
    finish()


if __name__ == "__main__":
    main()
