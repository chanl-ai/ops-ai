# ruff: noqa: E501
# Printed lines are the experiment's record and stay whole.
"""Experiment 3: every write tool call through a gateway that decides with OPA and an approval token bound to the input.

Needs `make db-up` (PostgreSQL and OPA) and `make migrate`. Starts the gateway on :8720 and a Runtime on :8723 with
OPS_GATEWAY_URL pointing at it, then:
  1. calls the gateway directly with one call per refusal case and prints the status and OPA's reasons;
  2. runs the dispute workflow to its review, tries to resume without a token, approves through the review service,
     resumes with the token, and prints the gateway_calls rows for the thread;
  3. sends the same approved reply again and shows the gateway answers with the first send.

  OPENAI_API_KEY=... uv run python experiments/e3_gateway_approval_token.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from ops_service_kit.ids import input_hash, new_id
from ops_service_kit.settings import Settings
from ops_tools.tokens import Binding, mint

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / ".logs"
GATEWAY, RUNTIME = 8720, 8723
EMAIL: dict[str, Any] = json.loads((ROOT / "tests" / "fixtures" / "seed" / "dispute_emails.json").read_text())[1]
KEY = Settings().review_key.get_secret_value()
SUB = "runtime:local"
DOC = {"customerId": "C-1042", "document": "proof of address", "reason": "Address changed last week."}
HOLD = {"wireId": "W-88213", "hours": 24, "reason": "First wire to a payee added this morning."}


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def spawn(module: str, port: int, extra: dict[str, str]) -> subprocess.Popen[bytes]:
    LOGS.mkdir(exist_ok=True)
    env = {**os.environ, "PYDANTIC_AI_NO_BANNER": "1", **extra}
    log = (LOGS / f"e3-{module}.log").open("ab")
    proc = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env, stdout=log, stderr=log)
    for _ in range(80):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    proc.kill()
    raise SystemExit(f"{module} did not come up on :{port}; see {LOGS}")


def token(thread: str, step: str, tool: str, args: dict[str, Any], approvers: list[str], **kw: Any) -> str:
    return mint(Binding(thread, step, tool, input_hash(args), approvers), KEY, ttl_s=kw.pop("ttl_s", 300), **kw)


def call(
    gw: httpx.Client, tool: str, args: dict[str, Any], *, thread: str, step: str, tok: str | None
) -> httpx.Response:
    return gw.post(
        "/v1/calls",
        json={
            "tool": tool,
            "input": args,
            "key": step,
            "runContext": {"thread": thread, "step": step, "sub": SUB, "act": "e3"},
            "approvalToken": tok,
        },
    )


def show(label: str, r: httpx.Response) -> None:
    body = r.json()
    if r.status_code == 200:
        out(f"  {label}: {r.status_code} allow")
    else:
        out(f"  {label}: {r.status_code} {body['error']['details']['reasons']}")


def refusals(gw: httpx.Client) -> None:
    out("## 1. Refusal cases, straight to the gateway")
    t = new_id("gth")
    show("read, no token", call(gw, "lookup_account", {"query": "CHQ-2219"}, thread=t, step="r1", tok=None))
    show("write, no token", call(gw, "request_document", DOC, thread=t, step="w1", tok=None))
    tok = token(t, "w2", "request_document", DOC, ["dana@bank.test"])
    edited = {**DOC, "document": "bank statements"}
    show("write, input edited after approval", call(gw, "request_document", edited, thread=t, step="w2", tok=tok))
    old = token(t, "w3", "request_document", DOC, ["dana@bank.test"], ttl_s=60, now=time.time() - 120)
    show("write, expired token", call(gw, "request_document", DOC, thread=t, step="w3", tok=old))
    other = token("gth_other", "w4", "request_document", DOC, ["dana@bank.test"])
    show("write, token from another thread", call(gw, "request_document", DOC, thread=t, step="w4", tok=other))
    forged = mint(Binding(t, "w5", "request_document", input_hash(DOC), ["dana@bank.test"]), "guessed-key", ttl_s=300)
    show("write, token signed with another key", call(gw, "request_document", DOC, thread=t, step="w5", tok=forged))
    one = token(t, "m1", "place_wire_hold", HOLD, ["dana@bank.test"])
    show("money, one approver", call(gw, "place_wire_hold", HOLD, thread=t, step="m1", tok=one))
    two = token(t, "m1", "place_wire_hold", HOLD, ["dana@bank.test", "lee@bank.test"])
    show("money, two approvers", call(gw, "place_wire_hold", HOLD, thread=t, step="m1", tok=two))
    as_float = {**HOLD, "hours": 24.0}
    show(
        "money, hours sent as 24.0 after approving 24",
        call(gw, "place_wire_hold", as_float, thread=t, step="m1", tok=two),
    )


def stream(rt: httpx.Client, tid: str, body: dict[str, Any]) -> tuple[int, str]:
    with rt.stream("POST", f"/v1/threads/{tid}/runs/stream", json=body) as r:
        text = "".join(r.iter_text())
    status = next(
        (
            json.loads(line[5:])["data"].get("status")
            for line in reversed(text.splitlines())
            if line.startswith("data:") and '"end"' in line
        ),
        None,
    )
    return r.status_code, str(status) if status else text[-300:]


def dispute(rt: httpx.Client, gw: httpx.Client) -> None:
    out("\n## 2. Dispute workflow with send_reply through the gateway")
    tid = rt.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {"source": "e3"}}).json()["data"][
        "threadId"
    ]
    out(f"thread {tid}: run -> {stream(rt, tid, {'input': {'email': EMAIL}})}")
    call_ = rt.get(f"/v1/threads/{tid}/state").json()["data"]["interrupt"]["payload"]["call"]
    out(
        f"review asks to approve: tool={call_['tool']} step={call_['step']} inputHash={input_hash(call_['input'])[:12]}…"
    )
    bare = rt.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}})
    out(f"resume approved without a token -> {bare.status_code} {bare.json()['error']['code']}")
    approval = rt.post(f"/v1/threads/{tid}/approvals", json={}).json()["data"]
    out(
        f"approvals -> approvers={approval['approvers']} needed={approval['needed']} token={approval['approvalToken'][:24]}…"
    )
    out(
        f"resume with the token -> {stream(rt, tid, {'resume': {'decision': 'approved', 'approvalToken': approval['approvalToken']}})}"
    )
    values = rt.get(f"/v1/threads/{tid}/state").json()["data"]["values"]
    out(f"thread status={values['status']} sent={values['sent']}")

    out("\n## 3. The same approved send again (a node re-run after a crash)")
    again = call(
        gw, "send_reply", call_["input"], thread=tid, step=call_["step"], tok=approval["approvalToken"]
    ).json()["data"]
    out(f"gateway -> reference={again['output']['reference']} replayOf={again.get('replayOf')}")
    rows = subprocess.run(
        [
            "docker",
            "exec",
            "ops-runtime-postgres-1",
            "psql",
            "-U",
            "ops",
            "-d",
            "ops_runtime",
            "-tAc",
            f"select tool, decision, outcome, effect, reasons from gateway_calls where thread_id = '{tid}' order by created_at",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    out("gateway_calls for the thread (tool | decision | outcome | effect | reasons):")
    for line in (rows.stdout or rows.stderr).strip().splitlines():
        out(f"  {line}")


def main() -> None:
    gateway = spawn("ops_tools", GATEWAY, {"OPS_GATEWAY_PORT": str(GATEWAY)})
    runtime = spawn(
        "ops_agents.api",
        RUNTIME,
        {"OPS_PORT": str(RUNTIME), "OPS_GATEWAY_URL": f"http://127.0.0.1:{GATEWAY}"},
    )
    try:
        with (
            httpx.Client(base_url=f"http://127.0.0.1:{GATEWAY}", timeout=30) as gw,
            httpx.Client(base_url=f"http://127.0.0.1:{RUNTIME}", timeout=300) as rt,
        ):
            refusals(gw)
            dispute(rt, gw)
    finally:
        for p in (runtime, gateway):
            p.terminate()
            p.wait(timeout=10)


if __name__ == "__main__":
    main()
