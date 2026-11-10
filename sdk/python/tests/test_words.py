"""The Apps area in the screen's words, by failure mode against httpx's mock transport: Connected lists an
app whose account never signed in; a tool run goes to another module of the app, or Mock reaches the system; the team's
own client is saved without the revision the route needs, or onto someone else's account; a caller gets the envelope
instead of Usage's rows; turning on a custom app sends a request to a plugin route; a document type's copy is made in
agents-service; and a sandbox account is added as a live one."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from ops_ai import OpsAI

BASE = "https://ops.test"
PAGE = {
    "card": {"id": "con_desk", "kind": "custom", "moduleIds": ["mod_a", "mod_b"]},
    "connection": {"id": "con_desk"},
    "tools": [{"name": "read_record", "title": "Read a record", "access": "read"}],
}


def client(answers: dict[tuple[str, str], Any], seen: list[httpx.Request]) -> OpsAI:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        path = r.url.path.split("/v1/", 1)[1]
        return httpx.Response(200, json={"success": True, "data": answers.get((r.method, path), {})})

    return OpsAI(
        api_key="ok_test", base_url=BASE, team="team_a", http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def body(r: httpx.Request) -> Any:
    return json.loads(r.content)


def test_connected_keeps_signed_in_and_built_in_apps_only() -> None:
    cards = [
        {"id": "plugin:desk", "kind": "plugin", "state": "connected", "appGroup": "on", "status": "healthy"},
        # Its team account reads connected, but the caller has not signed in: their card says so.
        {"id": "plugin:crm", "kind": "plugin", "state": "connected", "appGroup": "needs_you", "status": "healthy"},
        {"id": "builtin:files", "kind": "builtin", "status": "available"},
    ]
    ops = client({("GET", "apps"): cards}, [])
    assert [c["id"] for c in ops.apps.list(connected=True)] == ["plugin:desk", "builtin:files"]
    assert [c["id"] for c in ops.apps.list(connected=False)] == ["plugin:crm"]


def test_a_tool_runs_on_the_module_that_holds_it_and_mock_says_mock() -> None:
    seen: list[httpx.Request] = []
    answers = {
        ("GET", "apps/con_desk"): PAGE,
        ("GET", "tool-modules/mod_a"): {"id": "mod_a", "operations": [{"name": "write_record"}]},
        ("GET", "tool-modules/mod_b"): {"id": "mod_b", "operations": [{"name": "read_record"}]},
    }
    ops = client(answers, seen)
    ops.tools.run("con_desk", "read_record", {"id": "r1"})
    run = seen[-1]
    assert run.url.path.endswith("/v1/tool-modules/mod_b/operations/read_record/run")
    # Left to the gateway, a run is a test run: the app's sandbox account when it has one.
    assert body(run) == {"mode": "mock", "input": {"id": "r1"}}
    ops.tools.run("con_desk", "read_record", {"id": "r1"}, real=True)
    assert body(seen[-1])["mode"] == "real"


def test_an_account_picks_the_teams_credential_by_its_id_with_its_revision() -> None:
    seen: list[httpx.Request] = []
    answers = {
        ("GET", "apps/plugin:desk"): {**PAGE, "connection": {"id": "con_team"}},
        ("GET", "apps/plugin:desk/accounts/con_team"): {"revision": 4},
    }
    client(answers, seen).credentials.set("plugin:desk", "cred_bank")
    put = seen[-1]
    assert (put.method, put.url.path) == ("PATCH", "/api/tools/v1/apps/plugin:desk/accounts/con_team")
    assert body(put) == {"revision": 4, "credentialId": "cred_bank"}


def test_usage_is_the_calls_rows_not_the_envelope() -> None:
    rows = [{"id": "gwc_1", "runAs": "team account"}]
    ops = client({("GET", "executions"): {"data": rows, "pagination": {"page": 1}}}, [])
    assert ops.usage.list() == rows


def test_a_custom_app_is_not_turned_on_through_a_plugin_route() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ValueError, match="not an app a plugin brings"):
        client({}, seen).apps.turn_on("con_desk")
    assert not seen


def test_a_document_types_copy_is_made_in_documents_service() -> None:
    seen: list[httpx.Request] = []
    template = {"source": "plugin:desk", "id": "case-letter", "kind": "document_type"}
    client({}, seen).resources.add(template)
    assert seen[-1].url.path == "/api/documents/v1/resources/plugin:desk:case-letter/copies"


def test_credentials_list_answers_the_rows_of_the_app_credentials_route() -> None:
    seen: list[httpx.Request] = []
    rows = [{"id": "con_desk", "app": "plugin:desk", "type": "own", "accounts": 2, "status": "working"}]
    ops = client({("GET", "app-credentials"): rows}, seen)
    assert ops.credentials.list() == rows
    assert seen[-1].url.path.endswith("/v1/app-credentials")


def test_credentials_create_posts_the_app_its_client_and_secret_to_the_app_credentials_route() -> None:
    seen: list[httpx.Request] = []
    row = {"id": "con_desk", "app": "plugin:desk", "type": "own"}
    ops = client({("POST", "app-credentials"): row}, seen)
    assert ops.credentials.create("plugin:desk", client_id="bank-app", client_secret="s3") == row
    assert seen[-1].method == "POST"
    assert json.loads(seen[-1].content) == {
        "app": "plugin:desk",
        "clientId": "bank-app",
        "clientSecret": "s3",
    }


def test_a_sandbox_account_is_added_as_a_sandbox_under_its_app() -> None:
    seen: list[httpx.Request] = []
    client({}, seen).accounts.add("plugin:desk", "Desk sandbox", sandbox=True, credentialId="cred_uat")
    made = seen[-1]
    assert (made.method, made.url.path) == ("POST", "/api/tools/v1/apps/plugin:desk/accounts")
    assert body(made) == {"name": "Desk sandbox", "sandbox": True, "credentialId": "cred_uat"}


def test_a_copy_is_removed_by_the_delete_of_the_service_that_keeps_its_kind() -> None:
    seen: list[httpx.Request] = []
    ops = client({}, seen)
    made = {"copy": {"kind": "document_type", "recordId": "dt_1", "source": "plugin:desk", "templateId": "case-letter"}}
    ops.resources.remove(made)
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", "/api/documents/v1/document-types/dt_1")
    ops.resources.remove(made["copy"] | {"kind": "workflow", "recordId": "case_review_1"})
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", "/api/agents/v1/workflows/definitions/case_review_1")


def test_the_resources_list_is_the_apps_one_list_and_an_update_names_the_copy() -> None:
    seen: list[httpx.Request] = []
    ops = client({}, seen)
    ops.resources.list("plugin:desk")
    assert seen[-1].url.path == "/api/tools/v1/apps/plugin:desk/resources"
    copy = {"kind": "agent", "recordId": "ag_1", "source": "plugin:desk", "templateId": "case-helper"}
    ops.resources.update({"copy": copy}, confirm=True)
    assert seen[-1].url.path == "/api/agents/v1/resources/plugin:desk:case-helper/copies/ag_1/update"
    assert body(seen[-1]) == {"confirm": True}


def test_a_document_types_update_and_a_knowledge_sources_removal_go_to_the_service_that_keeps_them() -> None:
    seen: list[httpx.Request] = []
    ops = client({}, seen)
    copy = {"kind": "document_type", "recordId": "dt_1", "source": "plugin:desk", "templateId": "case-letter"}
    ops.resources.update(copy)
    assert seen[-1].url.path == "/api/documents/v1/resources/plugin:desk:case-letter/copies/dt_1/update"
    ops.resources.remove(copy | {"kind": "knowledge_source", "recordId": "src_1", "templateId": "articles"})
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", "/api/kb/v1/sources/src_1")


def test_a_connector_is_disconnected_on_its_primary_account_not_the_apps_first() -> None:
    # Connectors are one row per app; disconnecting one names the account the row calls primary.
    rows = [{"appId": "plugin:github", "name": "GitHub", "primaryAccountId": "con_second", "accountCount": 2}]
    seen: list[httpx.Request] = []
    ops = client({("GET", "me/connections"): rows}, seen)
    assert ops.me.connectors.list() == rows
    ops.me.connectors.disconnect("github")
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", "/api/tools/v1/me/accounts/con_second")
    with pytest.raises(ValueError, match="not one of your connectors"):
        ops.me.connectors.disconnect("plugin:hubspot")
