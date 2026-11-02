"""Workflow facade: validate/apply/run use the generated operations, and a failed check names its path."""

from __future__ import annotations

import json
from typing import Any

import httpx
from ops_ai import OpsAI, WorkflowCheck
from ops_ai.cli import main
from ops_ai.errors import BadRequest

BASE = "https://ops.test"


def client(handler: Any) -> OpsAI:
    return OpsAI(
        api_key="ok_test",
        base_url=BASE,
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def ok(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


DEFINITION = {
    "schemaVersion": 2,
    "id": "normalize_support_request",
    "name": "Normalize a support request",
    "nodes": [{"id": "start", "type": "ops.trigger.request", "typeVersion": 1}],
}


def test_validate_returns_a_check_that_can_raise() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        assert r.url.path.endswith("/v1/workflows/definitions/validate")
        body = json.loads(r.content)
        assert body["definition"]["id"] == "normalize_support_request"
        return ok(
            {
                "ok": False,
                "workflowId": "normalize_support_request",
                "digest": None,
                "checks": [
                    {
                        "node": "start",
                        "level": "error",
                        "code": "unconnected_port",
                        "message": "Out port payload of start leads nowhere.",
                        "path": "nodes.start",
                        "port": "payload",
                        "suggestion": "Connect this out port or remove the node.",
                    }
                ],
            }
        )

    check = client(handler).workflows.validate(DEFINITION)
    assert isinstance(check, WorkflowCheck)
    assert check.ok is False
    assert check.errors[0]["path"] == "nodes.start"
    try:
        check.raise_for_errors()
    except ValueError as exc:
        assert "nodes.start" in str(exc)
    else:
        raise AssertionError("raise_for_errors passed")


def test_apply_and_run_use_test_mode_by_default() -> None:
    seen: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(f"{r.method} {r.url.path}")
        if r.url.path.endswith("/v1/workflows/definitions"):
            return ok({"workflowId": "normalize_support_request", "version": 1, "digest": "d1", "created": True}, 201)
        if r.url.path.endswith("/v1/runs"):
            body = json.loads(r.content)
            assert body["mode"] == "test"
            return ok({"runId": "run_1", "workflowId": "normalize_support_request", "status": "queued"}, 202)
        if r.url.path.endswith("/v1/runs/run_1"):
            return ok({"id": "run_1", "status": "succeeded", "outcome": "accepted", "error": None})
        return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "message": r.url.path}})

    ops = client(handler)
    made = ops.workflows.apply(DEFINITION)
    assert made["created"] is True
    done = ops.workflows.run("normalize_support_request", input={"customerEmail": "a@b.test"}, wait=True)
    assert done["outcome"] == "accepted"
    assert any(path.endswith("/v1/runs") for path in seen)


def test_cli_validate_prints_the_failing_path(monkeypatch: Any, capsys: Any) -> None:
    class Fake:
        workflows = type(
            "W",
            (),
            {
                "validate": staticmethod(
                    lambda _: WorkflowCheck(
                        {
                            "ok": False,
                            "checks": [
                                {
                                    "path": "nodes.start",
                                    "message": "Out port payload of start leads nowhere.",
                                    "level": "error",
                                    "suggestion": "Connect this out port or remove the node.",
                                }
                            ],
                        }
                    )
                )
            },
        )()

    monkeypatch.setattr("ops_ai._cli.workflows.client", lambda ns: Fake())
    assert main(["workflows", "validate", "workflow.yaml"]) == 1
    out = capsys.readouterr().out
    assert "nodes.start" in out
    assert "Connect this out port" in out


def test_cli_run_prints_the_schema_path(monkeypatch: Any, capsys: Any) -> None:
    class Fake:
        workflows = type(
            "W",
            (),
            {
                "run": staticmethod(
                    lambda *_a, **_k: (_ for _ in ()).throw(
                        BadRequest(
                            422,
                            "invalid_input",
                            "customerEmail is required.",
                            details={"path": "customerEmail"},
                        )
                    )
                )
            },
        )()

    monkeypatch.setattr("ops_ai._cli.workflows.client", lambda ns: Fake())
    assert main(["workflows", "run", "normalize_support_request", "--input", "{}", "--test"]) == 1
    assert "customerEmail" in capsys.readouterr().err


def test_cli_convert_writes_json_from_yaml(tmp_path: Any) -> None:
    src = tmp_path / "workflow.json"
    src.write_text('{"schemaVersion": 2, "id": "echo", "name": "Echo", "nodes": [], "connections": []}\n')
    dest = tmp_path / "echo.yaml"
    assert main(["workflows", "convert", str(src), "--to", "json", "-o", str(dest)]) == 0
    assert json.loads(dest.read_text())["id"] == "echo"
