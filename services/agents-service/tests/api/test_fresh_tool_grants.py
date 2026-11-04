"""A tool a team has just been given can be granted at once, by failure mode: the tools list this service
keeps for 30 s does not have a plugin turned on moments ago, so saving an agent with its tool was refused as unknown
until the list expired."""

from __future__ import annotations

from pathlib import Path

import httpx

from ops_agents.activities.tool_directory import ToolsOperations
from ops_agents.store.tenancy import current_tenant
from ops_identity import ServiceClient, dev_service_signer

from ..unit.test_tool_directory import Clock, Tools, op
from .test_agent_limits import FRAUD, _app, _data  # pyright: ignore[reportPrivateUsage]


async def test_a_tool_turned_on_moments_ago_is_granted_without_waiting_for_the_list_to_expire(tmp_path: Path) -> None:
    tools = Tools({"local": [op("lookup_account")]})
    async with _app(tmp_path) as (c, app):
        client = httpx.AsyncClient(transport=httpx.MockTransport(tools.handler), base_url="http://tools")
        service = ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=current_tenant)
        app.state.runtime.tool_directory = ToolsOperations(service, ttl_s=30, clock=Clock())
        before = _data(await c.get(f"/v1/agents/{FRAUD}"))
        assert "salesforce_get_record" not in before.get("toolIds", [])
        # Salesforce is turned on for the team: tools-service now offers its tool; the cached list does not have it.
        tools.by_tenant["local"].append(op("salesforce_get_record"))
        granted = await c.patch(
            f"/v1/agents/{FRAUD}", json={"toolIds": [*before.get("toolIds", []), "salesforce_get_record"]}
        )
        assert granted.status_code == 200, granted.text
        assert "salesforce_get_record" in granted.json()["data"]["toolIds"]
