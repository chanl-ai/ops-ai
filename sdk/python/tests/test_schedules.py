"""The schedule noun and `opsai workflows schedule`, by failure mode: a rule's fields sent outside `rule` or without
its kind (the API refuses it); a verb calling the wrong path; the CLI printing the rule instead of the server's words;
a refused rule exiting zero; and the tick method `workflows.schedule` lost beside the new noun."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from ops_ai import OpsAI
from ops_ai._cli import workflows as cli_workflows
from ops_ai.cli import main
from ops_ai.errors import OpsError

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


def test_save_and_preview_send_the_kinds_own_fields_inside_rule() -> None:
    seen: list[httpx.Request] = []
    client = ops(seen, data=VIEW)
    client.workflows.schedules.save(
        "held_wires", "start", kind="every", every=15, unit="minutes", start="07:00", tz="Europe/London"
    )
    client.workflows.schedules.preview(kind="every", every=15, unit="minutes", start="07:00", tz="Europe/London")
    save, prev = seen
    assert (save.method, save.url.path.endswith(URL)) == ("PUT", True)
    assert json.loads(save.content) == {"rule": RULE}
    assert (prev.method, prev.url.path.endswith("/v1/schedules/preview")) == ("POST", True)
    assert json.loads(prev.content) == {"rule": RULE}


def test_show_clear_and_kinds_use_their_own_paths_and_the_tick_method_remains() -> None:
    seen: list[httpx.Request] = []
    client = ops(seen, data=[])
    client.workflows.schedules.kinds()
    client.workflows.schedules.show("held_wires", "start")
    assert [(r.method, r.url.path.split("/v1", 1)[1]) for r in seen] == [
        ("GET", "/schedules/kinds"),
        ("GET", URL.removeprefix("/v1")),
    ]
    cleared: list[httpx.Request] = []
    ops(cleared, status=204).workflows.schedules.clear("held_wires", "start")
    assert [(r.method, r.url.path.endswith(URL)) for r in cleared] == [("DELETE", True)]
    assert callable(client.workflows.schedule), "the one-off tick method stays beside the noun"


def test_the_cli_sets_with_fields_prints_the_servers_words_and_a_refusal_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(cli_workflows, "client", lambda _ns: ops(seen, data=VIEW))
    code = main(
        [
            "workflows",
            "schedule",
            "set",
            "held_wires",
            "--step",
            "start",
            "--kind",
            "every",
            "--set",
            "every=15",
            "--set",
            "unit=minutes",
            "--set",
            "start=07:00",
            "--set",
            "tz=Europe/London",
        ]
    )
    assert code == 0 and json.loads(seen[0].content) == {"rule": RULE}
    assert "Every 15 minutes from 07:00, Europe/London" in capsys.readouterr().out

    refused: list[httpx.Request] = []
    error = {"code": "schedule_invalid", "message": "Every is 1 to 1440 minutes.", "details": {"field": "every"}}
    monkeypatch.setattr(cli_workflows, "client", lambda _ns: ops(refused, status=422, error=error))
    assert (
        main(["workflows", "schedule", "set", "held_wires", "--step", "start", "--kind", "every", "--set", "every=0"])
        != 0
    )
    assert "Every is 1 to 1440" in capsys.readouterr().err


def test_cli_show_clear_kinds_and_preview_reach_their_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(cli_workflows, "client", lambda _ns: ops(seen, data=VIEW))
    base = ["workflows", "schedule"]
    assert main([*base, "show", "held_wires", "--step", "start"]) == 0
    assert main([*base, "kinds"]) == 0
    assert main([*base, "preview", "--rule", json.dumps(RULE)]) == 0
    assert [(r.method, r.url.path.split("/v1", 1)[1]) for r in seen] == [
        ("GET", URL.removeprefix("/v1")),
        ("GET", "/schedules/kinds"),
        ("POST", "/schedules/preview"),
    ]
    assert json.loads(seen[2].content) == {"rule": RULE}
    cleared: list[httpx.Request] = []
    monkeypatch.setattr(cli_workflows, "client", lambda _ns: ops(cleared, status=204))
    assert main([*base, "clear", "held_wires", "--step", "start"]) == 0
    assert cleared[0].method == "DELETE"


def test_an_unknown_error_from_the_api_is_an_ops_error() -> None:
    error = {
        "code": "schedule_kind_unknown",
        "message": "A schedule is every, not cron.",
        "details": {"known": ["every"]},
    }
    with pytest.raises(OpsError):
        ops([], status=422, error=error).workflows.schedules.save("held_wires", "start", kind="cron", line="* * * * *")
