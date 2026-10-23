"""The case told for people (c-500), on PostgreSQL, by failure mode: how a case started is wrong for an email, a form
or a hand-opened case; the walk up the runs that started it follows another team's run, runs past its bound or fails
on a parent that is gone; the feed shows another team's run, a scoped key's other workflows or a masked value, grows
without a cap, or words a case event unlike the Activity page (identity-and-tenancy.md, "The team is the
workspace")."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import case_story
from ops_agents.api.case_page import whats_left
from ops_agents.api.engine_runs import MAX_CHILD_DEPTH, runs_above
from ops_agents.store.case_links import CaseLinks
from ops_agents.store.cases import CaseStore
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs
from tests.api.test_action_roles import REVIEWER
from tests.api.test_case_page import _linked_runs, data, typed_case  # pyright: ignore[reportPrivateUsage]
from tests.api.test_case_routes import started_run
from tests.api.test_run_story import DEBTOR, EMAIL, INTAKE, World
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER
from tests.engine.test_run_reads_masked import Policies


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _origin(w: World, created_by: str, team: str = "team_ops") -> dict[str, Any]:
    rt: Any = SimpleNamespace(db=w.engine)
    with tenant_scope(w.tenant):
        return await case_story.origin(rt, {"created_by": created_by, "team_id": team})


async def test_an_email_started_case_names_the_email_and_links_the_first_run(engine: AsyncEngine) -> None:
    w = World(engine)
    for flow in (INTAKE, DEBTOR):
        await w.publish(flow)
    mail = await w.run(INTAKE, EMAIL)
    debtor = await w.run(DEBTOR, {"record": {"name": "Marcus Bell"}}, created_by=f"run:{mail}")
    told = await _origin(w, f"run:{debtor}")
    assert told == {
        "kind": "email",
        "text": "From an email from registry@court.example: Notice of garnishment",
        "runId": mail,
        "href": f"/workflows/runs/{mail}",
    }, told


async def test_a_form_started_case_names_who_started_it(engine: AsyncEngine) -> None:
    w = World(engine)
    await w.publish(DEBTOR)
    run = await w.run(DEBTOR, {"record": {"name": "Priya Nair"}}, created_by="maya@x")
    told = await _origin(w, f"run:{run}")
    assert (told["kind"], told["text"], told["runId"]) == ("request", "maya@x started Debtor", run), told


async def test_a_hand_opened_case_says_who_opened_it(engine: AsyncEngine) -> None:
    told = await _origin(World(engine), "maya@x")
    assert told == {"kind": "person", "text": "Opened by maya@x", "runId": None, "href": None}, told


async def test_origin_never_follows_another_teams_run(engine: AsyncEngine) -> None:
    w = World(engine)
    for flow in (INTAKE, DEBTOR):
        await w.publish(flow)
    theirs = await w.run(INTAKE, EMAIL, team="team_other")
    debtor = await w.run(DEBTOR, {"record": {"name": "Marcus Bell"}}, created_by=f"run:{theirs}")
    told = await _origin(w, f"run:{debtor}")
    # The email run is another team's: for this case it does not exist, so the walk stops at the debtor's own run.
    assert (told["kind"], told["text"], told["runId"]) == ("other", "Started by Debtor", debtor), told
    # A case whose opening run is another team's names no run at all.
    other_case = await _origin(w, f"run:{theirs}")
    assert other_case == {"kind": "other", "text": "Opened by a workflow", "runId": None, "href": None}, other_case


async def test_origin_stops_at_the_bound_and_at_a_missing_parent(engine: AsyncEngine) -> None:
    w = World(engine)
    await w.publish(DEBTOR)
    chain = [await w.run(DEBTOR, {}, created_by="run:wfrun_gone")]
    for _ in range(MAX_CHILD_DEPTH + 2):
        chain.append(await w.run(DEBTOR, {}, created_by=f"run:{chain[-1]}"))
    with tenant_scope(w.tenant):
        store = RunStore(w.tx)
        last = await store.get(chain[-1])
        assert last is not None
        above = await runs_above(store, last)
        top = await store.get(chain[0])
        assert top is not None
        # The first run's parent is gone: the walk stops at it rather than failing.
        assert await runs_above(store, top) == []
    assert [r["id"] for r in above] == list(reversed(chain[-1 - MAX_CHILD_DEPTH : -1])), [r["id"] for r in above]
    told = await _origin(w, f"run:{chain[1]}")
    assert told["runId"] == chain[0], told


def _verb(line: dict[str, Any]) -> str:
    """A feed line without who did it, as the Activity page says it beside its actor column."""
    rest = str(line["text"])[len(str(line["actor"])) + 1 :]
    return rest[:1].upper() + rest[1:]


async def test_a_hand_opened_case_says_who_opened_it_and_has_a_feed(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case = await typed_case(stack)
    assert (
        await c.post(f"/v1/cases/{case}/events", json={"kind": "note", "text": "Called the customer"}, headers=BUILDER)
    ).status_code == 201
    assert (await c.patch(f"/v1/cases/{case}", json={"priority": "urgent"}, headers=BUILDER)).status_code == 200
    page = data(await c.get(f"/v1/cases/{case}", headers=BUILDER))
    assert (page["origin"]["kind"], page["origin"]["runId"]) == ("person", None), page["origin"]
    assert page["origin"]["text"].startswith("Opened by "), page["origin"]
    assert [_verb(x) for x in page["feed"]["lines"]] == [
        "Changed Priority to Urgent",
        "Added a note: Called the customer",
        "Opened this case",
    ], page["feed"]
    assert page["feed"]["more"] == 0


async def test_activity_and_feed_say_a_case_entry_alike(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case = await typed_case(stack)
    await c.post(f"/v1/cases/{case}/events", json={"kind": "note", "text": "Called the customer"}, headers=BUILDER)
    await c.patch(f"/v1/cases/{case}", json={"status": "waiting_on_customer"}, headers=BUILDER)
    feed = {_verb(x) for x in data(await c.get(f"/v1/cases/{case}", headers=BUILDER))["feed"]["lines"]}
    rows = data(await c.get("/v1/activity", params={"case": case}, headers=BUILDER))["data"]
    activity = {r["title"] for r in rows if r["kind"] == "case"}
    assert (
        activity
        == feed
        == {"Opened this case", "Added a note: Called the customer", "Set the status to Waiting on customer"}
    ), (activity, feed)


async def test_the_feed_caps_at_200_lines_and_counts_the_rest(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case = await typed_case(stack)
    with tenant_scope(TENANT):
        for i in range(205):
            await CaseStore(rt.db).add_event(case, "note", ref=None, detail={"text": f"note {i}"}, by="b@x")
    told = data(await c.get(f"/v1/cases/{case}", headers=BUILDER))["feed"]
    assert (len(told["lines"]), told["more"]) == (200, 6), (len(told["lines"]), told["more"])


async def test_the_feed_never_shows_another_teams_run(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case = await typed_case(stack)
    await _linked_runs(stack, case, 1)
    with tenant_scope(TENANT):
        async with EngineTransactions(rt.db).tenant_tx() as conn:
            await conn.execute(
                engine_runs.insert().values(
                    id="wfrun_theirs00001", tenant_id=TENANT, team_id="team_fraud", workflow_id="wf", version=1,
                    digest="d", run_key="theirs", mode="live", status="succeeded", created_by="b@x",
                    created_at="2026-10-19T00:00:00+00:00", updated_at="2026-10-19T00:00:00+00:00",
                )
            )  # fmt: skip
        await CaseStore(rt.db).add_event(case, "run", ref="wfrun_theirs00001", detail={}, by="b@x")
    lines = data(await c.get(f"/v1/cases/{case}", headers=BUILDER))["feed"]["lines"]
    hrefs = {x["href"] for x in lines}
    assert f"/workflows/runs/wfrun_{case[-6:]}000" in hrefs, lines
    assert not any("wfrun_theirs00001" in str(h) for h in hrefs), lines


async def test_a_scoped_key_reads_its_workflows_lines_only(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    case = await typed_case(stack)
    await _linked_runs(stack, case, 2)
    with tenant_scope(TENANT):
        row = await CaseStore(rt.db).get(case, ["team_ops"])
        runs = await CaseLinks(rt.db).runs(case, "team_ops")
        everyone = await case_story.feed(rt, row, runs, scope=None)
        scoped = await case_story.feed(rt, row, runs, scope=("workflow", "another_workflow"))
    assert sum(1 for x in everyone["lines"] if "/workflows/runs/" in str(x["href"])) == 2, everyone
    assert not any("/workflows/runs/" in str(x["href"]) for x in scoped["lines"]), scoped


async def test_masking_follows_the_case_teams_setting(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case = await typed_case(stack)
    await c.post(
        f"/v1/cases/{case}/events", json={"kind": "note", "text": "Write to marcus.bell@example.com"}, headers=BUILDER
    )

    async def feed_text() -> str:
        return " ".join(x["text"] for x in data(await c.get(f"/v1/cases/{case}", headers=BUILDER))["feed"]["lines"])

    rt.policies = Policies({"team_ops": False})
    assert "marcus.bell@example.com" in await feed_text()
    rt.policies = Policies(True)
    assert "marcus.bell@example.com" not in await feed_text()


async def _waiting_run(s: Stack, case: str, title: str) -> str:
    c, rt = s
    run = await started_run(c, BUILDER, f"left_{case[-6:]}")
    assert (
        await c.post(f"/v1/cases/{case}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
    ).status_code == 201
    waiting = {"node": "review", "iteration": 1, "interruptId": "i1",
               "payload": {"node": "review", "iteration": 1, "title": title}}  # fmt: skip
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    return run


async def _left(s: Stack, case: str, who: dict[str, str] = BUILDER) -> dict[str, Any]:
    return data(await s[0].get(f"/v1/cases/{case}", headers=who))["whatsLeft"]


async def test_whats_left_names_who_what_and_by_when_until_nothing_is_left(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case = await typed_case(stack)
    run = await _waiting_run(stack, case, "Check the complaint")
    left = await _left(stack, case)
    [item] = left["items"]
    assert (item["kind"], item["who"], item["what"]) == ("task", "team_ops", "Check the complaint"), item
    assert item["dueAt"] and item["href"].startswith("/reviews/") and left["resolvable"] is False, left
    assert (
        await c.post(f"/reviews/{run}/decision", json={"decision": "approved"}, headers=REVIEWER)
    ).status_code == 200
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="succeeded", waiting=None)
    assert await _left(stack, case) == {"items": [], "resolvable": True}


async def test_resolve_is_not_offered_while_a_run_is_in_flight(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    case = await typed_case(stack)
    run = await started_run(c, BUILDER, f"busy_{case[-6:]}")
    await c.post(f"/v1/cases/{case}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="running")
    assert await _left(stack, case) == {"items": [], "resolvable": False}


async def test_resolve_is_offered_only_to_who_may_change_status(stack: Stack) -> None:  # noqa: F811
    case = await typed_case(stack)
    # Every member of the team works its cases (cases.edit, c-128), a viewer too.
    assert (await _left(stack, case))["resolvable"] is True
    assert (await _left(stack, case, VIEWER))["resolvable"] is True
    row = {"status": "open"}
    assert whats_left([], [], [], row, team_name="Ops", due=None, may_edit=False)["resolvable"] is False
    assert (await stack[0].patch(f"/v1/cases/{case}", json={"status": "resolved"}, headers=BUILDER)).status_code == 200
    assert (await _left(stack, case))["resolvable"] is False, "a resolved case is not offered Resolve again"


def test_a_refused_action_stays_in_whats_left() -> None:
    refused = {"taskId": "r1", "status": "refused", "label": "Place hold", "href": "/reviews/r1"}
    left = whats_left([], [refused], [], {"status": "open"}, team_name="Ops", due="2026-10-30", may_edit=True)
    assert left == {
        "items": [
            {
                "kind": "action",
                "who": "Ops",
                "what": "Place hold: refused by the bank's system, decide again",
                "dueAt": "2026-10-30",
                "href": "/reviews/r1",
            }
        ],
        "resolvable": False,
    }, left


async def test_the_feed_tells_the_email_that_led_to_the_case_and_says_its_opening_once(engine: AsyncEngine) -> None:
    w = World(engine)
    for flow in (INTAKE, DEBTOR):
        await w.publish(flow)
    mail = await w.run(INTAKE, EMAIL)
    debtor = await w.run(DEBTOR, {"record": {"name": "Marcus Bell"}}, created_by=f"run:{mail}")
    rt: Any = SimpleNamespace(db=engine)
    with tenant_scope(w.tenant):
        store = CaseStore(engine)
        opened = await store.open(
            team_id="team_ops", subject="Levy notice: Marcus Bell", priority="high", by=f"run:{debtor}"
        )
        case = str(opened.case["id"])
        await store.add_event(case, "run", ref=debtor, detail={}, by=f"run:{debtor}")
        row = await store.get(case, ["team_ops"])
        runs = await CaseLinks(engine).runs(case, "team_ops")
        told = [x["text"] for x in (await case_story.feed(rt, row, runs, scope=None))["lines"]]
    assert "Email from registry@court.example: Notice of garnishment" in told, told
    assert not any(t.endswith("opened this case") for t in told), told
