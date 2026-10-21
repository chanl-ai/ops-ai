"""A seeded workflow definition that changes in the seed file (c-057 live walk), by failure mode: a running stack
keeps starting new threads on the old version after a restart, a thread already under way is moved onto the new one,
and a version a person published is replaced by the seed."""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_agents.store.workflow_registry import registry_workflow_versions, registry_workflows
from ops_identity import Auth
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model


def seed_copy(tmp: Path) -> Path:
    seed = tmp / "seed"
    shutil.copytree(SEED, seed)
    return seed


def change_levy_case(seed: Path, status: str) -> None:
    """A real edit to the seeded definition: what the `held` end reports."""
    path = seed / "workflows.json"
    flows: list[dict[str, Any]] = json.loads(path.read_text())
    levy = next(f for f in flows if f["name"] == "levy-case")
    next(n for n in levy["nodes"] if n["id"] == "held")["config"]["status"] = status
    path.write_text(json.dumps(flows))


@asynccontextmanager
async def stack(db: str, seed: Path, *, environment: str = "dev") -> AsyncGenerator[AsyncClient]:
    """One start of agents-service on a database that outlives it, as a restart of the shared stack does.
    `environment` other than dev runs the seeding rules as production does; the routes keep dev auth so a test can
    name who decides."""
    engine = create_async_engine(db)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    dev = Settings(database_url=db, seed_dir=seed)
    settings = dev if environment == "dev" else dev.model_copy(update={"environment": environment})
    app = create_app(
        settings,
        auth=Auth.from_settings(dev, audience="agents"),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client
    await engine.dispose()


async def live_version(client: AsyncClient) -> int:
    r = await client.get("/v1/workflows/levy-case")
    assert r.status_code == 200, r.text
    return int(r.json()["data"]["version"])


async def test_a_changed_seed_definition_reaches_new_threads_on_restart(tmp_path: Path) -> None:
    db, seed = f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", seed_copy(tmp_path)
    async with stack(db, seed) as client:
        first = await live_version(client)
    change_levy_case(seed, "held_v2")
    async with stack(db, seed) as client:
        assert await live_version(client) == first + 1, "new threads still start on the old version"
    async with stack(db, seed) as client:
        assert await live_version(client) == first + 1, "an unchanged seed publishes nothing new"


async def test_a_version_a_person_published_is_not_replaced(tmp_path: Path) -> None:
    db, seed = f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", seed_copy(tmp_path)
    async with stack(db, seed) as client:
        first = await live_version(client)
    engine = create_async_engine(db)
    async with engine.begin() as c:
        mark = sa.update(registry_workflow_versions).where(registry_workflow_versions.c.workflow_id == "levy-case")
        await c.execute(mark.values(published_by="maya@harborpine.example"))
        await c.execute(
            sa.update(registry_workflows).where(registry_workflows.c.id == "levy-case").values(status="live")
        )
    await engine.dispose()
    change_levy_case(seed, "held_v2")
    async with stack(db, seed) as client:
        assert await live_version(client) == first, "the seed replaced a version a person published"


async def pending_seed_requests(client: AsyncClient) -> list[dict[str, Any]]:
    r = await client.get("/reviews", params={"view": "open", "pageSize": 100})
    assert r.status_code == 200, r.text
    return [x for x in r.json()["data"]["data"] if x.get("workflowId") == "levy-case" and x["id"].startswith("WFP")]


async def test_outside_dev_a_changed_seed_waits_for_review_and_the_pointer_stays(tmp_path: Path) -> None:
    """A shipped seed change outside dev is not published by the seed: it is the draft and one publish request, and
    new threads keep starting on the version a review approved. Restarting does not open a second request."""
    db, seed = f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", seed_copy(tmp_path)
    async with stack(db, seed) as client:
        first = await live_version(client)
    change_levy_case(seed, "held_v2")
    async with stack(db, seed, environment="production") as client:
        assert await live_version(client) == first, "the seed published itself outside dev"
        waiting = await pending_seed_requests(client)
        assert len(waiting) == 1, waiting
        draft = (await client.get("/v1/workflows/levy-case")).json()["data"]["draft"]
        assert draft is not None and draft["savedBy"] == "seed", draft
    async with stack(db, seed, environment="production") as client:
        assert len(await pending_seed_requests(client)) == 1, "a restart opened a second request"
        assert await live_version(client) == first


async def test_outside_dev_approving_the_seed_request_moves_the_pointer_to_the_seed_version(tmp_path: Path) -> None:
    db, seed = f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", seed_copy(tmp_path)
    async with stack(db, seed) as client:
        first = await live_version(client)
    change_levy_case(seed, "held_v2")
    async with stack(db, seed, environment="production") as client:
        (request,) = await pending_seed_requests(client)
        r = await client.post(
            f"/reviews/{request['id']}/decision",
            json={"decision": "approved"},
            headers={"X-Dev-User": "m.okafor@harborpine.example"},
        )
        assert r.status_code == 200, r.text
        assert await live_version(client) == first + 1
        t = await client.post("/v1/threads", json={"graph": "levy-case", "metadata": {}})
        assert t.status_code == 201, t.text
        versions = (await client.get("/v1/graphs/levy-case/versions")).json()["data"]
        seed_digest = next(v["digest"] for v in versions if v["version"] == first + 1)
        threads = (await client.get("/v1/threads", params={"graph": "levy-case"})).json()["data"]
        mine = next(x for x in threads if x["threadId"] == t.json()["data"]["threadId"])
        assert mine["version"] == first + 1 and seed_digest


async def test_outside_dev_a_persons_draft_is_kept_when_the_seed_asks_for_review(tmp_path: Path) -> None:
    """The seed's request carries its own definition; a draft a person saved is not overwritten by it."""
    db, seed = f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", seed_copy(tmp_path)
    async with stack(db, seed) as client:
        first = await live_version(client)
        mine = (await client.get("/v1/workflows/levy-case")).json()["data"]
    engine = create_async_engine(db)
    async with engine.begin() as c:
        await c.execute(
            sa.update(registry_workflows)
            .where(registry_workflows.c.id == "levy-case")
            .values(
                draft=mine.get("graph") or {"nodes": [], "edges": []},
                draft_saved_at="2026-10-15T20:00:00.000Z",
                draft_saved_by="maya@harborpine.example",
            )
        )
    await engine.dispose()
    change_levy_case(seed, "held_v2")
    async with stack(db, seed, environment="production") as client:
        assert len(await pending_seed_requests(client)) == 1, "the seed's change still waits for review"
        draft = (await client.get("/v1/workflows/levy-case")).json()["data"]["draft"]
        assert draft is not None and draft["savedBy"] == "maya@harborpine.example", draft
        assert await live_version(client) == first
