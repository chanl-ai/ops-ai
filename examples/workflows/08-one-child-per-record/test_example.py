import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, upload_bytes, wait_run

YAML = FOLDER / "resources" / "workflow.yaml"
WORKFLOW_ID = "one_child_per_record"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _case(name: str) -> tuple[dict, dict]:
    payload = json.loads((FOLDER / "fixtures" / f"{name}.json").read_text())
    expected = json.loads((FOLDER / "expected" / f"{name}.json").read_text())
    return payload, expected


def _input_with_file(ops, name: str) -> tuple[dict, dict]:
    payload, expected = _case(name)
    path = FOLDER / "fixtures" / str(payload.pop("file"))
    token = uuid4().hex
    raw = path.read_bytes()
    content = (
        "".join("\n" if c in "01234567" else " " for c in token).encode()
        if name == "unreadable"
        else raw + f"\n# {token}\n".encode()
    )
    payload["file"] = upload_bytes(ops, f"{name}-{token}-{path.name}", content, mime="text/plain")
    return payload, expected


def _run_id(run: dict) -> str:
    return str(run.get("id") or run.get("runId"))


def _children(run: dict) -> list[dict]:
    found = list(run.get("children") or [])
    if found:
        return found
    output = run.get("output") if isinstance(run.get("output"), dict) else {}
    found = list(output.get("children") or [])
    if found:
        return found
    for step in run.get("steps") or []:
        if step.get("nodeId") == "each":
            out = step.get("output") if isinstance(step.get("output"), dict) else {}
            found = list(out.get("children") or [])
            if found:
                return found
    return []


def _start(ops, payload: dict) -> dict:
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    started = ops.workflows.run(WORKFLOW_ID, input=payload, mode="test", wait=True)
    return wait_run(ops, _run_id(started))


def test_all_children_succeed() -> None:
    ops = ops_client()
    payload, expected = _input_with_file(ops, "records")
    run = _start(ops, payload)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
    children = _children(run)
    assert children, run
    assert all(str(child.get("outcome")) == "accepted" for child in children), children


def test_one_child_fails_while_siblings_finish() -> None:
    ops = ops_client()
    payload, expected = _input_with_file(ops, "partial")
    run = _start(ops, payload)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
    children = _children(run)
    outcomes = {str(child.get("outcome")) for child in children}
    assert "child_failed" in outcomes, children
    assert "accepted" in outcomes, children


def test_unreadable_extract_ends_fanout_failed() -> None:
    ops = ops_client()
    payload, expected = _input_with_file(ops, "unreadable")
    run = _start(ops, payload)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
