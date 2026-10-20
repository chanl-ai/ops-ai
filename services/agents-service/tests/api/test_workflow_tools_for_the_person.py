"""A workflow an agent holds as a tool, in a chat turn, is the person's to start (c-149), by failure mode: a person who
may not start the workflow has it offered, or runs it through the agent's grant; a chat turn whose person is not known
runs it as the agent; and an unattended agent run refused for want of a person."""

from __future__ import annotations

from httpx import AsyncClient

from ops_agents.api.auth import Principal
from ops_agents.api.child_runs import ChildRuns, acting_for
from ops_agents.api.deps import Runtime
from tests.api.test_child_runs import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - the shared app fixture

EMAIL = {"sender": "a@b.example", "subject": "Dispute", "body": "I did not make this payment."}


def member(role: str) -> Principal:
    return Principal(
        name=role,
        email=f"{role}@northfieldbank.com",
        team_id="team_ops",
        tenant_id="local",
        team_ids=("team_ops",),
        role=role,
        roles={"team_ops": role},
    )


async def chat_thread(client: AsyncClient) -> str:
    r = await client.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def test_a_viewer_is_neither_offered_nor_able_to_start_the_agents_workflow(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, rt = stack
    runs = ChildRuns(rt)
    parent = await chat_thread(client)
    with acting_for(member("viewer")):
        assert await runs.offers(["workflow:dispute_email"]) == [], "a viewer may not start workflows"
        out = await runs.run(
            workflow="dispute_email", arguments=EMAIL, key="k-viewer", parent_thread_id=parent, parent_run_id=None
        )
    assert not out.ok and out.output["code"] == "role_required", out.output
    assert rt.graph_store is not None
    assert await rt.graph_store.threads("dispute_email") == [], "no child started"
    with acting_for(member("builder")):
        assert [o.name for o in await runs.offers(["workflow:dispute_email"])] == ["workflow__dispute_email"]


async def test_a_chat_turn_with_no_known_person_starts_no_workflow(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    parent = await chat_thread(client)
    out = await ChildRuns(rt).run(
        workflow="dispute_email", arguments=EMAIL, key="k-nobody", parent_thread_id=parent, parent_run_id=None
    )
    assert not out.ok and out.output["code"] == "person_required", out.output
