"""The console calls tools-service from the browser, so a preflight from its origin must be answered."""

from __future__ import annotations

import httpx

from ops_agents.activities.catalog import load_catalog
from ops_service_kit.settings import Settings
from ops_tools.app import create_gateway_app
from ops_tools.opa import OpaClient
from ops_tools.registry import ToolRegistry
from ops_tools.store import CallLog
from ops_tools.tools import LocalToolRunner

CONSOLE = "http://localhost:3016"


async def test_a_preflight_from_the_console_origin_is_answered() -> None:
    settings = Settings()
    catalog = load_catalog(settings.seed_dir)
    app = create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(base_url="http://opa.invalid")),
        registry=ToolRegistry(catalog),
        log=CallLog(None),  # pyright: ignore[reportArgumentType]  # a preflight never reaches the call log
        runner=LocalToolRunner(catalog),
        review_key="test",
        cors_origins=(CONSOLE,),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        headers = {
            "Origin": CONSOLE,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type, x-team-id",
        }
        allowed = await c.options("/v1/tool-modules/mod_core_banking", headers=headers)
        other = await c.options("/v1/tool-modules", headers={**headers, "Origin": "https://evil.example.com"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == CONSOLE
    assert "x-team-id" in allowed.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in other.headers
