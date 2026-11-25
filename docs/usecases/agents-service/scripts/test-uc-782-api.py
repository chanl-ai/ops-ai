"""uc-782, api layer: docs/usecases/agents-service/only-a-person-who-may-decide.md. A person who may not decide a
review is refused (403) on every route that decides it, including a decision posted again after a reviewer's, on a
chat's write approval (a graph thread) and on a workflow's Human Task (an engine run); the reviewer's own repeat still
answers with the decided review and resumes nothing twice. agents-service runs on the scripted model; one worker
process takes the workflow run to its review. No model call is made."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import httpx
from usecase_harness import AGENTS_DIR, LOG_DIR, _env, agents, check, data, finish, pg_url, sse  # pyright: ignore[reportPrivateUsage]

# The two-person rule on (requesterMayDecide off): who asked for a write, or started a run, may not decide its review.
os.environ["OPS_DEV_POLICIES"] = '{"requesterMayDecide": false}'
OPS = {"X-Team-Id": "team_ops"}
DANA = {**OPS, "X-Dev-User": "dana@harborpine.example"}
LEE = {**OPS, "X-Dev-User": "lee@harborpine.example"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@harborpine.example"}
DEFINITION = """
schemaVersion: 2
id: uc782_one_review
name: One review (uc-782)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Review the request
    parameters: {title: Check the request, summary: "$.input.note"}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
connections:
  - {from: {node: start, port: payload}, to: {node: review, port: in}}
  - {from: {node: review, port: approve}, to: {node: approved, port: in}}
  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}
"""


@contextmanager
def worker() -> Generator[subprocess.Popen[bytes]]:
    env = _env() | {"OPS_DATABASE_URL": pg_url(), "OPS_LEASE_TTL_SECONDS": "3", "OPS_ENGINE_POLL_SECONDS": "0.2"}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc782.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


def until(what: Callable[[], Any], timeout: float = 60) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.3)
    return None


def resumes(api: httpx.Client, thread: str) -> int:
    runs = data(api.get(f"/v1/threads/{thread}/runs", headers=DANA)) or []
    return sum(1 for r in runs if r.get("kind") == "resume")


def step_up(api: httpx.Client, who: dict[str, str]) -> str:
    return str(data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=who))["token"])


with agents() as api:
    # 1. Dana's chat write waits for a reviewer.
    thread = data(api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=DANA))["id"]
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**DANA, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("1 Dana's write waits on an approval", widget is not None and widget["state"] == "pending", widget)
    assert widget is not None
    widget_url = f"/chat/threads/{thread}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    # 2-4. Dana may not decide her own write, on any route that decides it.
    own = api.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=DANA)
    check("2 Dana's decision in Reviews is refused (403)", own.status_code == 403, own.text[:300])
    card = api.post(widget_url, json={"type": "approve"}, headers=DANA)
    check("3 Dana's approve on the chat card is refused (403)", card.status_code == 403, card.text[:300])
    bulk = api.post("/reviews/bulk-decision", json={"ids": [thread], "decision": "approved"}, headers=DANA)
    skipped = (data(bulk) or {}).get("skipped") or []
    check(
        "4 Dana's bulk decision decides nothing: her task is skipped with the refusal",
        bulk.status_code == 200 and (data(bulk) or {}).get("updated") == [] and [s["id"] for s in skipped] == [thread],
        bulk.text[:300],
    )

    # 5. Lee, a reviewer, approves; the chat goes on once.
    lee = api.post(
        f"/reviews/{thread}/decision", json={"decision": "approved", "stepUpToken": step_up(api, LEE)}, headers=LEE
    )
    check("5 Lee approves and the chat resumes once", lee.status_code == 200 and resumes(api, thread) == 1, lee.text[:300])

    # 6-7. The same decision posted again: refused to Dana, answered to Lee, and nothing resumes again.
    replay = api.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=DANA)
    check("6 Dana's repeat of the decision is refused (403)", replay.status_code == 403, replay.text[:300])
    again = api.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=LEE)
    check(
        "7 Lee's repeat answers with the approved review and resumes nothing more",
        again.status_code == 200 and data(again)["status"] == "approved" and resumes(api, thread) == 1,
        again.text[:300],
    )

    # 8-11. A workflow's Human Task: Maya decides, then whoever started the run repeats her decision.
    created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=OPS)
    live = api.post("/v1/workflows/definitions/uc782_one_review/publish-requests", json={}, headers=OPS)
    check("8 the workflow is live", created.status_code == 201 and data(live)["status"] == "approved", live.text[:300])
    started = api.post(
        "/v1/runs", json={"workflowId": "uc782_one_review", "input": {"note": "Refund"}, "runKey": "uc782"}, headers=DANA
    )
    run_id = str((data(started) or {}).get("runId"))
    with worker():
        waiting = until(lambda: (data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}).get("status") == "waiting")
    check("9 Dana's run waits on its review", bool(waiting), api.get(f"/v1/runs/{run_id}", headers=OPS).text[:300])
    maya = api.post(f"/reviews/{run_id}/decision", json={"decision": "approved"}, headers=MAYA)
    check("10 Maya approves the task", maya.status_code == 200, maya.text[:300])
    for decision in ("approved", "rejected"):
        late = api.post(f"/reviews/{run_id}/decision", json={"decision": decision}, headers=DANA)
        check(f"11 Dana's {decision} after Maya's decision is refused (403)", late.status_code == 403, late.text[:300])
    same = api.post(f"/reviews/{run_id}/decision", json={"decision": "approved"}, headers=MAYA)
    check(
        "12 Maya's repeat answers with the approved task",
        same.status_code == 200 and data(same)["status"] == "approved",
        same.text[:300],
    )

finish()
