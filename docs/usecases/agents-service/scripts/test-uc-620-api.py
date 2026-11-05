# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-620 any file a workflow or chat reads ends read or with a reason, api layer:
docs/usecases/agents-service/any-file-a-workflow-or-chat.md.

Own services, no real model: models-service on the fake OpenAI with the levy notice's extraction rule, kb-service's
files-service (scanning off) and documents-service with the demo's document types, both delivering their service
events to this run's agents-service, agents-service and a workflow worker. The event workflows are the ones
agents-service ships; the notice workflow is a team copy of the seeded mail_document whose cases step starts a
workflow of this script's, so no bank is needed."""

from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    LOG_DIR,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    fake_openai,
    finish,
    kb,
    models,
    pg_url,
    put_in_files,
    sse,
)

RULES = AGENTS_DIR.parent / "models-service" / "seed" / "demo-fake-openai"
NOTICE = (AGENTS_DIR / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf").read_bytes()
# An image-only scan with no text layer: documents-service reads no text from it without OCR.
SCAN = (AGENTS_DIR.parent / "documents-service/tests/fixtures/restraining/TEST010.pdf").read_bytes()
SEED = AGENTS_DIR / "seed" / "engine_workflows.json"
OPS = {"X-Team-Id": "team_ops"}
RUN = uuid.uuid4().hex[:6]
SETTLED = {"succeeded", "failed", "cancelled"}
FILE_INPUT = {"type": "object", "required": ["fileId"], "properties": {"fileId": {"type": "string", "format": "file"}}}


def body(res: httpx.Response) -> dict[str, Any]:
    try:
        got = res.json()
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def got(res: httpx.Response) -> Any:
    return body(res).get("data")


def code(res: httpx.Response) -> str | None:
    error = body(res).get("error")
    return str(error.get("code")) if isinstance(error, dict) else None


def said(res: httpx.Response) -> str:
    return f"{res.request.method} {res.request.url.path} answered {res.status_code}: {res.text[:300]}"


def until(what: Callable[[], Any], timeout: float = 120) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.5)
    return None


def story(name: str, steps: Callable[[], None]) -> None:
    """One story's steps; an exception is that story's FAIL line, so the next story still runs and says its own."""
    try:
        steps()
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e} | {traceback.format_exc(limit=2)[-300:]}")


def wanted(name: str) -> bool:
    """UC620_STORIES=S1,S2 runs only those stories; all by default."""
    picked = {s.strip() for s in os.environ.get("UC620_STORIES", "").split(",") if s.strip()}
    return not picked or name in picked


@contextmanager
def worker(files_url: str, models_url: str, documents_url: str) -> Generator[None]:
    env = _env() | {
        "OPS_DATABASE_URL": pg_url(),
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        "OPS_DOCUMENTS_URL": documents_url,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc620.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def publish(api: httpx.Client, definition: dict[str, Any]) -> str:
    saved = api.post("/v1/workflows/definitions", json={"definition": definition}, headers=OPS)
    if saved.status_code not in (200, 201):
        return said(saved)
    asked = api.post(f"/v1/workflows/definitions/{definition['id']}/publish-requests", json={}, headers=OPS)
    return str((got(asked) or {}).get("status") or said(asked))


def run_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return got(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}


def settled(api: httpx.Client, run_id: str, timeout: float = 180) -> dict[str, Any]:
    return until(lambda: (r := run_of(api, run_id)) and r.get("status") in SETTLED and r, timeout) or run_of(
        api, run_id
    )


def runs_of(api: httpx.Client, wid: str) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"workflowId": wid, "pageSize": 100}
    return (got(api.get("/v1/runs", params=params, headers=OPS)) or {}).get("data") or []


def end(nid: str, outcome: str) -> dict[str, Any]:
    return {"id": nid, "type": "ops.flow.end", "typeVersion": 1, "name": outcome, "parameters": {"outcome": outcome}}


def reader(wid: str) -> dict[str, Any]:
    """A builder's own workflow: a file in, Extract from file as a Levy notice, and no Save data on file step."""
    read = {
        "id": "read",
        "type": "ops.ai.extract",
        "typeVersion": 1,
        "name": "Read the notice",
        "parameters": {"file": "$.input.fileId", "documentType": {"id": "levy_notice", "version": 1}},
    }
    ports = ("ok", "review", "unreadable", "error")
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Read a notice",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {"inputSchema": FILE_INPUT}},
            read,
            *(end(p, p) for p in ports),
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}}]
        + [{"from": {"node": "read", "port": p}, "to": {"node": p, "port": "in"}} for p in ports],
    }


def any_workflow_read_shows_in_files(api: httpx.Client, files: httpx.Client, files_url: str) -> None:
    # 1. A builder's workflow with an Extract step and no Save data on file step reads a notice.
    wid = f"uc620_read_{RUN}"
    live = publish(api, reader(wid))
    fid = put_in_files(files_url, f"notice-{RUN}.pdf", NOTICE + f"\n% uc-620 {RUN}\n".encode(), headers=OPS)
    started = api.post("/v1/runs", json={"workflowId": wid, "mode": "live", "input": {"fileId": fid}}, headers=OPS)
    run = settled(api, str((got(started) or {}).get("runId")))
    data = until(lambda: (got(files.get(f"/v1/files/{fid}")) or {}).get("data"), 90) or {}
    check(
        "1 a builder's workflow whose Extract step has no Save data on file step reads a notice, and Files says it was "
        "read as Levy notice with its fields to check",
        live == "approved"
        and run.get("status") == "succeeded"
        and run.get("outcome") in ("ok", "review")
        and (data.get("typeId"), data.get("typeName")) == ("levy_notice", "Levy notice")
        and isinstance(data.get("fieldsToCheck"), int)
        and bool(data.get("extractionId")),
        {"publish": live, "start": said(started), "run": run.get("status"), "outcome": run.get("outcome"),
         "error": run.get("error"), "data": data},
    )  # fmt: skip

    # 2. The save is the read's own event workflow, not a step of the builder's workflow.
    saves = [r for r in runs_of(api, "extraction_read_save") if r.get("status") in SETTLED]
    check(
        "2 the read reported extraction.read, and the shipped extraction_read_save workflow saved it and ended saved",
        any(r.get("status") == "succeeded" and r.get("outcome") == "saved" for r in saves),
        [{k: r.get(k) for k in ("id", "status", "outcome")} for r in saves],
    )


def notice_flow(wid: str, cases: str) -> dict[str, Any]:
    """The seeded mail_document as a team copy a person can start, its cases step starting `cases`."""
    seed = next(w for w in json.loads(SEED.read_text()) if w["id"] == "mail_document")
    flow = copy.deepcopy({k: v for k, v in seed.items() if k != "teamId"}) | {"id": wid, "name": f"Notice {RUN}"}
    for node in flow["nodes"]:
        if node["type"] == "ops.trigger.request":
            node["parameters"].pop("onlyFromWorkflows", None)
        if node["id"] == "open":
            node["parameters"]["workflow"] = cases
    return flow


def case_flow(wid: str) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Open a case",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            end("done", "opened"),
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


def past_the_check(api: httpx.Client, run_id: str) -> dict[str, Any]:
    """The run once settled or waiting at the acknowledgement; a read waiting for a person's check is approved."""

    def moved() -> dict[str, Any] | None:
        run = run_of(api, run_id)
        if run.get("status") in SETTLED:
            return run
        if run.get("status") == "waiting":
            review = got(api.get(f"/reviews/{run_id}:check:1", headers=OPS))
            if review and review.get("status") in ("pending", "open"):
                api.post(f"/reviews/{run_id}:check:1/decision", json={"decision": "approved"}, headers=OPS)
                return None
            ack = got(api.get(f"/reviews/{run_id}:ack:1", headers=OPS))
            return run | {"ack": ack} if ack else None
        return None

    return until(moved, 180) or run_of(api, run_id)


def submit(api: httpx.Client, slug: str, token: str, values: dict[str, Any]) -> httpx.Response:
    up = api.post(
        f"/v1/forms/public/{slug}/files",
        params={"t": token, "name": "levy_notice.pdf"},
        content=NOTICE + f"\n% uc-620 form {uuid.uuid4().hex[:6]}\n".encode(),
        headers={"Content-Type": "application/pdf", "X-Forwarded-For": "198.51.100.20"},
    )
    sent = values | {"fileId": (got(up) or {}).get("fileId")}
    return api.post(
        f"/v1/forms/public/{slug}/submit",
        params={"t": token},
        json={"values": sent},
        headers={"X-Forwarded-For": "198.51.100.20"},
    )


def form_notice_finishes(api: httpx.Client) -> None:
    wid, cases = f"uc620_notice_{RUN}", f"uc620_case_{RUN}"
    live = {publish(api, case_flow(cases)), publish(api, notice_flow(wid, cases))}
    share = {"mode": "link", "expiresInDays": 30, "dailyCap": 50, "title": f"Send us a notice {RUN}"}
    form = got(api.post(f"/v1/workflows/{wid}/forms", json=share, headers=OPS)) or {}
    slug, token = str(form.get("slug")), str(form.get("token"))

    # 3. A notice sent through the form with the sender and no mailbox opens its cases and ends with no reply.
    sent = submit(api, slug, token, {"from": "registry@court.test"})
    first = runs_of(api, wid)
    run = past_the_check(api, str(first[0]["id"])) if first else {}
    output = run.get("output") or {}
    check(
        "3 a notice sent through the form with no mailbox opens its cases and ends at Nothing to reply to, saying why",
        live == {"approved"} and sent.status_code == 202 and run.get("status") == "succeeded"
        and run.get("outcome") == "cases_opened" and "no mailbox, sender or subject" in json.dumps(output),
        {"publish": live, "sent": said(sent), "run": run.get("status"), "outcome": run.get("outcome"),
         "error": run.get("error"), "output": output},
    )  # fmt: skip

    # 4. With a mailbox and no subject, the acknowledgement opens with the form's default subject instead of failing.
    sent = submit(api, slug, token, {"from": "registry@court.test", "mailbox": "levies@harborpine.test"})
    second = [r for r in runs_of(api, wid) if r["id"] != (first[0]["id"] if first else None)]
    run = past_the_check(api, str(second[0]["id"])) if second else {}
    ack = run.get("ack") or {}
    check(
        "4 a notice with a mailbox and no subject waits at the acknowledgement with the subject We received your "
        "document, instead of failing",
        sent.status_code == 202 and run.get("status") == "waiting"
        and "We received your document" in json.dumps(ack),
        {"sent": said(sent), "run": run.get("status"), "error": run.get("error"), "ack": json.dumps(ack)[:400]},
    )  # fmt: skip

    # 5. The API refuses a form start with a required field empty, as the console does, naming the field.
    blank = api.post(
        f"/v1/forms/public/{slug}/submit",
        params={"t": token},
        json={"values": {"mailbox": "levies@harborpine.test"}},
        headers={"X-Forwarded-For": "198.51.100.21"},
    )
    by_hand = api.post("/v1/runs/start", json={"workflowId": wid, "values": {"fileId": "fil_x"}}, headers=OPS)
    check(
        "5 the hosted form and Start run by API refuse a start with a required field empty, naming it",
        blank.status_code == 422 and code(blank) == "invalid_input" and "Notice file" in blank.text
        and "Sender's email" in blank.text
        and by_hand.status_code == 422 and code(by_hand) == "invalid_input" and "Sender's email" in by_hand.text,
        {"form": said(blank), "byHand": said(by_hand)},
    )  # fmt: skip


def attach(files: httpx.Client, name: str, body: bytes) -> dict[str, Any]:
    """The console's chat attach: an upload ticket for a chat attachment, the bytes, complete."""
    meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "chat_attachment"}
    ticket = got(files.post("/v1/files/uploads", json=meta)) or {}
    files.put(str(ticket.get("uploadUrl")), headers=ticket.get("headers") or {}, content=body)
    done = (got(files.post(f"/v1/files/uploads/{ticket.get('fileId')}/complete")) or {}).get("file") or {}
    return {"fileId": done.get("id"), "name": name, "size": len(body)}


def ask(api: httpx.Client, tid: str, question: str, attached: list[dict[str, Any]]) -> tuple[httpx.Response, Any]:
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": question, "attachments": attached},
        headers={**OPS, "Accept": "text/event-stream"},
        timeout=120,
    )
    done = next((e for e in sse(res.text) if e.get("type") == "done"), {}) if res.status_code == 200 else {}
    return res, done.get("message") or {}


def chat_reads_an_attached_pdf(api: httpx.Client, files: httpx.Client) -> None:
    # 6. A person attaches the notice in chat and asks about it; the agent answers from its text and cites it.
    notice = attach(files, f"notice-{RUN}.pdf", NOTICE + f"\n% uc-620 chat {RUN}\n".encode())
    # An agent of the team's own with no knowledge bases, so the answer can come only from the attachment.
    made = got(
        api.post("/v1/agents", json={"name": f"Notice Desk {RUN}", "role": "Answers about notices"}, headers=OPS)
    )
    aid, version = (made or {}).get("id"), (made or {}).get("version")
    api.post(f"/v1/agents/{aid}/publish-requests", json={"version": version, "note": "uc-620"}, headers=OPS)
    tid = str((got(api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=OPS)) or {}).get("id"))
    res, reply = ask(api, tid, "uc620 who is the first debtor in this notice?", [notice])
    cited = reply.get("citations") or [{}]
    check(
        "6 a PDF attached in chat is read for the agent, which answers from it on the fake model and cites the file",
        res.status_code == 200
        and "Marcus Bell" in str(reply.get("content"))
        and "3,250.00" in str(reply.get("content"))
        and (cited[0].get("documentId"), cited[0].get("page")) == (notice["fileId"], 1),
        {"file": notice, "status": res.status_code, "reply": str(reply.get("content"))[:300], "cited": cited[:1]},
    )  # fmt: skip

    # 7. Files lists it as a chat attachment; the person deletes it there, and the next turn says it is gone.
    listed = (got(files.get("/v1/files", params={"purpose": "chat_attachment", "pageSize": 100})) or {}).get("data")
    row = next((f for f in listed or [] if f.get("id") == notice["fileId"]), {})
    deleted = files.delete(f"/v1/files/{notice['fileId']}")
    res, reply = ask(api, tid, "uc620 what did I attach?", [])
    check(
        "7 Files lists the attached PDF as a chat attachment, the person can delete it, and the next turn tells the "
        "agent it is no longer in Files",
        row.get("purpose") == "chat_attachment"
        and deleted.status_code == 204
        and f"{notice['name']} ({notice['fileId']}): could not be read: it is no longer in Files"
        in str(reply.get("content")),
        {"row": {k: row.get(k) for k in ("id", "name", "purpose")}, "delete": said(deleted),
         "reply": str(reply.get("content"))[:300]},
    )  # fmt: skip

    # 8. A scan with no text layer is told plainly to the person and the agent, not answered as if read.
    scan = attach(files, f"scan-{RUN}.pdf", SCAN + f"\n% uc-620 scan {RUN}\n".encode())
    res, reply = ask(api, tid, "What does the scan say?", [scan])
    check(
        "8 a scan with no text says in the reply that it could not be read and why",
        res.status_code == 200
        and f"scan-{RUN}.pdf could not be read: it has no text to read" in str(reply.get("content")),
        {"file": scan, "status": res.status_code, "reply": str(reply.get("content"))[-300:]},
    )


def main() -> None:
    agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
    with (
        tempfile.TemporaryDirectory(prefix="uc620-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, document_types=True, agents_url=agents_url) as knowledge,
        agents(
            kb_url=str(knowledge.base_url).rstrip("/"),
            models_url=models_url,
            models_key="mk_dev_agents",
            env={"OPS_FILES_URL": knowledge.files_url, "OPS_DOCUMENTS_URL": knowledge.documents_url},
        ) as api,
        worker(knowledge.files_url, models_url, knowledge.documents_url),
        httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=60) as files,
    ):
        if wanted("S1"):
            story(
                "1 a workflow's read shows in Files",
                lambda: any_workflow_read_shows_in_files(api, files, knowledge.files_url),
            )
        if wanted("S2"):
            story("3 a notice from a form finishes", lambda: form_notice_finishes(api))
        if wanted("S3"):
            story("6 chat reads an attached PDF", lambda: chat_reads_an_attached_pdf(api, files))
    finish()


if __name__ == "__main__":
    main()
