"""The console calls the public app from another origin: a listed origin gets the CORS headers, including on the
preflight for an authenticated call, and an unlisted one gets none. The internal app answers no browser."""

from __future__ import annotations

import httpx

from ops_platform.api.app import create_public_app

from .conftest import Platform

CONSOLE = "http://localhost:3018"


async def client(platform: Platform) -> httpx.AsyncClient:
    app = create_public_app(
        platform.store, platform.signer, demo_password=None, audiences=["platform"], cors_origins=[CONSOLE]
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://platform")


async def test_a_listed_origin_passes_the_preflight_with_authorization(platform: Platform) -> None:
    async with await client(platform) as c:
        r = await c.options(
            "/v1/auth/session",
            headers={
                "Origin": CONSOLE,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type,x-team-id",
            },
        )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == CONSOLE
    allowed = r.headers["access-control-allow-headers"].lower()
    assert all(h in allowed for h in ("authorization", "content-type", "x-team-id"))


async def test_an_unlisted_origin_gets_no_cors_headers(platform: Platform) -> None:
    async with await client(platform) as c:
        r = await c.get("/v1/health", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in r.headers


async def test_the_internal_app_answers_no_browser(platform: Platform) -> None:
    r = await platform.internal.options(
        "/v1/auth/introspect", headers={"Origin": CONSOLE, "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in r.headers
