"""`opsai plugin test` sends a data tool's request as tools-service sends it, by failure mode: an input the call leaves
out is sent empty instead of its default, so a test cannot show the request tools-service makes; the plugin's and the
tool's headers are left off, so a missing API-version header passes its tests; a header naming an unset setting is
sent with the placeholder in it; and a header outranks the connection's sign-in."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from test_query_inputs import with_tools
from test_validate import plugin

from ops_plugin_sdk import Plugin
from ops_plugin_sdk.testing import Fake, call

SETTINGS = {"instance_url": "https://alpha.my.desk.test"}
TOOLS = """
  - name: list_issues
    access: read
    headers: { X-Trace: "desk-{api_version}", X-Region: "{region}" }
    input:
      state: { type: string, enum: [open, closed, all], required: false, default: open }
    request:
      method: GET
      path: /issues
      query: { state: "{{state}}", per_page: "50" }
  - name: add_note
    access: write
    input:
      id: { type: string, pattern: "^[0-9]+$" }
      body: { type: string }
      kind: { type: string, required: false, default: note }
    request: { method: POST, path: "/issues/{id}/notes", body: '{"body": {{body}}, "kind": {{kind}}}' }
"""


def desk(tmp_path: Path) -> Plugin:
    manifest = with_tools(TOOLS).replace("settings:\n", "settings:\n  region: { type: string }\n", 1)
    manifest = manifest.replace(
        "egress:", 'headers:\n  Accept: application/vnd.desk+json\n  X-Api-Version: "{api_version}"\negress:', 1
    )
    root = plugin(tmp_path, manifest)
    return Plugin.beside(str(root / "__init__.py"))


def run(tmp_path: Path) -> tuple[Plugin, Fake, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    return desk(tmp_path), Fake(httpx.Client(transport=httpx.MockTransport(record)), "t"), seen


def test_an_input_left_out_is_sent_as_its_default(tmp_path: Path) -> None:
    p, fake, seen = run(tmp_path)
    call(p, "list_issues", {}, SETTINGS, fake)
    assert dict(seen[-1].url.params) == {"state": "open", "per_page": "50"}
    call(p, "add_note", {"id": "7", "body": 'Seen "again"'}, SETTINGS, fake)
    assert json.loads(seen[-1].content) == {"body": 'Seen "again"', "kind": "note"}


def test_the_plugins_and_the_tools_headers_go_out_and_the_sign_in_wins(tmp_path: Path) -> None:
    p, fake, seen = run(tmp_path)
    call(p, "list_issues", {"state": "all"}, SETTINGS, fake)
    sent = seen[-1].headers
    assert (sent["accept"], sent["x-api-version"], sent["x-trace"]) == ("application/vnd.desk+json", "1", "desk-1")
    assert "x-region" not in sent, "a header whose setting is unset is left out"
    assert sent["authorization"] == "Bearer t"
    call(p, "list_issues", {}, {**SETTINGS, "region": "eu"}, fake)
    assert seen[-1].headers["x-region"] == "eu"
