"""Cases runs and Reviews on the console's routes, by failure mode: a paused run missing from "needs a person", a
decision sending twice when repeated, a decision lost when its resume fails, and a money approval without step-up."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api import hitl_facade
from ops_agents.api.app import create_app
from ops_agents.api.auth import step_up_signer
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import metadata
from ops_policy import HmacSigner, mint_step_up
from ops_service_kit.settings import Settings
from tests.api.test_graphs import EMAILS, run, thread
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, step_up


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
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
        yield client, app.state.runtime


async def paused_dispute(client: AsyncClient) -> str:
    tid = await thread(client, "complex_workflow")
    events = await run(client, tid, {"input": {"email": EMAILS[0]}})
    assert events[-1]["data"]["status"] == "interrupted"
    return tid


async def data(client: AsyncClient, path: str) -> Any:
    res = await client.get(path)
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def test_paused_run_is_a_waiting_row_with_its_review_step(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    tid = await paused_dispute(client)
    page = await data(client, "/runs?view=needs_person&page=1&pageSize=25")
    assert [r["id"] for r in page["data"]] == [tid]
    assert page["viewCounts"] == {"needs_person": 1, "open": 1, "past_sla": 0, "done_today": 0}
    row = page["data"][0]
    assert (row["state"], row["status"], row["reviewId"]) == ("waiting", "waiting_review", tid)
    assert row["subject"] == EMAILS[0]["subject"]
    steps = (await data(client, f"/runs/{tid}"))["steps"]
    assert [s["nodeId"] for s in steps].count("extract") == 3
    assert [(s["nodeId"], s["status"]) for s in steps if s["status"] == "waiting"] == [("human", "waiting")]
    # Filters narrow the rows, not the view counts.
    assert (await data(client, "/runs?view=needs_person&page=1&pageSize=25&state=done"))["data"] == []


async def test_decision_resumes_once_and_a_repeat_sends_nothing(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    tid = await paused_dispute(client)
    review = await data(client, f"/reviews/{tid}")
    assert (review["status"], review["actionTool"], review["stepUp"]) == ("pending", "send_reply", False)

    # The body the console's Reviews page sends, including fields only other review kinds use.
    console_body = {"decision": "approved", "reason": "", "addTestCase": False, "conditions": None}
    res = await client.post(f"/reviews/{tid}/decision", json=console_body)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "approved"
    again = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    assert again.status_code == 200, again.text
    flipped = await client.post(f"/reviews/{tid}/decision", json={"decision": "rejected"})
    assert flipped.status_code == 409

    runs = (await client.get(f"/v1/threads/{tid}/runs")).json()["data"]
    assert sum(r["nodes"].count("send_reply") for r in runs) == 1
    row = await data(client, f"/runs/{tid}")
    assert (row["state"], row["actionsApproved"]) == ("done", 1)
    assert (await data(client, "/reviews?view=resolved&page=1&pageSize=25"))["viewCounts"]["resolved"] == 1


async def test_decision_stands_when_its_resume_fails_and_a_retry_resumes(stack: tuple[AsyncClient, Runtime]) -> None:
    client, rt = stack
    tid = await paused_dispute(client)
    assert rt.leases is not None
    await rt.leases.acquire(tid, "run_other")
    res = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved", "reason": "Evidence holds."})
    assert res.status_code == 409 and res.json()["error"]["code"] == "run_active"
    # Recorded before the resume: the review is decided, and the run still waits.
    decided = await data(client, f"/reviews/{tid}")
    assert (decided["status"], decided["decisionReason"]) == ("approved", "Evidence holds.")
    assert (await data(client, f"/runs/{tid}"))["state"] == "waiting"

    await rt.leases.release(tid, "run_other")
    retry = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    assert retry.status_code == 200, retry.text
    assert (await data(client, f"/runs/{tid}"))["state"] == "done"
    runs = (await client.get(f"/v1/threads/{tid}/runs")).json()["data"]
    assert sum(r["nodes"].count("send_reply") for r in runs) == 1


async def test_a_two_approver_approval_without_step_up_is_refused_and_not_recorded(
    stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = stack
    tid = await paused_dispute(client)

    async def needs_step_up(rt: Runtime, payload: dict[str, Any]) -> bool:
        return True

    monkeypatch.setattr(hitl_facade, "_needs_step_up", needs_step_up)
    res = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "step_up_required"
    assert (await data(client, f"/reviews/{tid}"))["status"] == "pending"
    forged = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved", "stepUpToken": "su_1"})
    assert forged.status_code == 422 and "malformed" in forged.json()["error"]["message"]
    token = await step_up(client)
    ok = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved", "stepUpToken": token})
    assert ok.status_code == 200, ok.text


async def money_paused(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> str:
    tid = await paused_dispute(client)

    async def needs_step_up(rt: Runtime, payload: dict[str, Any]) -> bool:
        return True

    monkeypatch.setattr(hitl_facade, "_needs_step_up", needs_step_up)
    return tid


async def refusal(client: AsyncClient, tid: str, token: str, **headers: str) -> str:
    res = await client.post(
        f"/reviews/{tid}/decision", json={"decision": "approved", "stepUpToken": token}, headers=headers
    )
    assert res.status_code == 422, res.text
    assert (await data(client, f"/reviews/{tid}"))["status"] == "pending"
    return res.json()["error"]["message"]


async def test_forged_step_up_is_refused(stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = stack
    tid = await money_paused(client, monkeypatch)
    forged = mint_step_up("j.richardson@harborpine.example", HmacSigner(b"guessed-key"))
    assert "(signature)" in await refusal(client, tid, forged)


async def test_expired_step_up_is_refused(stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch) -> None:
    client, rt = stack
    tid = await money_paused(client, monkeypatch)
    stale = mint_step_up("j.richardson@harborpine.example", step_up_signer(rt), now=time.time() - 301)
    assert "(expired)" in await refusal(client, tid, stale)


async def test_step_up_for_another_person_is_refused(
    stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = stack
    tid = await money_paused(client, monkeypatch)
    lees = await step_up(client, "lee@harborpine.example")
    assert "(subject)" in await refusal(client, tid, lees)


async def test_workflow_review_is_never_decided_by_its_requester(stack: tuple[AsyncClient, Runtime]) -> None:
    # A workflow's requester is its process principal; a caller presenting that identity is refused like a person
    # deciding their own request, and nothing is recorded.
    client, _ = stack
    tid = await paused_dispute(client)
    res = await client.post(
        f"/reviews/{tid}/decision", json={"decision": "approved"}, headers={"X-Dev-User": "workflow:complex_workflow"}
    )
    assert res.status_code == 403, res.text
    assert (await data(client, f"/reviews/{tid}"))["status"] == "pending"


async def test_a_thread_whose_graph_cannot_be_resolved_does_not_break_the_lists(
    stack: tuple[AsyncClient, Runtime],
) -> None:
    # A per-agent graph (`agent:<id>`) registered at publish is not compiled again after a restart; its threads must
    # not turn the Cases and Reviews lists into a 404 for everyone.
    client, rt = stack
    tid = await paused_dispute(client)
    assert rt.graph_store is not None
    await rt.graph_store.create_thread("th_orphan", "agent:ag_gone", {}, "team_all", "2026-10-11T00:00:00Z")
    runs = await client.get("/runs", params={"view": "needs_person", "page": 1, "pageSize": 25})
    assert runs.status_code == 200, runs.text
    assert [r["id"] for r in runs.json()["data"]["data"]] == [tid]
    reviews = await client.get("/reviews", params={"view": "open", "page": 1, "pageSize": 1})
    assert reviews.status_code == 200, reviews.text
    assert reviews.json()["data"]["viewCounts"]["open"] == 1


async def test_reviews_say_the_tools_service_is_down_instead_of_failing_obscurely() -> None:
    # With a gateway configured, tools-service decides a call's access class; unreachable, the review answers 503
    # with the reason rather than a 500, and never guesses a class that could lower the approvers needed.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    dead = httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=1)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        gateway=dead,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        tid = await paused_dispute(client)
        res = await client.get(f"/reviews/{tid}")
        assert res.status_code == 503, res.text
        assert res.json()["error"]["code"] == "tools_unavailable"


async def test_the_runs_list_builds_full_rows_for_its_page_only(
    stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sidebar asks for one row to read the counts. Building every thread's full row (its checkpoint, journal and
    # timers) made that call take seconds on a database with a thousand threads.
    client, _ = stack
    paused = [await paused_dispute(client) for _ in range(4)]
    built: list[str] = []
    full = hitl_facade.run_row

    async def counting(rt: Runtime, row: dict[str, Any], *args: Any) -> dict[str, Any]:
        built.append(row["id"])
        return await full(rt, row, *args)

    monkeypatch.setattr(hitl_facade, "run_row", counting)
    page = await data(client, "/runs?view=needs_person&page=1&pageSize=1")
    assert len(built) == 1, built
    assert page["viewCounts"]["needs_person"] == 4 and page["pagination"]["total"] == 4
    row = page["data"][0]
    assert row["id"] in paused and row["state"] == "waiting" and row["subject"] == EMAILS[0]["subject"]
    assert row["steps"], "the page row is the full row, with its steps"


async def test_the_list_row_and_the_detail_page_agree_on_every_case(stack: tuple[AsyncClient, Runtime]) -> None:
    # A list row and its detail page disagreeing (waiting in one, done in the other; two subjects) is what a person
    # sees first. Seeded: paused cases, a decided one, one whose thread errored while still paused, and a second
    # input run with a different email.
    client, rt = stack
    paused = [await paused_dispute(client) for _ in range(2)]
    decided = await paused_dispute(client)
    await client.post(f"/reviews/{decided}/decision", json={"decision": "approved"})
    errored = await paused_dispute(client)
    assert rt.graph_store is not None
    await rt.graph_store.set_thread_status(errored, "error", "2026-10-11T00:00:00Z")
    rerun = await thread(client, "complex_workflow")
    await run(client, rerun, {"input": {"email": EMAILS[1]}})
    # Marked interrupted with nothing pending: the thread row and the checkpoint disagree; both views must show one.
    stale = await paused_dispute(client)
    await client.post(f"/reviews/{stale}/decision", json={"decision": "approved"})
    await rt.graph_store.set_thread_status(stale, "interrupted", "2026-10-11T00:00:00Z")

    open_rows = (await data(client, "/runs?view=open&page=1&pageSize=50"))["data"]
    done_rows = (await data(client, "/runs?view=done_today&page=1&pageSize=50"))["data"]
    # A row is in the view its own fields say: the counts and the rows come from the same source.
    assert all(r["state"] in ("running", "waiting") for r in open_rows), [(r["id"], r["state"]) for r in open_rows]
    assert all(r["state"] in ("done", "failed") for r in done_rows), [(r["id"], r["state"]) for r in done_rows]
    listed = {r["id"]: r for r in [*open_rows, *done_rows]}
    assert {*paused, decided, errored, rerun, stale} <= set(listed), set(listed)
    for tid in (*paused, decided, errored, rerun, stale):
        detail = await data(client, f"/runs/{tid}")
        for field in ("state", "status", "subject", "queue", "slaMinutes", "reviewId"):
            assert listed[tid].get(field) == detail.get(field), (tid, field, listed[tid].get(field), detail.get(field))
    assert listed[errored]["state"] == "waiting", "an errored thread still at its interrupt is waiting"
    assert listed[rerun]["subject"] == EMAILS[1]["subject"]
