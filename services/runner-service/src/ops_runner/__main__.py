"""`uv run python -m ops_runner`: runner-service on settings.runner_port (8770)."""

from __future__ import annotations

import httpx
import uvicorn

from ops_identity import ServiceClient
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings

from .app import create_runner_app
from .fetch import wasm_path
from .wasm import WasmPython


def main() -> None:
    settings = Settings()
    configure_logging()
    runtime = WasmPython(wasm_path(settings), sha256=settings.runner_wasm_sha256, cache_dir=settings.runner_cache_dir)
    url = settings.tools_url or settings.gateway_url
    # Each call names the run's tenant and team itself; tools-service decides it as the caller its call token names.
    tools = (
        ServiceClient.for_settings(
            settings, httpx.AsyncClient(base_url=url), service="runner", audience="tools", scopes=["tools:run"]
        )
        if url
        else None
    )
    app = create_runner_app(runtime, settings=settings, tools=tools)
    uvicorn.run(app, host=settings.bind_host, port=settings.runner_port, log_level="info")


if __name__ == "__main__":
    main()
