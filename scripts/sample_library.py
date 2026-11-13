"""Installs the demo policy library through the public HTTP API: one knowledge base, one pushed source per collection,
and each document written in its format (PDF, Word, web page or text), its second version after its first.

    make sample-library                       the local stack, as the platform dev role in team Platform
    uv run python scripts/sample_library.py [--origin URL] [--expect-found]

The manifest is scripts/sample-team/library/library.json; each version's text is a markdown file beside it. The base
is made in the manifest's team as the dev role it names (services/platform-service/seed/dev-roles.json), so the person
signed in on a fresh `make up` sees it. A PDF is drawn by reportlab and a Word file by python-docx from the markdown; a
web page is pushed as text/html with its address (offline, no website plugin). Each record is looked up by name before
it is made, so a second run finds everything and makes nothing; a document holding fewer versions than the manifest
gets the rest. Every line says MADE, FOUND or FAIL, and the exit status is the number of FAIL lines.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
from sample_team import EXPECT_FOUND, FAILED, Refused, data, items, say, service_urls, settled, sign_in

from ops_service_kit.settings import Settings

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "sample-team" / "library"
ROLES = HERE.parent / "services" / "platform-service" / "seed" / "dev-roles.json"
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "text": "text/markdown",
}
EXTENSION = {"pdf": ".pdf", "docx": ".docx", "html": ".html", "text": ".md"}


# ── Rendering one version's markdown in its format ───────────────────────────────────────────────────────────────


def blocks(text: str) -> list[tuple[str, Any]]:
    """The markdown the library uses, as (kind, value): heading (level, text), bullet, number, table (rows), para."""
    out: list[tuple[str, Any]] = []
    table: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r"-+", c) for c in cells):
                table.append(cells)
            continue
        if table:
            out.append(("table", table))
            table = []
        if not line:
            continue
        if m := re.match(r"^(#+)\s+(.*)", line):
            out.append(("heading", (len(m.group(1)), m.group(2))))
        elif line.startswith("- "):
            out.append(("bullet", line[2:]))
        elif m := re.match(r"^\d+\.\s+(.*)", line):
            out.append(("number", m.group(1)))
        else:
            out.append(("para", line))
    if table:
        out.append(("table", table))
    return out


def as_pdf(title: str, text: str) -> bytes:
    styles = getSampleStyleSheet()
    flow: list[Any] = []
    for kind, value in blocks(text):
        if kind == "heading":
            flow.append(Paragraph(html.escape(value[1]), styles["Title" if value[0] == 1 else "Heading2"]))
        elif kind in {"bullet", "number"}:
            flow.append(Paragraph(f"&bull; {html.escape(value)}", styles["BodyText"]))
        elif kind == "table":
            flow.append(Table(value))
            flow.append(Spacer(1, 8))
        else:
            flow.append(Paragraph(html.escape(value), styles["BodyText"]))
    buf = io.BytesIO()
    # Fixed metadata, so the same text draws the same bytes and a second run's version is unchanged.
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title, author="Policy library", invariant=1)
    doc.build(flow)
    return buf.getvalue()


def as_docx(text: str) -> bytes:
    doc = Document()
    for kind, value in blocks(text):
        if kind == "heading":
            doc.add_heading(value[1], level=0 if value[0] == 1 else 1)
        elif kind == "bullet":
            doc.add_paragraph(value, style="List Bullet")
        elif kind == "number":
            doc.add_paragraph(value, style="List Number")
        elif kind == "table":
            grid = doc.add_table(rows=len(value), cols=len(value[0]))
            for r, row in enumerate(value):
                for c, cell in enumerate(row):
                    grid.cell(r, c).text = cell
        else:
            doc.add_paragraph(value)
    doc.core_properties.author = "Policy library"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def as_html(title: str, text: str) -> str:
    parts: list[str] = []
    for kind, value in blocks(text):
        if kind == "heading":
            level = 1 if value[0] == 1 else 2
            parts.append(f"<h{level}>{html.escape(value[1])}</h{level}>")
        elif kind in {"bullet", "number"}:
            parts.append(f"<ul><li>{html.escape(value)}</li></ul>")
        elif kind == "table":
            rows = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in value)
            parts.append(f"<table>{rows}</table>")
        else:
            parts.append(f"<p>{html.escape(value)}</p>")
    body = "\n".join(parts)
    head = f"<head><title>{html.escape(title)}</title></head>"
    return f"<!doctype html><html>{head}<body><main>{body}</main></body></html>"


def item_body(doc: dict[str, Any], version: str) -> dict[str, Any]:
    text = (LIBRARY / f"{version}.md").read_text()
    fmt = doc["format"]
    body: dict[str, Any] = {"name": slug(doc["title"]) + EXTENSION[fmt], "title": doc["title"], "mime": MIME[fmt]}
    if fmt == "pdf":
        body["content"] = base64.b64encode(as_pdf(doc["title"], text)).decode()
    elif fmt == "docx":
        body["content"] = base64.b64encode(as_docx(text)).decode()
    elif fmt == "html":
        body["text"] = as_html(doc["title"], text)
    else:
        body["text"] = text
    if doc.get("url"):
        body["url"] = doc["url"]
    return body


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ── Install ──────────────────────────────────────────────────────────────────────────────────────────────────────


def ensure_base(kb: Any, spec: dict[str, Any], owner: str, collections: list[str]) -> str:
    listed = items(data(kb.get("/v1/knowledge-bases", params={"search": spec["name"], "pageSize": 100})))
    # The list is the signed-in team's, so a base of the same name there is this one.
    found = next((b for b in listed if b["name"].lower() == spec["name"].lower()), None)
    if found:
        say("FOUND", f"knowledge base {spec['name']}", found["id"])
        return str(found["id"])
    body = {**spec, "owner": owner, "collections": collections}
    made = data(kb.post("/v1/knowledge-bases", json=body))
    say("MADE", f"knowledge base {spec['name']}", made["id"])
    return str(made["id"])


def ensure_source(kb: Any, kb_id: str, collection: dict[str, Any], owner: str) -> str:
    listed = items(data(kb.get("/v1/sources", params={"search": collection["source"], "pageSize": 100})))
    found = next((s for s in listed if s["name"] == collection["source"] and s["type"] == "push"), None)
    if found:
        say("FOUND", f"source {collection['source']}", found["id"])
        return str(found["id"])
    body = {
        "type": "push",
        "name": collection["source"],
        "collection": collection["name"],
        "tags": collection["tags"],
        "owner": owner,
        "kbIds": [kb_id],
    }
    made = data(kb.post("/v1/sources", json=body))
    say("MADE", f"source {collection['source']}", made["id"])
    return str(made["id"])


def ensure_document(kb: Any, source_id: str, doc: dict[str, Any]) -> None:
    """Each version the manifest lists, oldest first, past the versions the source already holds."""
    listed = items(data(kb.get(f"/v1/sources/{source_id}/items", params={"search": doc["title"], "pageSize": 100})))
    held = next((i for i in listed if i["title"] == doc["title"]), None)
    have = int(str(held["version"]).lstrip("v")) if held else 0
    wanted = doc["versions"]
    if have >= len(wanted):
        say("FOUND", f"document {doc['title']}", f"version {have}")
        return
    for n, version in enumerate(wanted[have:], start=have + 1):
        put = data(kb.post(f"/v1/sources/{source_id}/items", json=item_body(doc, version)))
        say("MADE", f"document {doc['title']}", f"version {n}, {put['outcome']}, {put['item']['status']}")


def check(spec: dict[str, Any]) -> None:
    names = {c["name"] for c in spec["collections"]}
    for doc in spec["documents"]:
        if doc["collection"] not in names or doc["format"] not in MIME:
            raise SystemExit(f"library.json: {doc['title']} names an unknown collection or format")
        for version in doc["versions"]:
            if not (LIBRARY / f"{version}.md").is_file():
                raise SystemExit(f"library.json: {doc['title']} names {version}.md, which is not in {LIBRARY}")


def install(args: argparse.Namespace) -> int:
    if args.expect_found:
        EXPECT_FOUND.append(True)
    spec = json.loads((LIBRARY / "library.json").read_text())
    check(spec)
    email = json.loads(ROLES.read_text())[spec["person"]]
    password = Settings().platform_demo_password.get_secret_value()
    urls = service_urls(args.origin)
    who = settled(sign_in(urls, email, password, spec["team"]))
    kb = who("kb")
    kb_id = ensure_base(kb, spec["base"], email, [c["name"] for c in spec["collections"]])
    sources = {c["name"]: ensure_source(kb, kb_id, c, email) for c in spec["collections"]}
    for doc in spec["documents"]:
        try:
            ensure_document(kb, sources[doc["collection"]], doc)
        except Refused as e:
            say("FAIL", f"document {doc['title']}", str(e))
    print(f"\n{len(FAILED)} failed", flush=True)
    return len(FAILED)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origin", default="http://localhost:3016", help="the install's console or public address")
    parser.add_argument("--expect-found", action="store_true", help="fail on anything made (a second run)")
    return install(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
