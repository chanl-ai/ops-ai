"""uc-567 every workflow run ends with a clear outcome, api layer: docs/usecases/agents-service/run-outcomes.md (c-561).
agents-service on the scripted model with tools-service as its gateway, the core bank fake behind it, files-service for
email attachments, and GreenMail for the mailbox; workers are `python -m ops_agents.api.worker` processes this script
starts, stops and lets die. No model call is made.

A write whose answer never came fails the run at once and is not sent again; tools-service stopped mid-run and started
again leaves the run to finish; a run whose worker keeps dying is marked Stuck and Retry carries it on without a second
write; Human Tasks lists a run older than the newest 200; and an email whose run will not start is set aside so the mail
after it is read, then Run again starts it."""

from __future__ import annotations

import json
import os
import re
import signal
import smtplib
import subprocess
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from email.message import EmailMessage
from typing import Any

import httpx
from fake_bank_https import private_address
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    FILES_PORT,
    LOG_DIR,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    approve_tool_review,
    check,
    core_bank,
    data,
    finish,
    pg_url,
    tools,
)

OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@harborpine.example"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
RUN = uuid.uuid4().hex[:6]
GREENMAIL_SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
GREENMAIL_IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))
IMAP_HOST, MAIL_SECRET = "mail.harborpine.test", "UC567_MAIL_PASSWORD"
ADDRESS = f"intake-{RUN}@harborpine.test"
BROKEN = f"unreadable-{RUN}"
LEASE = "2"


def flow(wid: str, nodes: list[dict[str, Any]], ends: dict[str, str]) -> dict[str, Any]:
    """Request, then `nodes` in a line, each tool's ok to the next and its other ports to Failed, then Done."""
    all_nodes = [{"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"}, *nodes]
    all_nodes += [
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": ends["ok"]}},
        {
            "id": "failed",
            "type": "ops.flow.end",
            "typeVersion": 1,
            "name": "Failed",
            "parameters": {"outcome": "failed"},
        },
    ]
    links = [{"from": {"node": "start", "port": "payload"}, "to": {"node": nodes[0]["id"], "port": "in"}}]
    for i, n in enumerate(nodes):
        after = nodes[i + 1]["id"] if i + 1 < len(nodes) else "done"
        out = "approve" if n["type"] == "ops.flow.humanReview" else "ok"
        links.append({"from": {"node": n["id"], "port": out}, "to": {"node": after, "port": "in"}})
        for port in ("refused", "error") if n["type"] == "ops.action.tool" else ("reject",):
            links.append({"from": {"node": n["id"], "port": port}, "to": {"node": "failed", "port": "in"}})
    return {"schemaVersion": 2, "id": wid, "name": wid, "nodes": all_nodes, "connections": links}


def tool(nid: str, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    params = {"operation": operation, "input": args}
    return {"id": nid, "type": "ops.action.tool", "typeVersion": 1, "name": nid, "parameters": params}


NOTE = tool(
    "note", "add_customer_note", {"customer_id": "$.input.customerId", "text": "$.input.text", "author": "uc-567"}
)
LOOKUP = tool("lookup", "get_customer", {"customer_id": "$.input.customerId"})
# The run reads the notes back from the bank at its end: what the outside system holds, not what was asked.
NOTES = tool("notes", "list_customer_notes", {"customer_id": "$.input.customerId"})
REVIEW = {
    "id": "review",
    "type": "ops.flow.humanReview",
    "typeVersion": 1,
    "name": "Check",
    "parameters": {"title": "Check"},
}
FLOWS = {
    "uncertain": flow(f"uc567_uncertain_{RUN}", [NOTE], {"ok": "noted"}),
    "outage": flow(f"uc567_outage_{RUN}", [LOOKUP], {"ok": "found"}),
    "stuck": flow(f"uc567_stuck_{RUN}", [NOTE, LOOKUP, NOTES], {"ok": "found"}),
    "tasks": flow(f"uc567_tasks_{RUN}", [REVIEW], {"ok": "checked"}),
}
MAIL_FLOW = {
    "schemaVersion": 2,
    "id": f"uc567_mail_{RUN}",
    "name": "Notice intake (uc-567)",
    "nodes": [
        {
            "id": "start",
            "type": "ops.trigger.email",
            "typeVersion": 1,
            "name": "Notice received",
            "parameters": {"mailbox": ADDRESS, "folder": "inbox"},
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Read", "parameters": {"outcome": "read"}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}


@contextmanager
def worker(name: str, extra: dict[str, str] | None = None) -> Generator[subprocess.Popen[bytes]]:
    """One worker on the run's database and gateway, with a 2 s lease so a takeover takes seconds."""
    env = _env() | {
        "OPS_DATABASE_URL": pg_url(),
        "OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}",
        "OPS_LEASE_TTL_SECONDS": LEASE,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
        **(extra or {}),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / f"worker-uc567-{name}.log").open("ab") as fh:
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


def until(what: Callable[[], Any], timeout: float = 90) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.4)
    return None


def run_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}


def ended(api: httpx.Client, run_id: str, *statuses: str) -> Callable[[], dict[str, Any] | None]:
    def probe() -> dict[str, Any] | None:
        r = run_of(api, run_id)
        return r if r.get("status") in (statuses or ("succeeded", "failed", "cancelled")) else None

    return probe


def start(api: httpx.Client, which: str, payload: dict[str, Any], *, mode: str = "live") -> str:
    body = {"workflowId": FLOWS[which]["id"], "input": payload, "mode": mode, "runKey": f"uc567-{uuid.uuid4().hex[:8]}"}
    res = api.post("/v1/runs", json=body, headers=OPS)
    return str((data(res) or {}).get("runId", ""))


def calls(gw: httpx.Client, run_id: str, target: str) -> list[dict[str, Any]]:
    rows = data(gw.get("/v1/executions", params={"thread": run_id, "pageSize": 200}))["data"]
    return [r for r in rows if r["target"] == target]


def notes_held(run: dict[str, Any], text: str) -> int:
    """How many notes with `text` the bank held when the run read them back at its end."""
    step = next((x for x in run.get("steps", []) if x.get("nodeId") == "notes"), {})
    rows = step.get("output") or []
    return sum(1 for n in rows if isinstance(n, dict) and n.get("text") == text) if isinstance(rows, list) else -1


def bank_module(gw: httpx.Client, host: str) -> str:
    """The core bank's operations as one published module: reads from GET, and the note write runs at once."""
    source = {"kind": "openapi", "specUrl": f"https://{host}/openapi.json"}
    found = data(gw.post("/v1/tool-modules/discover", json=source))
    ops = [
        {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"} for o in found["operations"]
    ]
    made = data(
        gw.post(
            "/v1/tool-modules",
            json={
                "name": f"uc567-bank-{RUN}",
                "displayName": "Core Banking (uc-567)",
                "system": found["system"],
                "type": "openapi",
                "endpoint": found["endpoint"],
                "operations": ops,
                "source": source,
            },
        )
    )
    note = next(o for o in made["operations"] if o["name"] == "add_customer_note")
    data(gw.patch(f"/v1/tool-modules/{made['id']}/operations/{note['id']}", json={"requiresApproval": False}))
    # A test call for CUS-1002 answers as a system that took the note and never replied (c-332's mock answers).
    mock = {"name": "Never answers", "match": {"customer_id": "CUS-1002"}, "timeout": True}
    data(gw.post(f"/v1/tool-modules/{made['id']}/operations/{note['id']}/mocks", json=mock))
    data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-567"}))
    approve_tool_review(gw, made["id"], SECURITY)
    return str(made["id"])


def publish(api: httpx.Client, definition: dict[str, Any]) -> str:
    api.post("/v1/workflows/definitions", json={"definition": definition}, headers=OPS)
    asked = api.post(f"/v1/workflows/definitions/{definition['id']}/publish-requests", json={}, headers=OPS)
    return str((data(asked) or {}).get("status"))


def send_mail(subject: str) -> None:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "clerk@court.example", ADDRESS, subject
    m.set_content("Please hold the account.")
    with smtplib.SMTP("127.0.0.1", GREENMAIL_SMTP) as s:
        s.send_message(m)


def main() -> None:
    with ExitStack() as stack:
        bank = stack.enter_context(core_bank())
        here = private_address()
        resolve = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"]) | {IMAP_HOST: f"{here}:{GREENMAIL_IMAP}"}
        settings = bank["settings"] | {
            "OPS_EGRESS_RESOLVE": json.dumps(resolve),
            "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
        }
        gateway = f"http://127.0.0.1:{TOOLS_PORT}"
        # The files-service agents() starts for its knowledge service, on the run's Files port.
        files_url = f"http://127.0.0.1:{FILES_PORT}"
        # Run again stores the email as the listener does, so the API needs Files too.
        api = stack.enter_context(agents(gateway_url=gateway, env={"OPS_FILES_URL": files_url}))
        tools_on = ExitStack()
        gw = tools_on.enter_context(tools(settings))
        for host in (bank["host"], IMAP_HOST):
            gw.post("/v1/egress/hosts", json={"value": host, "note": "uc-567"})
        gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "uc-567"})
        gw.post("/v1/egress/ranges", json={"value": f"{here}/32", "note": "uc-567 GreenMail"})
        gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"}, headers=OPS)
        gw.post("/v1/secrets", json={"name": MAIL_SECRET, "value": "any", "teamId": "team_ops"}, headers=OPS)
        bank_module(gw, bank["host"])
        published = {k: publish(api, d) for k, d in FLOWS.items()}
        check("setup the four workflows go live", set(published.values()) == {"approved"}, published)

        # 11. A note write whose answer never came (a test run, the mock times out after the call left tools-service):
        # the run fails at once with the reason, and the note is not sent again.
        with worker("one"):
            uncertain = start(api, "uncertain", {"customerId": "CUS-1002", "text": f"uncertain {RUN}"}, mode="test")
            failed = until(ended(api, uncertain), 120) or {}
        sent = calls(gw, uncertain, "add_customer_note")
        check(
            "11 a write whose answer never came fails the run at once with the reason, and is sent once",
            failed.get("status") == "failed" and "may have" in str(failed.get("error")) and len(sent) == 1,
            {"status": failed.get("status"), "error": failed.get("error"), "calls": len(sent)},
        )
        check(
            "11 Executions shows that call as failed, never as ok",
            [c.get("status") for c in sent] in (["failed"], ["error"]),
            [c.get("status") for c in sent],
        )

        # 12. tools-service stops; a run's read meets the outage, and tools-service starts again within the backoff.
        tools_on.close()
        with worker("two"):
            outage = start(api, "outage", {"customerId": "CUS-1001"})
            time.sleep(3)
            down = run_of(api, outage).get("status")
            gw = stack.enter_context(tools(settings))
            done = until(ended(api, outage), 120) or {}
        tries = [s for s in run_of(api, outage).get("steps", []) if s.get("nodeId") == "lookup"]
        check(
            "12 a run meeting a tools-service outage waits and finishes once it is back",
            down in ("queued", "running") and done.get("outcome") == "found",
            {"while_down": down, "status": done.get("status"), "outcome": done.get("outcome"), "lookup": tries[:2]},
        )

        # 13. A worker that dies on the lookup every time: 7 workers in turn; the 8th leaves the run, and the reconciler
        # marks it Stuck. Retry carries it on and the note it wrote first is not written again.
        stuck_id = start(api, "stuck", {"customerId": "CUS-1001", "text": f"stuck {RUN}"})
        dying = {"OPS_ENGINE_FAULT_KILL_AFTER_NODE": "lookup", "OPS_ENGINE_FAULT_IGNORE_RECORDED": "1"}
        codes = []
        for i in range(7):
            with worker(f"dying-{i}", dying) as doomed:
                codes.append(until(doomed.poll, timeout=90))
        with worker("marking", {"OPS_ENGINE_RECONCILE_SECONDS": "2"}):
            stuck = until(ended(api, stuck_id, "stuck"), 60) or {}
            check(
                "13 a run whose worker dies on it every time is marked Stuck with the reason and is not taken again",
                stuck.get("status") == "stuck"
                and re.search(r"stopped 7 times (after|while running) lookup", str(stuck.get("error"))) is not None,
                {"status": stuck.get("status"), "error": stuck.get("error"), "codes": codes},
            )
            retried = api.post(f"/v1/runs/{stuck_id}/retry", headers=OPS)
            finished = until(ended(api, stuck_id), 90) or {}
        check(
            "13 Retry carries the Stuck run on to its end, and the outside system has its note once",
            retried.status_code == 200
            and finished.get("outcome") == "found"
            and notes_held(run_of(api, stuck_id), f"stuck {RUN}") == 1,
            {
                "retry": retried.status_code,
                "outcome": finished.get("outcome"),
                "notes": notes_held(run_of(api, stuck_id), f"stuck {RUN}"),
            },
        )

        # 14. A run waiting on a person, then 200 newer runs: Human Tasks still lists the first.
        with worker("tasks"):
            oldest = start(api, "tasks", {"customerId": "CUS-1001"})
            until(ended(api, oldest, "waiting"), 60)
        for _ in range(200):
            start(api, "tasks", {"customerId": "CUS-1001"})
        tasks = (
            data(api.get("/reviews", params={"pageSize": 100, "workflowId": FLOWS["tasks"]["id"]}, headers=MAYA)) or []
        )
        listed = [
            t for t in (tasks.get("data") if isinstance(tasks, dict) else tasks) or [] if oldest in str(t.get("id"))
        ]
        check("14 Human Tasks lists a waiting run older than the newest 200", bool(listed), {"oldest": oldest})

        # 15. Two emails; the first one's run fails to start on every read, so after 3 it is set aside with its reason
        # and the second starts its run. Run again starts the first, and its kept copy is gone after.
        connected = api.post(
            "/v1/channels/mailboxes",
            json={
                "name": f"Intake {RUN}",
                "address": ADDRESS,
                "provider": "imap",
                "imapHost": IMAP_HOST,
                "imapPort": 143,
                "imapTls": False,
                "passwordSecret": MAIL_SECRET,
            },
            headers=OPS,
        )
        mail_live = publish(api, MAIL_FLOW)
        listen = {"OPS_FILES_URL": files_url, "OPS_EMAIL_POLL_SECONDS": "1", "OPS_EMAIL_FAULT_FAIL_SUBJECT": BROKEN}
        with worker("mail", listen):
            time.sleep(31)  # the first read takes the mailbox's cursor; agents-service keeps tool lists for 30 s
            send_mail(f"Garnishment notice {BROKEN}")
            send_mail(f"Garnishment notice {RUN} readable")

            def emails() -> list[dict[str, Any]]:
                rows = (data(api.get("/v1/activity", params={"kind": "email", "pageSize": 50}, headers=OPS)) or {}).get(
                    "data"
                ) or []
                return [r for r in rows if RUN in str(r.get("title"))]

            def both() -> list[dict[str, Any]] | None:
                rows = emails()
                return rows if {"set_aside", "started"} <= {r.get("outcome") for r in rows} else None

            rows = until(both, 120) or emails()
        outcomes = sorted(
            f"{r.get('outcome')}:{'broken' if BROKEN in str(r.get('title')) else 'readable'}" for r in rows
        )
        check(
            "15 an email whose run fails to start 3 times is set aside, and the email after it starts its run",
            connected.status_code == 201
            and mail_live == "approved"
            and [o for o in outcomes if o.endswith(":broken")] == ["set_aside:broken"]
            and str(next((r for r in rows if r.get("outcome") == "set_aside"), {}).get("detail")).startswith(
                "Failed to start 3 times: "
            )
            and "started:readable" in outcomes,
            outcomes,
        )
        aside = next((r for r in rows if r.get("outcome") == "set_aside"), {})
        event = str((aside.get("ref") or {}).get("id"))
        again = api.post(f"/v1/runs/set-aside-emails/{event}/run", headers=OPS)
        twice = api.post(f"/v1/runs/set-aside-emails/{event}/run", headers=OPS)
        check(
            "15 Run again starts the set-aside email's run once, and its kept copy is gone after",
            again.status_code == 202 and twice.status_code == 404,
            {"again": again.status_code, "twice": twice.status_code, "body": again.text[:200]},
        )
        tools_on.close()
    finish()


if __name__ == "__main__":
    main()
