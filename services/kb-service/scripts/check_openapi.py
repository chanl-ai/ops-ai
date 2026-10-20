"""kb-service's OpenAPI document is complete and committed; the gate itself is `ops_service_kit.openapi`.

uv run python scripts/check_openapi.py          # check
uv run python scripts/check_openapi.py --write  # regenerate openapi.json after a route change
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine

from ops_kb.app import create_kb_app
from ops_service_kit import openapi
from ops_service_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "openapi.json"
ALLOWLIST = ROOT / "openapi-untyped.txt"
REPO_ALLOWLIST = "services/kb-service/openapi-untyped.txt"


def document() -> dict[str, Any]:
    """The app's document; building the app opens no connection, so nothing here needs a database."""
    return create_kb_app(create_async_engine(Settings().database_url)).openapi()


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
