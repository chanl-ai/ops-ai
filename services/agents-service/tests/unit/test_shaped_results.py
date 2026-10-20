"""Shaped tool results on the chat (c-055 T004), by failure mode: a registry operation's result never shaped, its
declared shape ignored, a shaped part lost on reload, and a legacy view turned into a part."""

from __future__ import annotations

from typing import Any

from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.gateway import GatewayToolExecutor
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.chat_threads import AssistantBuilder
from ops_contracts.chat import ChatMessage, WidgetPart
from tests.conftest import SEED

ROWS = [{"day": "2026-10-01", "opened": 3}, {"day": "2026-10-02", "opened": 5}]


class Gateway:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def call(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> dict[str, Any]:
        return self.data


class Directory:
    async def operations(self) -> list[OperationRef]:
        return [OperationRef("daily", "", "read", {}, False, "mod_1", "Bank", output_shape="rows")]


async def test_an_ok_result_with_no_view_is_shaped_and_honours_the_declared_shape() -> None:
    inferred = await GatewayToolExecutor(Gateway({"ok": True, "output": ROWS}), None).execute(  # type: ignore[arg-type]
        "daily", {}, key="k", approval_token=None
    )
    assert inferred.view is not None and inferred.view["part"]["shape"] == "series"
    declared = await GatewayToolExecutor(Gateway({"ok": True, "output": ROWS}), Directory()).execute(  # type: ignore[arg-type]
        "daily", {}, key="k", approval_token=None
    )
    assert declared.view is not None and declared.view["part"]["shape"] == "rows"


async def test_a_failed_call_or_a_legacy_view_is_left_alone() -> None:
    failed = await GatewayToolExecutor(Gateway({"ok": False, "output": ROWS}), None).execute(  # type: ignore[arg-type]
        "daily", {}, key="k", approval_token=None
    )
    assert failed.view is None
    legacy: dict[str, Any] = {"kind": "record", "title": "Account", "fields": []}
    kept = await GatewayToolExecutor(Gateway({"ok": True, "output": ROWS, "view": legacy}), None).execute(  # type: ignore[arg-type]
        "daily", {}, key="k", approval_token=None
    )
    assert kept.view == legacy


def test_the_builder_keeps_a_shaped_part_on_the_message_and_streams_it() -> None:
    """Thread reloads rebuild messages from the same events, so a part kept here is a part kept on reload."""
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    part: dict[str, Any] = {"type": "widget", "id": "", "shape": "rows", "data": [{"id": "T1"}]}
    call: dict[str, Any] = {
        "id": "c1",
        "tool": "list_transactions",
        "server": "Bank",
        "input": {},
        "status": "ok",
        "output": [{"id": "T1"}],
    }
    events = builder.apply("tool_call", {**call, "view": {"part": part}})
    streamed = [e for e in events if e.type == "part"]
    assert [p.wire() for p in builder.message.parts or []] == [{**part, "id": "wp_c1"}]
    assert len(streamed) == 1 and streamed[0].wire()["part"]["id"] == "wp_c1"
    assert not builder.message.widgets, "no legacy widget for a shaped part"


def test_a_part_with_a_schema_is_accepted_and_sent_back_as_schema() -> None:
    """lib/types/widgets.ts carries `schema?` on every part; the wire model forbids unknown fields, so a missing field
    would refuse the first form part."""
    schema = {"type": "object", "properties": {"amount": {"type": "number"}}}
    sent = {"type": "widget", "id": "wp_1", "shape": "form", "data": {}, "schema": schema}
    assert WidgetPart.model_validate(sent).wire() == sent
