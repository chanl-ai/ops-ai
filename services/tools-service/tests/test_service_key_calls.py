"""A key limited to picked tools, by failure mode: the key runs a tool it was not given, over MCP or over POST
/v1/calls; the call log names the person who made the key instead of the key; a write by a key waits for a person who
is not there.

Names fixed here for the builder: platform-service introspection answers the key's name as `name`, its picked tools as
`apiKey.tools` and its maker as `apiKey.makerEmail`; the call log keeps them as `key_name` and `key_maker`."""

from __future__ import annotations

from typing import Any

import pytest

from . import test_mcp_server
from .test_mcp_server import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]

PICKED = {
    "ok_picked": ("key_picked", ["lookup_case"], "Claims triage script"),
    "ok_elsewhere": ("key_elsewhere", ["close_case"], "Nightly export"),
    "ok_writer": ("key_writer", ["lookup_case", "close_case"], "Closer"),
}
MAKER = "priya.shah@bank.test"


def _introspect(tenant: str) -> Any:
    async def introspect(secret: str) -> dict[str, Any] | None:
        found = PICKED.get(secret)
        if found is None:
            return None
        key_id, tools, name = found
        return {
            "sub": f"key:{key_id}",
            "email": "",
            "name": name,
            "tenantId": tenant,
            "teamId": "team_lending",
            "scopes": ["read"],
            "apiKey": {"id": key_id, "tools": tools, "makerEmail": MAKER, "target": None},
        }

    return introspect


@pytest.fixture
def picked_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Platform-service's answers for keys that carry picked tools, in place of the plain keys of test_mcp_server."""
    monkeypatch.setattr(test_mcp_server, "_introspect", _introspect)


def call_body(tool: str, key: str) -> dict[str, Any]:
    return {"tool": tool, "input": {"caseId": "CASE-4112"}, "key": key, "runContext": {"environment": "test"}}


async def test_a_key_lists_and_runs_only_the_tools_it_was_given(picked_keys: None, stack: Stack) -> None:  # noqa: F811
    async with stack.running(), stack.http("ok_elsewhere") as http, stack.client(http, "/mcp/team_lending") as c:
        listed = {t.name for t in (await c.list_tools()).tools}
        refused = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
    assert listed == set(), "close_case is a write, so a key picking only it lists nothing"
    assert refused.is_error is True and refused.structured_content is not None
    assert refused.structured_content["code"] == "insufficient_scope"
    async with stack.running(), stack.http("ok_picked") as http, stack.client(http, "/mcp/team_lending") as c:
        assert {t.name for t in (await c.list_tools()).tools} == {"lookup_case"}
    # The same limit holds on the REST route keys reach too.
    other = await stack.api.client.post(
        "/v1/calls", json=call_body("lookup_case", "rest-other"), headers={"Authorization": "Bearer ok_elsewhere"}
    )
    assert other.status_code in (200, 403) and "insufficient_scope" in other.text, other.text
    own = await stack.api.client.post(
        "/v1/calls", json=call_body("lookup_case", "rest-own"), headers={"Authorization": "Bearer ok_picked"}
    )
    assert own.status_code == 200 and "insufficient_scope" not in own.text, own.text


async def test_the_call_log_names_the_key_and_its_maker_at_call_time(picked_keys: None, stack: Stack) -> None:  # noqa: F811
    async with stack.running(), stack.http("ok_picked") as http, stack.client(http, "/mcp/team_lending") as c:
        await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
    [row] = await stack.rows("lookup_case")
    assert (row["sub"], row["key_name"], row["key_maker"]) == ("key:key_picked", "Claims triage script", MAKER)
    assert MAKER not in (row["sub"], row["acting_for"])


async def test_a_write_by_a_key_is_a_refused_tool_error_and_holds_nothing(picked_keys: None, stack: Stack) -> None:  # noqa: F811
    async with stack.running(), stack.http("ok_writer") as http, stack.client(http, "/mcp/team_lending") as c:
        result = await c.call_tool("close_case", {"caseId": "CASE-4112"})
    assert result.is_error is True and result.structured_content is not None
    assert result.structured_content["code"] == "insufficient_scope", result
    assert not [x for x in stack.received if "closeCase" in str(x.get("body"))], "the bank received nothing"
    [row] = await stack.rows("close_case")
    assert (row["outcome"], row["decision"]) == ("refused", "deny")
    assert not row.get("approval_token_id"), "no hold was opened for a person who is not there"
