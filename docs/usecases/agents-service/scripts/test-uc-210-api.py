# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-210 a levy notice runs on the workflow runner from its mailbox, api layer:
docs/usecases/agents-service/levy-on-the-runner.md.

Own services, no real model: models-service on the fake OpenAI with the notice's extraction rule, kb-service's
files-service with scanning off, tools-service with the core fake bank on https (docs/usecases/lib/fake_bank_serve.py),
agents-service, and a workflow worker that reads a levy mailbox of this run's own on the stack's GreenMail over IMAP,
connected through the API like any team mailbox (c-229). The v2 levy_case and levy_intake definitions (the dev seed,
services/agents-service/seed/engine_workflows.json) are saved and published as the dev builder of team_ops, watching
that mailbox."""

from __future__ import annotations

import json
import os
import signal
import smtplib
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    DB,
    LOG_DIR,
    ROOT,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    approve_tool_review,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    tools,
)

RULES = AGENTS_DIR / "tests" / "fixtures" / "levy-extraction-fake-openai"
NOTICE: dict[str, Any] = json.loads((AGENTS_DIR / "tests" / "fixtures" / "mailbox" / "levy_notice.json").read_text())
SEED = {w["id"]: w for w in json.loads((AGENTS_DIR / "seed" / "engine_workflows.json").read_text())}
sys.path.insert(0, str(AGENTS_DIR / "scripts"))
from send_levy_email import message  # noqa: E402

RUN = uuid.uuid4().hex[:8]
MAILBOX = f"levy-{RUN}@northfield.example"
GREENMAIL_SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
GREENMAIL_IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))
IMAP_HOST, SECRET = "mail.northfield.test", "DEV_IMAP_PASSWORD"
OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@northfieldbank.com"}
SECURITY = {"X-Dev-User": "Nadia Petrov"}
BANK_KEY = {"X-Api-Key": "dev-bank-key"}
SETTLED = ("succeeded", "failed", "cancelled")


@contextmanager
def core_bank() -> Generator[dict[str, Any]]:
    """The core-banking fake on https as api.bank.test; yields what tools-service needs and the script's own URL."""
    env = _env() | {"OPS_FAKE_BANK_APP": "core"}
    argv = [
        "uv",
        "run",
        "--directory",
        str(AGENTS_DIR),
        "python",
        str(ROOT / "docs" / "usecases" / "lib" / "fake_bank_serve.py"),
    ]
    proc = subprocess.Popen(
        argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT / "docs" / "usecases" / "lib"
    )
    try:
        assert proc.stdout is not None
        found = json.loads(proc.stdout.readline())
        resolved = json.loads(found["settings"]["OPS_EGRESS_RESOLVE"])[found["host"]]
        yield found | {"url": f"https://{resolved}"}
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        proc.wait(10)


@contextmanager
def worker(files_url: str, models_url: str, documents_url: str) -> Generator[None]:
    """The workflow worker, reading the levy mailbox through tools-service and storing attachments in files-service."""
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env = _env() | {
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}",
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        # The Extract from file step reads through documents-service (c-256).
        "OPS_DOCUMENTS_URL": documents_url,
        "OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}",
        "OPS_ENGINE_POLL_SECONDS": "0.2",
        "OPS_EMAIL_POLL_SECONDS": "1",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc210.log").open("ab") as fh:
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


def bank_module(gw: httpx.Client) -> None:
    """The bank imported as a published module: reads from GET, place_hold approved by one person of team_ops."""
    source = {"kind": "openapi", "specUrl": "https://api.bank.test/openapi.json"}
    found = data(gw.post("/v1/tool-modules/discover", json=source))
    ops = [
        {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"} for o in found["operations"]
    ]
    body = {
        "name": "northfield-core-banking",
        "displayName": "Northfield Core Banking",
        "system": found["system"],
        "type": "openapi",
        "endpoint": found["endpoint"],
        "operations": ops,
        "source": source,
    }
    made = data(gw.post("/v1/tool-modules", json=body))
    hold = next(o for o in made["operations"] if o["name"] == "place_hold")
    gw.patch(
        f"/v1/tool-modules/{made['id']}/operations/{hold['id']}",
        json={"approvers": 1, "approverTeam": "team_ops", "stepUp": False},
    )
    data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-210"}))
    approve_tool_review(gw, made["id"], SECURITY)


def publish(api: httpx.Client, name: str) -> str:
    d = {k: v for k, v in SEED[name].items() if k != "teamId"}
    for n in d["nodes"]:
        if n["type"] == "ops.trigger.email":
            n["parameters"]["mailbox"] = MAILBOX
    saved = api.post("/v1/workflows/definitions", json={"definition": d}, headers=OPS)
    live = api.post(f"/v1/workflows/definitions/{name}/publish-requests", json={}, headers=OPS)
    return f"{saved.status_code}/{live.status_code}/{live.json().get('data', {}).get('status')}"


def runs(api: httpx.Client, workflow: str) -> list[dict[str, Any]]:
    return list(data(api.get("/v1/runs", params={"workflowId": workflow, "pageSize": 100}, headers=OPS))["data"])


def detail(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=OPS))


def until(fn: Any, seconds: float = 60) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if got := fn():
            return got
        time.sleep(0.5)
    return fn()


def settled(api: httpx.Client, run_id: str) -> dict[str, Any] | None:
    d = detail(api, run_id)
    return d if d["status"] in SETTLED else None


def waiting_again(api: httpx.Client, run_id: str) -> dict[str, Any] | None:
    d = detail(api, run_id)
    return d if d["status"] == "waiting" and (d["waiting"] or {}).get("iteration") == 2 else None


def three_cases(api: httpx.Client) -> list[dict[str, Any]] | None:
    rs = runs(api, "levy_case")
    return rs if len(rs) == 3 and all(r["status"] in ("waiting", *SETTLED) for r in rs) else None


def send(item: dict[str, Any]) -> None:
    """The notice emailed to this run's levy mailbox through GreenMail's SMTP."""
    with smtplib.SMTP("127.0.0.1", GREENMAIL_SMTP) as s:
        s.send_message(message(item, MAILBOX))


def private_address() -> str:
    """This machine's private address: tools-service reaches GreenMail as an outside host, there."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("10.255.255.255", 1))
    address = str(s.getsockname()[0])
    s.close()
    return address


def case_for(api: httpx.Client, name: str) -> dict[str, Any]:
    return next(r for r in runs(api, "levy_case") if r["input"]["record"]["name"] == name)


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with (
        tempfile.TemporaryDirectory(prefix="uc210-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        # kb's files-service is the one files-service: agents() would start a second on the same reserved port.
        kb(Path(tmp) / "files", models_url=models_url, document_types=True) as knowledge,
        agents(
            kb_url=str(knowledge.base_url).rstrip("/"),
            gateway_url=f"http://127.0.0.1:{TOOLS_PORT}",
            models_url=models_url,
            models_key="mk_dev_agents",
        ) as api,
        # After the services on reserved ports: the bank's own port is the OS's next free one.
        core_bank() as bank,
        tools(
            settings=bank["settings"]
            | {
                "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
                "OPS_EGRESS_RESOLVE": json.dumps(
                    json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"])
                    | {IMAP_HOST: f"{private_address()}:{GREENMAIL_IMAP}"}
                ),
            }
        ) as gw,
        httpx.Client(base_url=bank["url"], verify=False, headers=BANK_KEY, timeout=10) as bank_api,
    ):
        gw.post("/v1/egress/hosts", json={"value": bank["host"], "note": "uc-210 fake bank"})
        gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "uc-210 fake bank network"})
        gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"})
        gw.post("/v1/egress/hosts", json={"value": IMAP_HOST, "note": "uc-210 GreenMail"})
        gw.post("/v1/egress/ranges", json={"value": f"{private_address()}/32", "note": "uc-210 this machine"})
        gw.post("/v1/secrets", json={"name": SECRET, "value": "any", "teams": ["team_ops"]})
        bank_module(gw)
        form = {
            "name": f"Levy {RUN}",
            "address": MAILBOX,
            "provider": "imap",
            "imapHost": IMAP_HOST,
            "imapPort": 143,
            "imapTls": False,
            "passwordSecret": SECRET,
        }
        connected = api.post("/v1/channels/mailboxes", json=form, headers=OPS)
        assert connected.status_code == 201, connected.text[:300]
        published = [publish(api, "levy_case"), publish(api, "levy_intake")]
        check(
            "1 the levy case and intake are saved and published for team_ops",
            published == ["201/201/approved"] * 2,
            published,
        )
        with worker(knowledge.files_url, models_url, knowledge.documents_url):
            time.sleep(31)  # agents-service keeps each tenant's tool list (and its policies) for 30 seconds
            send(NOTICE)
            # The intake's own steps end once it has started the cases; it then waits on the ones a person decides.
            intake = until(lambda: [r for r in runs(api, "levy_intake") if r["outcome"] or r["status"] in SETTLED])
            cases = until(lambda: three_cases(api))
            names = sorted(c["input"]["record"]["name"] for c in cases or [])
            check(
                "2 the notice starts one intake, which reads three debtors and opens a case each",
                len(intake or []) == 1
                and intake[0]["outcome"] == "cases_opened"
                and names == ["Jordan Whitfield", "Marcus Bell", "Priya Natarajan"],
                {"intake": [(r["status"], r["outcome"], r["error"]) for r in intake or []], "cases": names},
            )
            jordan = case_for(api, "Jordan Whitfield")
            marcus, priya = case_for(api, "Marcus Bell"), case_for(api, "Priya Natarajan")
            check(
                "3 Marcus (name and address) and Priya (name and last four) wait for a review; "
                "Jordan, found by name alone, ends not_matched",
                marcus["status"] == "waiting"
                and priya["status"] == "waiting"
                and jordan["outcome"] == "not_matched"
                and [c["id"] for c in jordan["output"]["candidates"]] == ["CUS-1003"],
                {
                    "marcus": marcus["status"],
                    "priya": priya["status"],
                    "jordan": (jordan["status"], jordan["outcome"], jordan["output"]),
                },
            )

            over = api.post(
                f"/reviews/{marcus['id']}/decision", json={"decision": "hold", "amount": 9000}, headers=MAYA
            )
            back = until(lambda: waiting_again(api, marcus["id"]))
            hold_step = next((s for s in (back or {}).get("steps", []) if s["nodeId"] == "hold"), {})
            check(
                "4 a hold over the balance comes back from the bank as 422 and waits on the same review",
                over.status_code == 200 and back is not None and hold_step.get("port") == "error",
                {"decision": over.text[:300], "hold": hold_step},
            )
            held = api.post(
                f"/reviews/{marcus['id']}/decision", json={"decision": "hold", "amount": 1500}, headers=MAYA
            )
            done = until(lambda: settled(api, marcus["id"]))
            holds = bank_api.get("/accounts/CHQ-2219").json()
            check(
                "5 Maya holds 1500 instead: the case ends held, and the bank holds 1500 on CHQ-2219 once",
                held.status_code == 200
                and (done or {}).get("outcome") == "held"
                and [h["amount"] for h in holds.get("holds", [])] == [1500.0],
                {"decision": held.text[:200], "case": (done or {}).get("outcome"), "holds": holds.get("holds")},
            )
            flagged = api.post(f"/reviews/{priya['id']}/decision", json={"decision": "flag"}, headers=MAYA)
            ended = until(lambda: settled(api, priya["id"]))
            notes = bank_api.get("/customers/CUS-1002/notes").json()
            check(
                "6 Maya flags Priya: the case ends flagged and the bank holds the note",
                flagged.status_code == 200 and (ended or {}).get("outcome") == "flagged" and len(notes) == 1,
                {"decision": flagged.text[:200], "case": (ended or {}).get("outcome"), "notes": notes},
            )

            send(NOTICE)  # the same message again
            time.sleep(5)
            check(
                "7 the same notice delivered again starts no second intake and no second case",
                len(runs(api, "levy_intake")) == 1 and len(runs(api, "levy_case")) == 3,
                {"intakes": len(runs(api, "levy_intake")), "cases": len(runs(api, "levy_case"))},
            )
    finish()


if __name__ == "__main__":
    main()
