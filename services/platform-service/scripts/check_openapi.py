"""platform-service's OpenAPI document is complete and committed; the gate itself is `ops_service_kit.openapi`.
The public and internal apps are one document, so a route moving between them shows in the diff.

uv run python scripts/check_openapi.py          # check
uv run python scripts/check_openapi.py --write  # regenerate openapi.json after a route change
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ops_identity import ServiceAuth
from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.keys import dev_signer
from ops_platform.store.identity import IdentityStore
from ops_service_kit import openapi
from ops_service_kit.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "openapi.json"
ALLOWLIST = ROOT / "openapi-untyped.txt"
REPO_ALLOWLIST = "services/platform-service/openapi-untyped.txt"


def document() -> dict[str, Any]:
    """Both apps' documents in one; building the apps opens no connection, so nothing here needs a database."""
    store = IdentityStore.open(Settings().database_url)
    doc = create_public_app(store, dev_signer(), demo_password=None, audiences=["platform"]).openapi()
    services = ServiceAuth(audience="platform", verifiers={}, tenant_scoped=False)
    internal = create_internal_app(store, services=services).openapi()
    doc["paths"].update(internal["paths"])
    doc.setdefault("components", {}).setdefault("schemas", {}).update(internal.get("components", {}).get("schemas", {}))
    return doc


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
