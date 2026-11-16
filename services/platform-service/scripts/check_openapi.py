"""platform-service's OpenAPI document is complete and committed; the gate itself is `ops_service_kit.openapi`.
The public and internal apps are one document, so a route moving between them shows in the diff.

uv run python scripts/check_openapi.py          # check
uv run python scripts/check_openapi.py --write  # regenerate openapi.json after a route change
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from ops_identity import ServiceAuth
from ops_platform.api.app import create_internal_app, create_public_app
from ops_platform.keys import dev_signer
from ops_platform.store.identity import IdentityStore
from ops_service_kit import openapi
from ops_service_kit.settings import Settings, isolate_from_stack, unanswered_endpoints

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "openapi.json"
ALLOWLIST = ROOT / "openapi-untyped.txt"
REPO_ALLOWLIST = "services/platform-service/openapi-untyped.txt"


# The app is built to read its routes: the fixed dev user, and none of a running stack's addresses.
isolate_from_stack()


def build_apps() -> list[FastAPI]:
    """The public and the internal app; building them opens no connection, so nothing here needs a database."""
    unanswered_endpoints("agents")
    store = IdentityStore.open(Settings().database_url)
    public = create_public_app(store, dev_signer(), demo_password=None, audiences=["platform"])
    services = ServiceAuth(audience="platform", verifiers={}, tenant_scoped=False)
    return [public, create_internal_app(store, services=services)]


def document() -> dict[str, Any]:
    """Both apps' documents in one."""
    public, internal = (app.openapi() for app in build_apps())
    public["paths"].update(internal["paths"])
    public.setdefault("components", {}).setdefault("schemas", {}).update(
        internal.get("components", {}).get("schemas", {})
    )
    return public


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
