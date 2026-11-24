"""`opsai workflows schedule` and the noun under it, in one walk by failure mode: a rule's fields sent outside `rule`
or without its kind (the API refuses it); a verb calling the wrong path; the CLI printing the rule instead of the
server's words; a refused rule exiting zero; the verb's first name `set` lost; and the tick method `workflows.schedule`
lost beside the new noun. The use case's sdk and cli layers run the same verbs against the real API."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from ops_ai import OpsAI
from ops_ai._cli import workflows as cli_workflows
from ops_ai.cli import main

URL = "/v1/workflows/definitions/held_wires/triggers/start/schedule"
RULE = {"kind": "every", "every": 15, "unit": "minutes", "start": "07:00", "tz": "Europe/London"}
VIEW = {
    "workflowId": "held_wires",
    "triggerStep": "start",
    "rule": RULE,
    "words": "Every 15 minutes from 07:00, Europe/London",
    "nextRuns": ["2026-11-24T07:00:00Z"],
    "changedBy": "user_ana",
    "changedAt": "2026-11-23T10:00:00Z",
}


def ops(seen: list[httpx.Request], status: int = 200, data: Any = None, error: Any = None) -> OpsAI:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if error:
            return httpx.Response(status, json={"success": False, "error": error})
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json={"success": True, "data": data})

    return OpsAI(
        api_key="ok_t",
        base_url="https://ops.test",
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def using(client: OpsAI) -> Callable[[object], OpsAI]:
    return lambda _ns: client


def test_each_verb_reaches_its_route_prints_the_servers_words_and_a_refusal_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(cli_workflows, "client", using(ops(seen, data=VIEW)))
    base, wf = ["workflows", "schedule"], ["held_wires", "--step", "start"]
    fields = ["--kind", "every", "--set", "every=15", "--set", "unit=minutes", "--set", "start=07:00"]
    fields += ["--set", "tz=Europe/London"]
    for verb in ("save", "set"):
        assert main([*base, verb, *wf, *fields]) == 0
    assert "Every 15 minutes from 07:00, Europe/London" in capsys.readouterr().out
    assert main([*base, "show", *wf]) == 0
    assert main([*base, "kinds"]) == 0
    assert main([*base, "preview", "--rule", json.dumps(RULE)]) == 0
    assert [(r.method, r.url.path.split("/v1", 1)[1]) for r in seen] == [
        ("PUT", URL.removeprefix("/v1")),
        ("PUT", URL.removeprefix("/v1")),
        ("GET", URL.removeprefix("/v1")),
        ("GET", "/schedules/kinds"),
        ("POST", "/schedules/preview"),
    ]
    assert [json.loads(r.content) for r in seen if r.method != "GET"] == [{"rule": RULE}] * 3
    cleared: list[httpx.Request] = []
    monkeypatch.setattr(cli_workflows, "client", using(ops(cleared, status=204)))
    assert main([*base, "clear", *wf]) == 0
    assert [(r.method, r.url.path.endswith(URL)) for r in cleared] == [("DELETE", True)]
    assert callable(ops([]).workflows.schedule), "the one-off tick method stays beside the noun"

    error = {"code": "schedule_invalid", "message": "Every is 1 to 1440 minutes.", "details": {"field": "every"}}
    monkeypatch.setattr(cli_workflows, "client", using(ops([], status=422, error=error)))
    assert main([*base, "save", *wf, "--kind", "every", "--set", "every=0"]) != 0
    assert "Every is 1 to 1440" in capsys.readouterr().err
