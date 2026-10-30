"""tools-service's OpenAPI document is complete and committed; the gate itself is `ops_service_kit.openapi`.

uv run python scripts/check_openapi.py          # check
uv run python scripts/check_openapi.py --write  # regenerate openapi.json after a route change
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.activities.catalog import load_catalog
from ops_email import UnconfiguredSender
from ops_policy import AesGcmCipher
from ops_service_kit import openapi
from ops_service_kit.settings import Settings
from ops_tools.app import create_gateway_app
from ops_tools.auth import Tokens
from ops_tools.connections.routes import connections_router
from ops_tools.connections.service import ConnectionService
from ops_tools.egress_routes import egress_router
from ops_tools.expression_routes import expressions_router
from ops_tools.mailboxes import mailboxes_router
from ops_tools.mock_routes import mocks_router
from ops_tools.modules.directory import Directory
from ops_tools.modules.routes import executions_router, modules_router
from ops_tools.modules.service import ModuleService
from ops_tools.opa import OpaClient
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.plugins.templates import plugin_templates_router
from ops_tools.registry import ToolRegistry
from ops_tools.secrets.routes import secrets_router
from ops_tools.send_policy_routes import send_policy_router
from ops_tools.store import CallLog
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.egress import EgressStore
from ops_tools.store.mocks import MockStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore
from ops_tools.store.send_policies import SendPolicies
from ops_tools.systems import Systems, systems_router
from ops_tools.tools import LocalToolRunner

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "openapi.json"
ALLOWLIST = ROOT / "openapi-untyped.txt"
REPO_ALLOWLIST = "services/tools-service/openapi-untyped.txt"


def document() -> dict[str, Any]:
    """The app's document; building the app opens no connection, so nothing here needs a database or OPA."""
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    catalog = load_catalog(settings.seed_dir)
    directory = Directory.from_seed(json.loads(settings.tools_seed_file.read_text()), datetime.now(UTC))
    service = ModuleService(ModuleStore(engine), directory, CallLog(engine))
    connections = ConnectionStore(engine)
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    connection_service = ConnectionService(
        connections,
        SecretStore(engine),
        cipher,
        Tokens(connections, cipher, None, None),
        directory,
        egress=None,
        console_url=None,
    )
    app = create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(base_url=settings.opa_url)),
        registry=ToolRegistry(catalog),
        log=CallLog(engine),
        runner=LocalToolRunner(catalog, UnconfiguredSender()),
        review_key="openapi",
        routers=(
            modules_router(service, directory),
            executions_router(service, directory),
            mailboxes_router(settings, None, None),
            egress_router(EgressStore(engine)),
            expressions_router(),
            secrets_router(SecretStore(engine), cipher),
            send_policy_router(SendPolicies(engine), directory),
            mocks_router(MockStore(engine), ModuleStore(engine), directory, security_team="team_security"),
            connections_router(connection_service, directory),
            plugins_router(
                PluginHost(ModuleStore(engine), PluginBindings(engine), InstallSwitches(None)),
                connection_service,
                directory,
                PluginAppKeys(engine, cipher),
            ),
            plugin_templates_router(PluginHost(ModuleStore(engine), PluginBindings(engine), InstallSwitches(None))),
            systems_router(Systems(connection_service, ModuleStore(engine)), directory),
        ),
    )
    return app.openapi()


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
