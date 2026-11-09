# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-673 a scanned chat attachment reaches the agent whole, api layer:
docs/usecases/agents-service/scanned-chat-attachment.md.

Own files-service (scanning off), documents-service and kb-service, and agents-service on the scripted model, which
answers "<n> pages" when asked how many pages it got and otherwise cites the attached page sharing most words with the
question. Tesseract on this machine reads the scan; no model is called."""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont
from usecase_harness import agents, check, data, finish, kb, seed_fixture_knowledge, sse, until

TEAM = {"X-Team-Id": "team_ops"}
PAGES = [
    ["Schedule of fees, effective 2026", "Account fees: the monthly fee is waived."],
    ["Card fees", "Replacement debit card: 10 dollars."],
]


def scan() -> bytes:
    """Two pages that are only pictures of printed lines, as a scanner makes them."""
    font = ImageFont.load_default(size=48)
    pictures = []
    for lines in PAGES:
        page = Image.new("L", (1240, 1754), 255)
        draw = ImageDraw.Draw(page)
        for i, line in enumerate(lines):
            draw.text((100, 200 + i * 100), line, fill=0, font=font)
        pictures.append(page)
    out = io.BytesIO()
    pictures[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=pictures[1:])
    return out.getvalue()


def attach(files_url: str, body: bytes) -> dict[str, Any]:
    with httpx.Client(base_url=files_url, headers=TEAM, timeout=60) as f:
        meta = {"name": "fees-scan.pdf", "size": len(body), "mime": "application/pdf", "purpose": "chat_attachment"}
        ticket = data(f.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
        f.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
        stored = data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]
    return {"fileId": stored["id"], "name": stored["name"], "size": stored["size"]}


def say(api: httpx.Client, tid: str, content: str, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    r = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": content, "attachments": files},
        headers={**TEAM, "Accept": "text/event-stream"},
        timeout=180,
    )
    return sse(r.text) if r.status_code == 200 else [{"type": "error", "text": r.text[:300]}]


def reply(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next((e.get("message") or {} for e in reversed(events) if e.get("message")), {})


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-673-") as tmp, kb(Path(tmp)) as k:
        # The seeded agents' knowledge bases, as agents() seeds them for a stack of its own.
        seed_fixture_knowledge(str(k.base_url).rstrip("/"), k.files_url)
        env = {"OPS_FILES_URL": k.files_url, "OPS_DOCUMENTS_URL": k.documents_url}
        with agents(kb_url=str(k.base_url).rstrip("/"), env=env) as api:
            file = attach(k.files_url, scan())
            check("1 the scan is stored in Files as a chat attachment", file["fileId"].startswith("fil_"), file)
            agent = data(api.get("/chat/agents", headers=TEAM))[0]["id"]
            tid = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=TEAM))["id"]
            counted = reply(say(api, tid, "How many pages did you get?", [file]))
            check(
                "2 the agent is given both pages of the scanned attachment",
                str(counted.get("content", "")).startswith("2 pages"),
                {"reply": counted.get("content"), "attachments": counted.get("attachments")},
            )
            asked = reply(say(api, tid, "What does a replacement debit card cost?", [file]))
            cited = [(c.get("fileId"), c.get("page")) for c in asked.get("citations") or []]
            check(
                "3 the answer cites page 2 of the scan",
                (file["fileId"], 2) in cited,
                {"cited": cited, "reply": asked.get("content")},
            )
            with httpx.Client(base_url=k.documents_url, headers=TEAM, timeout=60) as documents:
                read = (
                    until(
                        lambda: (
                            (r := data(documents.get(f"/v1/documents/readings/{file['fileId']}")))
                            and r["status"] == "done"
                            and r
                        )
                    )
                    or {}
                )
            sources = [p.get("source") for p in read.get("pages") or []]
            check(
                "4 documents-service read the scan once, both pages by OCR",
                sources == ["ocr", "ocr"],
                {"status": read.get("status"), "sources": sources},
            )


main()
finish()
