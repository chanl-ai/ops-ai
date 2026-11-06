"""The `ops` command, by failure mode: an area it does not know runs anything, `ops plugin` without the plugin kit
fails with a traceback in place of what to install, and `ops plugin` loses the verb or the folder on the way to the
kit."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import httpx
import pytest
from ops_ai import OpsAI
from ops_ai.cli import main


def test_an_unknown_area_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["nothing"])
    assert stop.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_ops_plugin_without_the_kit_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # None in sys.modules makes the import fail as it does where the kit is not installed.
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk.cli", None)
    assert main(["plugin", "validate", "somewhere"]) == 2
    assert "install ops-ai[plugin]" in capsys.readouterr().err


def test_ops_plugin_hands_the_verb_and_folder_to_the_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    kit = types.ModuleType("ops_plugin_sdk.cli")
    kit.main = lambda argv: seen.append(argv) or 1  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk", types.ModuleType("ops_plugin_sdk"))
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk.cli", kit)
    assert main(["plugin", "test", "plugins/desk"]) == 1
    assert seen == [["plugin", "test", "plugins/desk"]]


def _resources_client(seen: list[httpx.Request]) -> Any:
    rows = [
        {"id": "case-helper", "source": "plugin:test.templates", "kind": "agent", "copy": None},
        {"id": "levy", "source": "plugin:test.templates", "kind": "document_type", "copy": None},
    ]

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if r.method == "GET":
            return httpx.Response(200, json={"success": True, "data": rows})
        return httpx.Response(201, json={"success": True, "data": {"copy": {"recordId": "ag_9"}}})

    return OpsAI(
        api_key="ok_t",
        base_url="https://ops.test",
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_ops_resources_add_copies_the_resource_the_id_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr("ops_ai._cli.resources.client", lambda _ns: _resources_client(seen))
    assert main(["resources", "add", "plugin:test.templates", "levy", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"copy": {"recordId": "ag_9"}}
    # A document type is copied by documents-service, under the resource's source and id.
    assert seen[-1].method == "POST" and "/api/documents/" in str(seen[-1].url)
    assert "plugin%3Atest.templates%3Alevy" in str(seen[-1].url) or "plugin:test.templates:levy" in str(seen[-1].url)
    assert main(["resources", "add", "plugin:test.templates", "nothing"]) == 1
    assert "ops resources list plugin:test.templates" in capsys.readouterr().err


def test_ops_as_signs_in_on_a_local_stack_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["resources", "list", "plugin:x", "--as", "a@b.example", "--base-url", "https://ops.bank.example"]) == 1
    assert "local stack only" in capsys.readouterr().err
