"""Fails unless OCR works on this machine: Tesseract reads English, and documents-service's /health does not report
OCR missing. stg-deploy runs it on the staging machine after every process is up, so a deploy whose image lost
Tesseract stops there instead of every scanned page failing quietly afterwards.

    python3 deploy/fly/check_ocr.py [documents-service base URL, default http://127.0.0.1:8760]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8760"
    tesseract = shutil.which("tesseract")
    if tesseract is None:
        print("FAIL ocr: no tesseract binary on PATH")
        return 1
    langs = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True, check=False).stdout.split()
    if "eng" not in langs:
        print(f"FAIL ocr: tesseract has no English language data ({' '.join(langs[-5:])})")
        return 1
    with urllib.request.urlopen(f"{base}/health", timeout=10) as r:
        health = json.load(r)
    if health.get("reason") == "ocr" or health.get("status") != "ok":
        print(f"FAIL ocr: documents-service /health says {health}")
        return 1
    print("ok ocr: tesseract with eng, documents-service reports OCR available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
