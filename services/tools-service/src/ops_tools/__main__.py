"""`uv run python -m ops_tools`: the tool gateway on settings.gateway_port (8720), deciding with OPA at opa_url, with
the tool-module registry at /v1/tool-modules. In dev the registry is seeded with the console's modules."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import uvicorn
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.activities.catalog import load_catalog
from ops_identity import Auth, mint_service_token, service_signer
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings

from .app import create_gateway_app
from .egress import EgressPolicy, OverrideResolver, egress_client
from .egress_routes import egress_router
from .modules.directory import Directory
from .modules.routes import executions_router, modules_router
from .modules.seed import load
from .modules.service import ModuleService
from .modules.workflows import AgentsWorkflows
from .opa import OpaClient
from .registry import ToolRegistry
from .secrets import SecretResolver
from .secrets.cipher import AesGcmCipher
from .secrets.routes import secrets_router
from .store import CallLog
from .store.egress import EgressStore
from .store.modules import ModuleStore
from .store.secrets import SecretStore
from .tools import LocalToolRunner

# One tenant until tools-service resolves tenants through ops_identity (c-006); the checkpointer uses the same id.
TENANT = "local"
log = get_logger("ops_tools")


async def _seed(settings: Settings, seed: dict[str, Any], catalog: list[dict[str, Any]]) -> None:
    engine = create_async_engine(settings.database_url)
    added = await load(ModuleStore(engine), seed, tenant_id=TENANT, now=datetime.now(UTC), catalog=catalog)
    await engine.dispose()
    log.info("tool_modules_seeded", added=added)


def main() -> None:
    settings = Settings()
    configure_logging()
    catalog = load_catalog(settings.seed_dir)
    seed = json.loads(settings.tools_seed_file.read_text())
    dev = settings.environment == "dev"
    if dev:
        asyncio.run(_seed(settings, seed, json.loads((settings.seed_dir / "tools.json").read_text())))
    engine = create_async_engine(settings.database_url)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    store, calls = ModuleStore(engine), CallLog(engine)
    policy = EgressPolicy(EgressStore(engine), OverrideResolver(settings.egress_resolve))
    ca = str(settings.egress_ca_file) if settings.egress_ca_file else None
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    secrets = SecretResolver(SecretStore(engine), cipher)
    signer = service_signer(settings)
    modules = ModuleService(
        store,
        directory,
        calls,
        egress=policy,
        http=egress_client(policy, ca_file=ca),
        secrets=secrets,
        security_team=settings.security_team_id,
        workflows=AgentsWorkflows(
            httpx.AsyncClient(base_url=settings.agents_url or f"http://127.0.0.1:{settings.port}", timeout=5),
            lambda tenant: mint_service_token(signer, service="tools", audience="agents", tenant_id=tenant),
        ),
    )
    app = create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(base_url=settings.opa_url, timeout=5)),
        registry=ToolRegistry(catalog, store, tenant_id=TENANT),
        log=calls,
        runner=LocalToolRunner(catalog),
        review_key=settings.review_key.get_secret_value(),
        auth=Auth.from_settings(settings, audience="tools"),
        egress=policy,
        http_client=egress_client(policy, ca_file=ca),
        cors_origins=tuple(settings.cors_origins),
        secret_resolver=secrets,
        routers=(
            modules_router(modules, directory),
            executions_router(modules, directory),
            egress_router(EgressStore(engine)),
            secrets_router(SecretStore(engine), cipher),
        ),
    )
    uvicorn.run(app, host="127.0.0.1", port=settings.gateway_port, log_level="info")


if __name__ == "__main__":
    main()
