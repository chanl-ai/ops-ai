"""A plugin tool's title from its manifest (c-581), by failure mode: the approval card and the tools catalog show the
raw operation name (salesforce_update_record) where the plugin gave a title, and a tool with no title loses its
readable name."""

from __future__ import annotations

import json
from typing import Any, cast

from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.chat_threads import AssistantBuilder
from ops_agents.api.review_text import describe_call, humanize
from ops_agents.api.routers.tool_catalog import known_tools, tool_options
from ops_contracts.chat import ApprovalWidget, ChatMessage, WidgetEvent
from tests.conftest import SEED

TITLED = OperationRef(
    name="salesforce_update_record",
    title="Update a record",
    description="Changes fields of one record",
    access="write",
    input_schema={"properties": {"object": {"type": "string"}, "id": {"type": "string"}}},
    requires_approval=True,
    module_id="mod_plugin_salesforce",
    module_name="Salesforce",
)
UNTITLED = OperationRef(
    name="crm_lookup_account",
    description="Looks up an account",
    access="read",
    input_schema={},
    requires_approval=False,
    module_id="mod_crm",
    module_name="CRM",
)


class Directory:
    async def operations(self) -> list[OperationRef]:
        return [TITLED, UNTITLED]


class Rt:
    """The runtime parts describe_call and the tools catalog read: the catalogue and the tool directory."""

    def __init__(self) -> None:
        self.catalog = load_catalog(SEED)

    def directory(self) -> Directory:
        return Directory()


async def test_an_approval_card_names_a_plugin_tool_by_its_title() -> None:
    call = {"tool": "salesforce_update_record", "input": {"object": "Case", "id": "500A"}}
    told = await describe_call(cast(Any, Rt()), call, currency=None, money_key=None)
    assert told["label"] == "Update a record" and told["sentence"].startswith("Update a record"), told
    plain = await describe_call(
        cast(Any, Rt()), {"tool": "crm_lookup_account", "input": {}}, currency=None, money_key=None
    )
    assert plain["label"] == humanize("crm_lookup_account"), plain


async def test_the_tools_catalog_lists_a_plugin_tools_title(monkeypatch: Any) -> None:
    monkeypatch.setattr("ops_agents.api.routers.tool_catalog.published_workflows", _none)
    monkeypatch.setattr("ops_agents.api.routers.tool_catalog.engine_workflows", _none)
    rows = {r["name"]: r for r in await known_tools(cast(Any, Rt()))}
    assert rows["salesforce_update_record"]["title"] == "Update a record", rows["salesforce_update_record"]
    assert rows["crm_lookup_account"]["title"] is None


async def _none(*_: Any) -> list[Any]:
    return []


async def test_the_tools_picker_labels_and_finds_a_plugin_tool_by_its_title(monkeypatch: Any) -> None:
    monkeypatch.setattr("ops_agents.api.routers.tool_catalog.published_workflows", _none)
    monkeypatch.setattr("ops_agents.api.routers.tool_catalog.engine_workflows", _none)
    found = await tool_options(cast(Any, Rt()), search="update a record", cursor=None, limit=25, ids=None)
    labels = [o["label"] for o in json.loads(bytes(found.body))["data"]["data"]]
    assert labels == ["Update a record"], labels


def test_a_chat_approval_card_names_a_plugin_tool_by_its_title() -> None:
    titles = {"salesforce_update_record": "Update a record"}
    builder = AssistantBuilder(
        load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"), titles=titles
    )
    held = {
        "tool": "salesforce_update_record",
        "input": {"object": "Case", "id": "500A"},
        "review_id": "r1",
        # As the agent kernel words the wait (ops_agent_kernel/kernel.py): with the operation's name.
        "needed": "Approval to run salesforce_update_record",
        # The graph copies the same wording into the card's action (graphs/definition.py).
        "action": "Approval to run salesforce_update_record",
    }
    events = builder.apply("waiting_review", {"id": "i1", "payload": held})
    widget = next(e.widget for e in events if isinstance(e, WidgetEvent))
    assert isinstance(widget, ApprovalWidget), widget
    assert (widget.title, widget.tool_label) == ("Update a record", "Update a record"), widget
    assert "salesforce_update_record" not in widget.summary + widget.action, (widget.summary, widget.action)
