"""GET /v1/activity (c-201), by failure mode, through the app with platform tokens: a row from a team the caller is not
in leaks; another person's private chat shows; a facet count disagrees with the rows it counts; a skipped email looks
like one that started a run."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from ops_agents.api.runs import graph_store
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvent, TriggerEvents
from ops_agents.store.widget_deployments import WidgetDeployments
from ops_engine.journal import StepRow
from ops_engine.store import RunStore, SqlJournal
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from tests.api.test_action_roles import REVIEWER
from tests.api.test_case_routes import opened, started_run
from tests.api.test_chat_owner_only import chat_reader_role, reader  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, PLATFORM, TENANT, VIEWER, person

FRAUD_BUILDER = person("omar", "team_fraud", "builder")


def two_teams() -> dict[str, str]:
    """A builder in team_ops and team_fraud, acting in team_ops."""
    claims: dict[str, Any] = {
        "sub": "lee",
        "email": "lee@northfield.example",
        "name": "lee",
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops", "team_fraud"],
        "roles": {"team_ops": "builder", "team_fraud": "builder"},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


async def activity(c: AsyncClient, who: dict[str, str], **params: Any) -> dict[str, Any]:
    r = await c.get("/v1/activity", params=params, headers=who)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def email(s: Stack, outcome: str, *, run_id: str | None = None, subject: str = "Notice") -> None:
    _, rt = s
    with tenant_scope(TENANT):
        await TriggerEvents(rt.db).add(
            TriggerEvent(
                team_id="team_ops",
                workflow_id="ops_check",
                source="email:levy@northfield.example",
                event_key=f"email:{subject}",
                sender="registry@court.example",
                subject=subject,
                received_at="",
                outcome=outcome,  # pyright: ignore[reportArgumentType]
                run_id=run_id,
            )
        )


async def test_a_member_sees_their_teams_and_never_another(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    ours = await started_run(c, BUILDER, "ops_check")
    theirs = await started_run(c, FRAUD_BUILDER, "fraud_check")
    one = await activity(c, BUILDER)
    assert [r["id"] for r in one["data"]] == [f"workflow_run:{ours}"]
    both = await activity(c, two_teams(), team="all")
    assert {r["id"] for r in both["data"]} == {f"workflow_run:{ours}", f"workflow_run:{theirs}"}
    assert [r["id"] for r in (await activity(c, two_teams()))["data"]] == [f"workflow_run:{ours}"]
    refused = await c.get("/v1/activity", params={"team": "team_fraud"}, headers=BUILDER)
    assert refused.status_code == 404


async def test_another_persons_private_chat_never_shows(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    theirs = await chat(c, VIEWER)
    mine = await activity(c, reader(None), kind="chat")
    assert mine["data"] == [] and mine["facets"]["kind"] == {}
    # With chats shared, a reader of every chat in the team sees it: the rule above is the policy, not a missing row.
    shared = await activity(c, reader({"chatThreadsOwnerOnly": False}), kind="chat")
    assert [r["id"] for r in shared["data"]] == [f"chat:{theirs}"]
    own = await activity(c, VIEWER, kind="chat")
    assert [(r["id"], r["actor"]["id"]) for r in own["data"]] == [(f"chat:{theirs}", "vera@northfield.example")]


async def test_facets_count_the_rows_under_the_other_filters(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    run = await started_run(c, BUILDER, "ops_check")
    await email(stack, "started", run_id=run, subject="Started")
    await email(stack, "filtered", subject="Filtered")
    everything = await activity(c, BUILDER)
    by_kind = {k: sum(1 for r in everything["data"] if r["kind"] == k) for k in everything["facets"]["kind"]}
    assert everything["facets"]["kind"] == by_kind == {"workflow_run": 1, "email": 2}
    emails = await activity(c, BUILDER, kind="email")
    # facets.kind ignores the kind filter, so the buttons can show every kind's count at once.
    assert emails["pagination"]["total"] == 2 and emails["facets"]["kind"] == by_kind
    assert emails["facets"]["status"] == {"done": 1, "skipped": 1}
    scoped = await activity(c, BUILDER, source="channel:levy@northfield.example")
    assert {r["kind"] for r in scoped["data"]} == {"email"} and scoped["pagination"]["total"] == 2


async def test_a_skipped_email_says_why_and_links_no_run(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await email(stack, "daily_cap", subject="Over the cap")
    [row] = (await activity(c, BUILDER, kind="email"))["data"]
    assert (row["status"], row["outcome"], row["ref"]["kind"]) == ("skipped", "daily_cap", "email")
    assert row["actor"] == {"kind": "sender", "id": "registry@court.example", "name": "registry@court.example"}
    # No mailbox record for the address: the row names the address it came to.
    assert row["source"] == {"type": "channel", "id": "levy@northfield.example", "name": "levy@northfield.example"}


async def test_a_decision_on_a_workflows_human_task_is_listed_with_who_decided(stack: Stack) -> None:  # noqa: F811
    # Decisions are read back from what the decide route writes; a reader of another shape listed none (shared, c-201).
    c, rt = stack
    run = await started_run(c, BUILDER, "ops_check")
    waiting = {"node": "review", "iteration": 1, "interruptId": "i1", "payload": {"node": "review", "iteration": 1}}
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    decided = await c.post(f"/reviews/{run}/decision", json={"decision": "approved", "reason": "ok"}, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    [row] = (await activity(c, BUILDER, kind="decision"))["data"]
    assert (row["outcome"], row["actor"]["id"], row["source"]["id"]) == (
        "approved",
        "maya@northfield.example",
        "ops_check",
    )
    assert row["ref"] == {"kind": "review", "id": run}


async def test_an_email_and_a_widget_chat_name_their_channel_records(stack: Stack) -> None:  # noqa: F811
    # The Channels page opens Activity with source=channel:<record id>; rows naming an address matched none of them.
    c, rt = stack
    with tenant_scope(TENANT):
        await MailboxStore(rt.db).create(
            MailboxRow(
                id="mbx_levy",
                team_id="team_ops",
                name="Levy notices",
                address="levy@northfield.example",
                provider="imap",
                created_by="b",
                created_at="n",
                updated_at="n",
            )
        )
        await WidgetDeployments(rt.db).add(
            {
                "id": "wd_help",
                "team_id": "team_ops",
                "name": "Intranet help",
                "agent_id": "ag_branch",
                "agent_version": 1,
                "origins": ["https://intranet.example"],
                "created_by": "b",
                "created_at": "n",
                "updated_at": "n",
            }
        )
    await email(stack, "started", subject="Notice")
    widget_chat = await chat(c, VIEWER)
    await graph_store(rt).set_deployment(widget_chat, "wd_help")  # what the widget's thread route records
    mailbox = (await activity(c, BUILDER, source="channel:mbx_levy"))["data"]
    assert [r["source"] for r in mailbox] == [{"type": "channel", "id": "mbx_levy", "name": "Levy notices"}]
    widget = (await activity(c, VIEWER, source="channel:wd_help"))["data"]
    assert [(r["id"], r["source"]["name"]) for r in widget] == [(f"chat:{widget_chat}", "Intranet help")]


async def test_a_tool_call_in_a_private_chat_lists_for_its_owner_only(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    thread = await chat(c, VIEWER)
    call = {"tool": "list_accounts", "status": "ok", "input": {"customerId": "CUS-1002"}}
    await EventLog(rt.db).append(
        thread_id=thread, team_id="team_ops", run_id=None, type_="tool_end", node="agent", data=call
    )
    [row] = (await activity(c, VIEWER, kind="tool_call"))["data"]
    assert (row["title"], row["status"], row["ref"]) == ("list_accounts", "done", {"kind": "chat", "id": thread})
    assert (await activity(c, reader(None), kind="tool_call"))["data"] == []


async def test_a_workflows_tool_step_lists_as_a_tool_call(stack: Stack) -> None:  # noqa: F811
    # Steps journaled with their node type list as tool calls; a step of another type (a review) does not.
    c, rt = stack
    run = await started_run(c, BUILDER, "ops_check")
    steps = SqlJournal(EngineTransactions(rt.db))
    with tenant_scope(TENANT):
        for node, node_type in (("hold", "ops.action.tool"), ("review", "ops.flow.humanReview")):
            await steps.begin(
                StepRow(
                    run,
                    node,
                    1,
                    1,
                    "running",
                    "write",
                    f"{run}:{node}:1:1",
                    input={"operation": "place_hold"},
                    node_type=node_type,
                )
            )
    [row] = (await activity(c, BUILDER, kind="tool_call"))["data"]
    assert (row["title"], row["status"], row["source"]["id"], row["ref"]) == (
        "place_hold",
        "running",
        "ops_check",
        {"kind": "run", "id": run},
    ), row


async def test_a_cases_activity_is_its_own_entries_and_what_its_linked_run_did(stack: Stack) -> None:  # noqa: F811
    """c-341: filtered to a case, the list holds the case's entries and the rows about its linked run (the run and the
    decision on its Human Task), and nothing about a run the case does not link."""
    c, rt = stack
    case = await opened(c, BUILDER, subject="Levy on Marcus Bell")
    linked, unlinked = await started_run(c, BUILDER, "case_check"), await started_run(c, BUILDER, "other_check")
    for body in ({"kind": "run", "ref": linked}, {"kind": "note", "text": "Called the court"}):
        added = await c.post(f"/v1/cases/{case['id']}/events", json=body, headers=BUILDER)
        assert added.status_code == 201, added.text
    waiting = {"node": "review", "iteration": 1, "interruptId": "i1", "payload": {"node": "review", "iteration": 1}}
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(linked, status="waiting", waiting=waiting)
    decided = await c.post(f"/reviews/{linked}/decision", json={"decision": "approved"}, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    found = await activity(c, BUILDER, case=case["id"])
    rows = found["data"]
    assert {r["kind"] for r in rows} == {"case", "workflow_run", "decision"}, rows
    assert {r["title"] for r in rows if r["kind"] == "case"} == {"Opened the case", "Added a run", "Added a note"}
    assert {r["ref"]["id"] for r in rows if r["kind"] != "case"} == {linked}, "only the linked run's rows"
    assert unlinked not in {r["ref"]["id"] for r in rows}
    assert found["facets"]["kind"] == {"case": 3, "workflow_run": 1, "decision": 1}, found["facets"]


async def test_another_teams_case_has_no_activity_to_read(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    case = await opened(c, BUILDER, subject="Levy on Marcus Bell")
    r = await c.get("/v1/activity", params={"case": case["id"]}, headers=FRAUD_BUILDER)
    assert r.status_code == 404, r.text
