"""kb-service's three background processes, as its lifespan runs them: a pass that raises shows on
/health/background, so a hand-off, schedule or embedding loop that has stopped working never reads as running."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb import embedding, schedule
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_service_kit.settings import Settings
from ops_store import background
from ops_store.outbox import Relay
from ops_store.testing import loop_reports_failure

from .readings_fake import LocalReadings
from .vectors_fake import ConceptEmbedder


@asynccontextmanager
async def serving(
    engine: AsyncEngine, tenant: str, tmp_path: Path, key: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient]:
    """The kb app with its loops started by its lifespan, `key`'s every 50 ms so a failed pass shows within the wait,
    once its first heartbeat is on the report."""
    monkeypatch.setitem(background.BY_KEY, key, replace(background.BY_KEY[key], every_s=0.05))
    files = KnowledgeFiles(tmp_path)
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    app = create_kb_app(
        engine,
        auth=auth,
        files=files,
        agents=StaticAgents(),
        readings=LocalReadings(files),
        embedder=ConceptEmbedder(),
    )
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb")
    async with app.router.lifespan_context(app), http as client:
        for _ in range(100):
            listed = (await client.get("/health/background")).json()["processes"]
            if any(p["key"] == key and p["lastRunAt"] for p in listed):
                break
            await asyncio.sleep(0.05)
        yield client


async def broken(*_: Any, **__: Any) -> Any:
    raise ConnectionError("database connection refused")


async def test_a_hand_off_pass_that_raises_shows_on_health(
    engine: AsyncEngine, tenant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with serving(engine, tenant, tmp_path, "kb_relay", monkeypatch) as client:
        await loop_reports_failure(client, "kb_relay", lambda: monkeypatch.setattr(Relay, "once", broken))


async def test_a_schedule_pass_that_raises_shows_on_health(
    engine: AsyncEngine, tenant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with serving(engine, tenant, tmp_path, "knowledge_schedule", monkeypatch) as client:
        await loop_reports_failure(
            client, "knowledge_schedule", lambda: monkeypatch.setattr(schedule, "run_due", broken)
        )


async def test_an_embedding_pass_that_raises_shows_on_health(
    engine: AsyncEngine, tenant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with serving(engine, tenant, tmp_path, "kb_embed", monkeypatch) as client:
        await loop_reports_failure(client, "kb_embed", lambda: monkeypatch.setattr(embedding, "embed_all", broken))
