"""Started with no model key, every read answers from the database: a GET never answers 503 model_unavailable. Only
a route that calls a model may refuse for want of one, so the review queue, the bell's count and every other list
still load. One test per route, over every GET route without a path parameter, so a new read is covered when it is
added."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.graphs import GraphStore, metadata
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.ids import now_iso
from ops_service_kit.settings import Settings

from ..conftest import SEED, fixture_knowledge
from .test_no_model import keyless  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

# Not reads of stored state: health reports the missing model on purpose (test_no_model). Live event streams are left
# out by their response type (`_streams`).
NOT_READS = {"/health"}


def _streams(route: APIRoute) -> bool:
    """A live event stream: the in-process client waits for a body that never ends, so it is not swept here."""
    return any("text/event-stream" in (r.get("content") or {}) for r in route.responses.values())


def _reads() -> list[str]:
    app = create_app(Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, openai_api_key=None))
    # Included routers are nested in FastAPI 0.143; iter_route_contexts flattens them with their effective paths.
    paths = {
        ctx.path or ctx.original_route.path
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute)
        and "GET" in (ctx.original_route.methods or set())
        and not _streams(ctx.original_route)
    }
    reads = sorted(p for p in paths if "{" not in p and p not in NOT_READS)
    assert reads, "no GET routes were found to check"
    return reads


@pytest.mark.parametrize("path", _reads())
async def test_a_read_needs_no_model(keyless: AsyncClient, path: str) -> None:  # noqa: F811
    async def status() -> tuple[int, str]:
        # Streamed, so a live event stream answers with its status line instead of holding the test open.
        async with keyless.stream("GET", path) as r:
            return r.status_code, "" if r.status_code != 503 else (await r.aread()).decode()[:300]

    # A read that never answers is as broken as one that refuses.
    code, body = await asyncio.wait_for(status(), timeout=10)
    assert code != 503, f"{path}: {body}"


async def test_the_review_queue_lists_with_a_stored_thread_and_no_model() -> None:
    """A paused workflow thread is stored, but no model is configured to resolve its graph: the queue still answers,
    with the reviews it can read, instead of refusing them all."""
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, openai_api_key=None, anthropic_api_key=None)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    with tenant_scope(LOCAL_TENANT):
        await GraphStore(engine).create_thread("th_paused", "dispute_email", {}, "team_ops", now_iso(), version=1)
    app = create_app(settings, engine=engine, knowledge=fixture_knowledge())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        r = await c.get("/reviews", params={"view": "open"})
    assert r.status_code == 200, r.text
