# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-950 open a document beside the text read from it, api layer: docs/usecases/kb-service/open-a-document-beside-
the-text.md. Own kb-service with its files-service and documents-service, platform-service for the team's pageImages
policy, and models-service with the fake OpenAI describing page pictures by
services/kb-service/tests/fixtures/picture-reading-fake-openai; no provider is called."""

from __future__ import annotations

import base64
import io
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from docx import Document
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from usecase_harness import ROOT, bearer, check, data, fake_openai, finish, kb, models, platform, service_headers, signed_in

OWNER = "maya@harborpine.example"
RULES = ROOT / "services/kb-service/tests/fixtures/picture-reading-fake-openai"
MODELS_ADMIN = service_headers("models")
LIMIT = 20  # documents-service's PICTURE_PAGES_PER_FILE


def diagram() -> ImageReader:
    """Three boxes joined by arrows, as pixels with no words a text layer or OCR could read."""
    img = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(img)
    for x in (60, 340, 620):
        draw.rectangle([x, 200, x + 200, 300], outline="black", width=3)
    draw.line([260, 250, 340, 250], fill="black", width=3)
    draw.line([540, 250, 620, 250], fill="black", width=3)
    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return ImageReader(out)


def pdf(pages: list[str | None]) -> bytes:
    """A text page per string (one drawn line per sentence), a picture-only page per None."""
    out = io.BytesIO()
    c = Canvas(out, pagesize=LETTER)
    for page in pages:
        if page is None:
            c.drawImage(diagram(), 72, 300, width=450, height=250)  # pyright: ignore[reportUnknownMemberType]
        else:
            text = c.beginText(72, 700)
            for line in page.split(". "):
                text.textLine(line)
            c.drawText(text)
        c.showPage()
    c.save()
    return out.getvalue()


def note() -> bytes:
    """A decision note the way people write them: bold lines, no heading styles."""
    doc = Document()
    for head, body in [
        ("Decision", "We chose an event queue between intake and the adjusters."),
        ("What we did not choose", "We did not choose a nightly batch file."),
        ("Who does what", "Dana Whitfield leads the project. Omar Haddad builds the Intake service."),
        ("Open risks", "If the Intake service is down, the Mobile app keeps the work."),
    ]:
        doc.add_paragraph().add_run(head).bold = True
        doc.add_paragraph(body)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def push(k: Any, source: str, name: str, body: bytes, mime: str) -> str:
    made = k.post(
        f"/v1/sources/{source}/items", json={"name": name, "content": base64.b64encode(body).decode(), "mime": mime}
    )
    if made.status_code not in (200, 201):
        raise SystemExit(f"FAIL {name} was not taken in: {made.status_code} {made.text[:300]}")
    return str(data(made)["item"]["id"])


def text_of(k: Any, item: str) -> dict[str, Any]:
    """The item's text once it is indexed (a file with a picture page is read in the background, then indexed)."""
    deadline = time.monotonic() + 180
    while data(k.get(f"/v1/items/{item}"))["status"] not in ("indexed", "failed") and time.monotonic() < deadline:
        time.sleep(1)
    return data(k.get(f"/v1/items/{item}/text"))


def blocks(text: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for s in text["sections"] for b in s["blocks"]]


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc-950-") as tmp,
        platform() as (people, _inner),
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, platform_url=str(people.base_url).rstrip("/")) as k,
        httpx.Client(base_url=models_url, timeout=30) as model_admin,
    ):
        alias = {"name": "extract", "providerId": "openai-local", "modelId": "default", "images": True}
        model_admin.post("/v1/models/aliases", json={**alias, "clearedSensitivity": "confidential"}, headers=MODELS_ADMIN)
        session = signed_in(people, "w.kamau@harborpine.example")
        allowed = people.put("/v1/policies/pageImages", json={"value": True}, headers=bearer(session, "team_ops"))
        if allowed.status_code != 200:
            raise SystemExit(f"FAIL the team's pageImages policy was not turned on: {allowed.text[:300]}")
        base = data(k.post("/v1/knowledge-bases", json={"name": "Claims intake", "owner": OWNER}))
        src = data(k.post("/v1/sources", json={"type": "push", "name": "Project files", "kbIds": [base["id"]]}))

        review_text = "Reviewed on 14 October by Dana Whitfield. The diagram on the next page shows how the parts connect"
        review = text_of(k, push(k, src["id"], "architecture-review.pdf", pdf([review_text, None]), "application/pdf"))
        drawn = [b for b in blocks(review) if b["readBy"] == "model"]
        asked = k.post(f"/v1/knowledge-bases/{base['id']}/query", json={"question": "What sends work to the Intake service?"})
        answer = data(asked) or {"error": asked.text[:300]}
        cited = [(c.get("page"), c.get("snippet", "")[:60]) for c in answer.get("citations", [])[:3]]
        check(
            "1 the picture-only page is described by a model, marked so, and a search cites that page",
            [p["readBy"] for p in review["pages"]] == ["text", "model"]
            and len(drawn) == 1
            and "Mobile app sends work" in drawn[0]["text"]
            and drawn[0]["page"] == 2
            and drawn[0]["boxes"] == [{"page": 2, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}]
            and any(page == 2 for page, _ in cited),
            {"pages": review["pages"], "drawn": drawn, "cited": cited},
        )

        para = next((b for b in blocks(review) if b["readBy"] == "text"), {})
        check(
            "2 a PDF paragraph carries one box per line on its page, keyed by the paragraph",
            para.get("page") == 1
            and len(para.get("boxes", [])) >= 2
            and all(b["page"] == 1 and 0 <= b["y"] < 1 and b["w"] > 0 for b in para.get("boxes", [])),
            para,
        )

        word = text_of(k, push(k, src["id"], "decision-note.docx", note(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        heads = [s["headingPath"][-1] for s in word["sections"] if s["headingPath"]]
        check(
            "3 the Word note written with bold lines has four sections, none with a page box",
            heads == ["Decision", "What we did not choose", "Who does what", "Open risks"]
            and not word["paged"]
            and all(not b["boxes"] for b in blocks(word)),
            {"heads": heads, "paged": word["paged"]},
        )

        deck = text_of(k, push(k, src["id"], "storm-deck.pdf", pdf([None] * (LIMIT + 2)), "application/pdf"))
        read = [p["readBy"] for p in deck["pages"]]
        check(
            f"4 picture reading stops at its limit of {LIMIT} pages per file and says so in plain words",
            read == ["model"] * LIMIT + ["none", "none"]
            and deck["notes"] == [f"Pages {LIMIT + 1} to {LIMIT + 2} were not read. Not described: this file reached its limit of {LIMIT} pages read by a model."],
            {"read": read, "notes": deck["notes"]},
        )

        other = k.get("/v1/items/itm_missing/text")
        check("5 a document the team does not have has no text to show", other.status_code == 404, other.text[:300])
    finish()


if __name__ == "__main__":
    main()
