"""A container's health check: `healthcheck.py <url>` exits 0 when the URL answers 2xx; `healthcheck.py db` exits 0
when the database in the service's settings answers a query (for the worker, which serves no port). Standard library
and the service's own settings only, so the images need no curl."""

from __future__ import annotations

import asyncio
import sys
import urllib.request


def url_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            return 200 <= r.status < 300
    except OSError:
        return False


async def db_ok() -> bool:
    from sqlalchemy import text  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    from ops_service_kit.settings import Settings  # noqa: PLC0415

    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
        return True
    except Exception:  # any failure is unhealthy
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(0 if (asyncio.run(db_ok()) if target == "db" else url_ok(target)) else 1)
