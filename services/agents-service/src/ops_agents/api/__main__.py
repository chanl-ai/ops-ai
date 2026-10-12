"""`python -m ops_agents.api`: builds Settings once at boot (a bad value stops the process) and serves."""

from __future__ import annotations

import uvicorn

from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings

from .app import create_app


def main() -> None:
    configure_logging()
    settings = Settings()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
