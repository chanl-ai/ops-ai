"""The call log's rows, by failure mode: an approved write that does not say who approved it, and a chat
call whose run cannot be told from a workflow's."""

from __future__ import annotations

from typing import Any, cast

from ops_tools.modules.executions import call_row
from ops_tools.modules.seed import tool_title
from ops_tools.store.calls import GatewayCall
from ops_tools.store.modules import ModuleColumns

BLANK = dict.fromkeys(GatewayCall.model_fields)


def _row(**over: Any) -> GatewayCall:
    return GatewayCall.model_validate({
        **BLANK,
        "id": "gwc_1", "created_at": "2026-10-17T10:00:00Z", "tool": "place_hold", "access": "write",
        "outcome": "ok", "latency_ms": 12, "sub": "user:j.richardson@harborpine.example", "act": "agent:ag_branch",
        "thread_id": "th_abc", "step": "s1", "approvers": [], "approval_token_id": None, "decision": "allow",
        "reasons": [], "effect": True, "input_hash": "h", "idempotency_key": "k", "effect_scope": "none", **over,
    })  # fmt: skip


def test_an_approved_write_names_who_approved_it() -> None:
    row = call_row(_row(approvers=["Maya Okafor"], approval_token_id="tok_1"), {}, None)
    assert row["approval"] == {"kind": "person", "tokenId": "tok_1", "by": "Maya Okafor"}


def test_a_chat_call_carries_its_thread_and_no_workflow() -> None:
    row = call_row(_row(access="read", tool="get_account"), {}, None)
    assert (row["runId"], row["workflowId"], row["agentSlug"]) == ("th_abc", "", "ag_branch")
    assert row["approval"] == {"kind": "none"}


def test_a_call_shows_its_tools_title_and_app_never_only_the_slug() -> None:
    """A chat, an approval and the call log read the tool's title and its app's name from the row."""
    module = cast(ModuleColumns, {"id": "mod_plugin_salesforce", "display_name": "Salesforce", "system": "Salesforce"})
    row = call_row(_row(tool="salesforce_get_record"), {}, module, "Get a record")
    assert (row["title"], row["app"]) == ("Get a record", "Salesforce"), row
    plain = call_row(_row(), {}, None)
    assert (plain["title"], plain["app"]) == ("Place hold", ""), "a tool with no title reads as words, not its slug"


def test_a_teams_own_tool_has_a_title_in_words() -> None:
    """A custom tool (`open_case`) was listed by its code name where every other tool shows a title."""
    cases = cast(ModuleColumns, {"name": "cases"})
    assert tool_title(cases, "open_case", None) == "Open case"
    assert tool_title(cases, "openCase", lambda m, op: None) == "Open case"
    assert tool_title(cases, "open_case", lambda m, op: "Open a case") == "Open a case"


def test_a_team_login_call_records_the_login_and_the_person_who_asked() -> None:
    """A chat on an app everyone uses with the team's login acts as that login; the audit row keeps who asked too."""
    team = _row(acting_for="j.richardson@harborpine.example", credential="team", signed_in_as="ops@harborpine.example")
    assert call_row(team, {}, None).get("runAs") == {
        "kind": "team",
        "login": "ops@harborpine.example",
        "askedBy": "j.richardson@harborpine.example",
    }
    own = _row(acting_for="j.richardson@harborpine.example", credential="person")
    assert call_row(own, {}, None).get("runAs") == {"kind": "person", "email": "j.richardson@harborpine.example"}
