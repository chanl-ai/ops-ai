# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-949 open a document beside the text read from it, cli layer: docs/usecases/kb-service/open-a-document-beside-
the-text.md, story S5 (step 6). A developer reads a pushed PDF's text with `opsai kb text`, reading the address from a
saved profile. Own kb-service with its files-service and documents-service; no model is called."""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from usecase_harness import ROOT, check, data, finish, kb


def review() -> bytes:
    out = io.BytesIO()
    c = Canvas(out, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 720, "Claims intake review")
    c.setFont("Helvetica", 11)
    c.drawString(72, 690, "The event queue went live in three regions on 14 October.")
    c.save()
    return out.getvalue()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uc-949-cli-") as tmp, kb(Path(tmp) / "files") as k:
        base = data(k.post("/v1/knowledge-bases", json={"name": "Claims intake", "owner": "maya@harborpine.example"}))
        src = data(k.post("/v1/sources", json={"type": "push", "name": "Project files", "kbIds": [base["id"]]}))
        body = {"name": "review.pdf", "content": base64.b64encode(review()).decode(), "mime": "application/pdf"}
        item = data(k.post(f"/v1/sources/{src['id']}/items", json=body))["item"]
        config = Path(tmp) / "ops-config.json"
        profile = {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": {"kb": str(k.base_url).rstrip("/")}}
        config.write_text(json.dumps({"profiles": {"local": profile}, "current": "local"}))
        env = {**os.environ, "OPS_CONFIG": str(config)}
        env.pop("VIRTUAL_ENV", None)
        argv = ["uv", "run", "--quiet", "--project", str(ROOT / "sdk" / "python"), "opsai", "kb", "text", item["id"]]
        ran = subprocess.run(argv, env=env, capture_output=True, text=True, check=False, timeout=300)
        check(
            "6 opsai kb text prints the heading, then the paragraph with its page and who read it",
            ran.returncode == 0
            and "# Claims intake review" in ran.stdout
            and "[p1 text] The event queue went live in three regions" in ran.stdout,
            {"out": ran.stdout[-600:], "err": ran.stderr[-400:]},
        )
    finish()


main()
