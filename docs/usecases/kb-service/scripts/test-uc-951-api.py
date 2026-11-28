# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-951 open a deck or Word file as pages, api layer: docs/usecases/kb-service/open-a-deck-or-word-file-as-pages.md.
Own kb-service with its files-service and documents-service, platform-service for the team's pageImages policy, and
models-service with the fake OpenAI describing page pictures by services/kb-service/tests/fixtures/picture-reading-
fake-openai; no provider is called. The converter worker is the real one (`make converter-up`)."""

from __future__ import annotations

import base64
import io
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from docx import Document
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches
from usecase_harness import ROOT, bearer, check, data, fake_openai, finish, kb, models, platform, service_headers, signed_in

OWNER = "maya@harborpine.example"
RULES = ROOT / "services/kb-service/tests/fixtures/picture-reading-fake-openai"
MODELS_ADMIN = service_headers("models")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
WHOLE = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def converter_url() -> str:
    given = os.environ.get("OPS_DOCUMENTS_CONVERTER_URL")
    return given or f"http://127.0.0.1:{8780 + int(os.environ.get('OPS_PORT_OFFSET') or 0)}"


def diagram_png() -> io.BytesIO:
    """Three boxes joined by arrows, as pixels with no words a text layer could read."""
    img = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(img)
    for x in (60, 340, 620):
        draw.rectangle([x, 200, x + 200, 300], outline="black", width=3)
    draw.line([260, 250, 340, 250], fill="black", width=3)
    draw.line([540, 250, 620, 250], fill="black", width=3)
    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return out


def deck(*, closing: str | None = None) -> bytes:
    """A three-slide project update: a title slide, a slide that is only the architecture diagram, next steps; with
    `closing`, a fourth slide that holds only that title."""
    prs = Presentation()
    slides: list[tuple[str, str] | None] = [
        ("Claims intake: project update", "The event queue went live in three regions on 14 October."),
        None,
        ("Next steps", "Replay after an outage is tested every quarter."),
    ]
    for content in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1 if content else 6])
        if content:
            slide.shapes.title.text, slide.placeholders[1].text = content
        else:
            slide.shapes.add_picture(diagram_png(), Inches(1), Inches(1.5), width=Inches(8))
    if closing is not None:
        prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = closing
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def note() -> bytes:
    """A two-page decision note: the decision on page 1, the risks after a page break."""
    doc = Document()
    doc.add_paragraph("Decision: refunds move to the event queue in March, approved by Dana Whitfield.")
    doc.add_page_break()
    doc.add_paragraph("Open risks: the adjusters' tool lags a day behind the queue during the move.")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def push(k: Any, source: str, name: str, body: bytes, mime: str) -> dict[str, Any]:
    made = k.post(
        f"/v1/sources/{source}/items", json={"name": name, "content": base64.b64encode(body).decode(), "mime": mime}
    )
    if made.status_code not in (200, 201):
        raise SystemExit(f"FAIL {name} was not taken in: {made.status_code} {made.text[:300]}")
    return data(made)["item"]


def text_of(k: Any, item: str) -> dict[str, Any]:
    """The item's text once indexed, every page's sections joined (the service answers one page at a time)."""
    deadline = time.monotonic() + 240
    while data(k.get(f"/v1/items/{item}"))["status"] not in ("indexed", "failed") and time.monotonic() < deadline:
        time.sleep(1)
    first = data(k.get(f"/v1/items/{item}/text"))
    rest = [data(k.get(f"/v1/items/{item}/text", params={"page": n})) for n in range(2, len(first["pages"]) + 1)]
    return {**first, "sections": [s for t in (first, *rest) for s in t["sections"]]}


def blocks(text: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for s in text["sections"] for b in s["blocks"]]


def main() -> None:
    worker = converter_url()
    try:
        up = httpx.get(f"{worker}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        up = False
    if not up:
        raise SystemExit(f"FAIL the converter worker is not answering at {worker}: run make converter-up first")
    with (
        tempfile.TemporaryDirectory(prefix="uc-951-") as tmp,
        platform() as (people, _inner),
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(
            Path(tmp) / "files",
            models_url=models_url,
            platform_url=str(people.base_url).rstrip("/"),
            documents_env={"OPS_DOCUMENTS_CONVERTER_URL": worker},
        ) as k,
        httpx.Client(base_url=models_url, timeout=30) as model_admin,
        httpx.Client(base_url=k.documents_url, headers={"X-Team-Id": "team_ops"}, timeout=60) as reader,
    ):
        alias = {"name": "extract", "providerId": "openai-local", "modelId": "default", "images": True}
        model_admin.post("/v1/models/aliases", json={**alias, "clearedSensitivity": "confidential"}, headers=MODELS_ADMIN)
        session = signed_in(people, "w.kamau@harborpine.example")
        allowed = people.put("/v1/policies/pageImages", json={"value": True}, headers=bearer(session, "team_ops"))
        if allowed.status_code != 200:
            raise SystemExit(f"FAIL the team's pageImages policy was not turned on: {allowed.text[:300]}")
        base = data(k.post("/v1/knowledge-bases", json={"name": "Claims intake", "owner": OWNER}))
        src = data(k.post("/v1/sources", json={"type": "push", "name": "Project files", "kbIds": [base["id"]]}))

        update = push(k, src["id"], "project-update.pptx", deck(), PPTX)
        slides = text_of(k, update["id"])
        drawn = [b for b in blocks(slides) if b["readBy"] == "model"]
        asked = k.post(f"/v1/knowledge-bases/{base['id']}/query", json={"question": "What sends work to the Intake service?"})
        answer = data(asked) or {"error": asked.text[:300]}
        cited = [(c.get("page"), c.get("snippet", "")[:60]) for c in answer.get("citations", [])[:3]]
        check(
            "1 the deck's picture-only slide is described by a model, marked so, and a search cites slide 2",
            [p["readBy"] for p in slides["pages"]] == ["text", "model", "text"]
            and len(drawn) == 1
            and "Mobile app sends work" in drawn[0]["text"]
            and drawn[0]["page"] == 2
            and any(page == 2 for page, _ in cited),
            {"pages": slides["pages"], "drawn": drawn, "cited": cited},
        )
        check(
            "2 every block of the deck is boxed as its whole slide, and the text names the drawn PDF",
            all(b["boxes"] == [{"page": b["page"], **WHOLE}] for b in blocks(slides))
            and bool(slides["renditionId"])
            and slides["renditionId"] != update["fileId"],
            {"renditionId": slides["renditionId"], "boxes": [b["boxes"] for b in blocks(slides)]},
        )
        image = reader.get(f"/v1/documents/readings/{update['fileId']}/pages/2/image")
        check(
            "3 slide 2 is served as a picture drawn from the deck's PDF",
            image.status_code == 200 and image.headers.get("content-type") == "image/png" and len(image.content) > 2000,
            {"status": image.status_code, "type": image.headers.get("content-type"), "body": image.text[:200]},
        )

        decision = text_of(k, push(k, src["id"], "decision-note.docx", note(), DOCX)["id"])
        on = [(b["page"], b["text"].split(":")[0]) for b in blocks(decision)]
        check(
            "4 the Word note is two pages and each paragraph sits on the page it is drawn on",
            decision["paged"]
            and len(decision["pages"]) == 2
            and on == [(1, "Decision"), (2, "Open risks")]
            and all(b["boxes"] == [{"page": b["page"], **WHOLE}] for b in blocks(decision)),
            {"on": on, "pages": len(decision["pages"])},
        )
    finish()


if __name__ == "__main__":
    main()
