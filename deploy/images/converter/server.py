"""Converter worker: Word files and decks in, PDF out. Standard library only; LibreOffice does the drawing.

POST /convert?name=<original file name> with the raw bytes as the body. One conversion at a time: LibreOffice is heavy
and a second request waits for the lock. Each call gets a fresh temp folder and its own LibreOffice profile, so a
file that crashes soffice leaves nothing behind for the next one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = int(os.environ.get("OPS_CONVERTER_TIMEOUT_S", "90"))
SUFFIXES = (".docx", ".pptx")
# Hidden slides are exported too, so slide N of a deck is page N of the PDF (JSON filter options, LibreOffice 7.4+).
DECK_FILTER = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
WORD_FILTER = "pdf:writer_pdf_Export"

_lock = threading.Lock()


def convert(data: bytes, suffix: str) -> tuple[int, bytes | str]:
    """Return (200, pdf bytes), (504, message) on timeout or (422, message) when no PDF came out."""
    work = Path(tempfile.mkdtemp(prefix="convert-"))
    try:
        source = work / f"input{suffix}"
        source.write_bytes(data)
        out = work / "out"
        out.mkdir()
        cmd = [
            "soffice", "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nofirststartwizard",
            f"-env:UserInstallation=file://{work / 'profile'}",
            "--convert-to", DECK_FILTER if suffix == ".pptx" else WORD_FILTER,
            "--outdir", str(out), str(source),
        ]  # fmt: skip
        try:
            subprocess.run(cmd, cwd=work, capture_output=True, timeout=TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            return 504, "conversion timed out"
        pdf = out / "input.pdf"
        if not pdf.is_file() or pdf.stat().st_size == 0:
            return 422, "the file could not be converted"
        return 200, pdf.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "converter"

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code: int, message: str) -> None:
        self._send(code, json.dumps({"error": message}).encode(), "application/json")

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self._send(200, b'{"status":"ok"}', "application/json")
        else:
            self._text(404, "not found")

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path != "/convert":
            return self._text(404, "not found")
        name = (parse_qs(url.query).get("name") or [""])[0].lower()
        suffix = next((s for s in SUFFIXES if name.endswith(s)), None)
        if suffix is None:
            return self._text(415, "only .docx and .pptx files are converted")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            return self._text(411, "Content-Length is required")
        length = int(raw_length)
        if length > MAX_BYTES:
            return self._text(413, "the file is over 50 MB")
        data = self.rfile.read(length)
        if not data.startswith(b"PK\x03\x04"):  # both formats are zip files; anything else would be read as plain text
            return self._text(422, "the file could not be converted")
        with _lock:
            code, result = convert(data, suffix)
        if code == 200:
            assert isinstance(result, bytes)
            self._send(200, result, "application/pdf")
        else:
            self._text(code, str(result))

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} {format % args}", flush=True)


def main() -> None:
    host = os.environ.get("OPS_CONVERTER_HOST", "127.0.0.1")
    port = int(os.environ.get("OPS_CONVERTER_PORT", "8770"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
