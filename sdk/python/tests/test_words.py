"""The Apps area in the screen's words (c-616 K1), by failure mode against httpx's mock transport: Connected lists an
app whose account never signed in; a tool run goes to another module of the app, or Mock reaches the system; the team's
own client is saved without the revision the route needs, or onto someone else's account; a caller gets the envelope
instead of Usage's rows; turning on a custom app sends a request to a plugin route; and a document type's copy is made
in agents-service."""

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
        {"id": "plugin:desk", "kind": "plugin", "state": "connected", "status": "healthy"},
        {"id": "plugin:crm", "kind": "plugin", "state": "not_signed_in", "status": "healthy"},
        {"id": "builtin:files", "kind": "builtin", "status": "available"},
    ]
    ops = client({("GET", "systems"): cards}, [])
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
    assert body(run) == {"mode": "mock", "input": {"id": "r1"}, "environment": "test"}
    ops.tools.run("con_desk", "read_record", {"id": "r1"}, real=True)
    assert body(seen[-1])["mode"] == "real"


def test_the_teams_own_client_goes_on_the_apps_account_with_its_revision() -> None:
    seen: list[httpx.Request] = []
    answers = {
        ("GET", "apps/plugin:desk"): {**PAGE, "connection": {"id": "con_team"}},
        ("GET", "connections/con_team"): {"revision": 4},
    }
    client(answers, seen).credentials.set("plugin:desk", client_id="own-app", client_secret="s3")
    put = seen[-1]
    assert (put.method, put.url.path) == ("PUT", "/api/tools/v1/connections/con_team/environments/production")
    assert body(put) == {"revision": 4, "settings": {"clientId": "own-app"}, "secretValues": {"clientSecret": "s3"}}


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
        "environment": "production",
    }


def test_a_run_uses_production_when_only_production_is_set() -> None:
    # The app page lists every environment with whether it is set; a listed but unset test is not one to run in.
    seen: list[httpx.Request] = []
    envs = {"test": {"set": False}, "production": {"set": True}}
    page = {
        **PAGE,
        "card": {**PAGE["card"], "moduleIds": ["mod_b"]},
        "connection": {"id": "con_desk", "environments": envs},
    }
    client({("GET", "apps/con_desk"): page}, seen).tools.run("con_desk", "read_record", {"id": "r1"})
    assert body(seen[-1])["environment"] == "production"
