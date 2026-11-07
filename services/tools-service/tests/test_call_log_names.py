"""The call log's agent and workflow, by failure mode: a call an agent made shows the agent's id (`ag_…`) where its
name belongs, and the log fails to list when agents-service does not answer instead of keeping the ids."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_service_kit.errors import ServiceUnavailable
from ops_tools.modules.service import ModuleService
from ops_tools.modules.tool_users import StaticToolUsers

WHO = SimpleNamespace(tenant_id="t", team=SimpleNamespace(id="team_ops"))


def rows() -> list[dict[str, Any]]:
    return [
        {
            "target": "salesforce_query",
            "agentSlug": "ag_2c30",
            "agentName": "ag_2c30",
            "workflowId": "",
            "workflowName": "",
        },
        {"target": "get_customer", "agentSlug": "", "agentName": "", "workflowId": "wf_9", "workflowName": "wf_9"},
    ]


async def test_agents_and_workflows_read_by_name() -> None:
    uses = {
        "salesforce_query": [{"kind": "agent", "id": "ag_2c30", "name": "Case helper"}],
        "get_customer": [{"kind": "workflow", "id": "wf_9", "name": "Customer summary"}],
    }
    host = SimpleNamespace(users=StaticToolUsers(uses))
    named = await ModuleService._named(host, WHO, rows())  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]
    assert (named[0]["agentName"], named[1]["workflowName"]) == ("Case helper", "Customer summary")


async def test_the_log_keeps_its_ids_when_agents_service_does_not_answer() -> None:
    class Down:
        async def of(self, tenant_id: str, team_id: str, tools: list[str]) -> dict[str, Any]:
            raise ServiceUnavailable("down", code="tool_users_unavailable")

    named = await ModuleService._named(SimpleNamespace(users=Down()), WHO, rows())  # type: ignore[arg-type]  # pyright: ignore[reportPrivateUsage]
    assert (named[0]["agentName"], named[1]["workflowName"]) == ("ag_2c30", "wf_9")
