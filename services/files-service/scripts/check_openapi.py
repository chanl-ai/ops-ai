"""files-service's OpenAPI document is complete and committed; the gate itself is `ops_service_kit.openapi`.

uv run python scripts/check_openapi.py          # check
uv run python scripts/check_openapi.py --write  # regenerate openapi.json after a route change
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ops_files.__main__ import build
from ops_files.app import create_files_app
from ops_service_kit import openapi
from ops_service_kit.settings import Settings, isolate_from_stack

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "openapi.json"
ALLOWLIST = ROOT / "openapi-untyped.txt"
REPO_ALLOWLIST = "services/files-service/openapi-untyped.txt"


# The app is built to read its routes: the fixed dev user, and none of a running stack's addresses.
isolate_from_stack()


def build_app() -> FastAPI:
    """The app; building it opens no connection, so nothing here needs a database."""
    files = build(Settings())
    return create_files_app(files, engine=files.engine, settings=files.settings)


def document() -> dict[str, Any]:
    """The app's document."""
    return build_app().openapi()


def main() -> int:
    code, lines = openapi.report(
        document(),
        allowlist_path=ALLOWLIST,
        document_path=DOCUMENT,
        committed=openapi.committed_count(REPO_ALLOWLIST, ROOT),
        write="--write" in sys.argv,
    )
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
