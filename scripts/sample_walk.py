"""Walks the sample team end to end through the public API (`make demo-walk`, c-542): the install, a chat that loads a
skill and cites knowledge, a blocked topic, bank reads, a write a person approves, then a levy notice emailed to the
team's mailbox through to the second reply in the sender's inbox.

    make sample-team && make demo-walk
    uv run python scripts/sample_walk.py [--name NAME] [--origin URL] [--admin-env FILE]

Signs in as the sample team's people (scripts/sample-team/sample-team.json, their password in the admin env file that
`make sample-team` wrote). Every email has its own Message-ID and subject, so the walk can run again and never reads a
message an earlier run sent. Turns run on the aliases `make sample-team` points at the fake model, whose committed rules
(services/models-service/seed/demo-fake-openai) answer each step. One PASS or FAIL line per step; the exit status is
the number of FAIL lines.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import httpx
from sample_team import (
    MANIFEST,
    ROOT,
    Refused,
    Session,
    admin_env,
    data,
    decide,
    items,
    named,
    service_urls,
    sign_in,
    until,
)

NOTICE = ROOT / "services" / "agents-service" / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf"
THANKS = "We received your notice and are working on it."
WAIT_S = float(os.environ.get("DEMO_WAIT_SECONDS", "180"))
# The turns the fake model's committed rules answer for the sample team's agents.
SKILLED = "What evidence does a duplicate charge dispute need?"
BLOCKED = "Should the customer buy shares in Northline Electronics with the refund?"
BANK_READ = (
    "Can you pull up Jordan Whitfield's accounts? He is disputing a 482.10 CAD charge from Northline Electronics that "
    "never arrived."
)
HOLD = "Place a hold of 50.00 CAD on Marcus Bell's chequing account CHQ-2219 for the restraining notice."

FAILED: list[str] = []


def step(ok: bool, name: str, evidence: Any = "") -> bool:
    if not ok:
        FAILED.append(name)
    shown = evidence if isinstance(evidence, str) else json.dumps(evidence, default=str)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {shown[:400]}", flush=True)
    return ok


def frames(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


def chat(who: Session, agent_id: str, question: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """One turn in a new conversation: the thread id, the final message (done or error frame) and every frame."""
    api = who("agents")
    tid = str(data(api.post("/chat/threads", json={"agentId": agent_id, "kbIds": []}))["id"])
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": question},
        headers={"Accept": "text/event-stream"},
        timeout=180,
    )
    events = frames(res.text)
    end = next((e for e in reversed(events) if e.get("type") in ("done", "error")), {})
    message = dict(end.get("message") or end.get("partial") or {})
    if end.get("type") == "error":
        message |= {"error": end.get("message"), "errorCode": end.get("code")}
    return tid, message, events


def tool_ends(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last result of each tool the turn called, by tool name."""
    return {e["call"]["name"]: e["call"] for e in events if e.get("type") == "tool_end" and e.get("call")}


class Walk:
    def __init__(self, a: argparse.Namespace) -> None:
        self.spec = json.loads(MANIFEST.read_text())
        if a.name:
            named(self.spec, a.name)
        self.team_name = a.name or self.spec["team"]["name"]
        env = admin_env(a.admin_env)
        self.urls = service_urls(a.origin)
        admin = sign_in(self.urls, env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"])
        teams = items(data(admin("platform").get("/v1/settings/teams", params={"search": self.team_name})))
        team = next((t for t in teams if t["name"].lower() == self.team_name.lower()), None)
        if team is None:
            raise SystemExit(f"demo-walk: no team {self.team_name!r}; run make sample-team first")
        self.team = str(team["id"])
        self.admin = sign_in(self.urls, admin.email, admin.password, self.team)
        self.people = {
            p["key"]: sign_in(self.urls, p["email"], env["OPS_DEMO_PASSWORD"], self.team) for p in self.spec["people"]
        }
        self.agents: dict[str, str] = {}

    def install(self) -> None:
        lead = self.people["lead"]
        members = [
            m for m in items(data(self.admin("platform").get("/v1/settings/members"))) if m["status"] == "active"
        ]
        wanted = {p["email"].lower() for p in self.spec["people"]}
        people = wanted & {m["email"].lower() for m in members}
        listed = items(data(lead("agents").get("/v1/agents", params={"pageSize": 100})))
        names = {a["name"]: str(a["id"]) for a in listed if a.get("teamId") == self.team}
        self.agents = {a["key"]: names[a["name"]] for a in self.spec["agents"] if a["name"] in names}
        rows = items(data(lead("agents").get("/v1/workflows/definitions", params={"pageSize": 100})))
        live = {str(w.get("workflowId")) for w in rows if w.get("status") == "live"}
        ids = [w.get("id") or w["file"].removesuffix(".json") for w in self.spec["workflows"]]
        workflows = [w for w in ids if any(x == w or x.endswith(f"_{w}") for x in live)]
        step(
            len(people) == len(wanted) and len(self.agents) == len(self.spec["agents"]) and len(workflows) == len(ids),
            f"team: {self.team_name}, {len(people)} people, {len(self.agents)} agents, {len(workflows)} workflows",
            {"missingWorkflows": sorted(set(ids) - set(workflows))} if len(workflows) != len(ids) else self.team,
        )

    def chat_skill(self) -> None:
        tid, m, _ = chat(self.people["lead"], self.agents["dispute"], SKILLED)
        loaded = [f"{s['name']} v{s['version']}" for s in m.get("skills") or []]
        cites = [str(c.get("title")) for c in m.get("citations") or []]
        step(
            bool(loaded) and bool(cites) and not m.get("error"),
            "chat: the dispute agent loads its skill and cites a knowledge base",
            {"thread": tid, "skills": loaded, "citations": cites, "error": m.get("error")},
        )

    def guardrail(self) -> None:
        tid, m, _ = chat(self.people["lead"], self.agents["dispute"], BLOCKED)
        hit = m.get("guardrail") or {}
        step(
            hit.get("when") == "before" and bool(m.get("content")),
            "guardrail: a shares question is blocked",
            {"thread": tid, "guardrail": hit, "reply": str(m.get("content") or "")[:160]},
        )

    def tools(self) -> None:
        tid, m, events = chat(self.people["lead"], self.agents["dispute"], BANK_READ)
        calls = tool_ends(events)
        ok = all(calls.get(t, {}).get("status") == "success" for t in ("search_customers", "list_accounts"))
        step(
            ok and "CHQ-1003" in str(m.get("content") or ""),
            "tools: customer found, accounts read from the fake bank",
            {"thread": tid, "tools": {k: v.get("status") for k, v in calls.items()}, "error": m.get("error")},
        )

    def write_approval(self) -> None:
        lead, approver = self.people["lead"], self.people["approver"]
        tid, m, events = chat(lead, self.agents["levy"], HOLD)
        cards = [e["widget"] for e in events if e.get("type") == "widget" and e["widget"].get("kind") == "approval"]
        if not step(bool(cards), "write approval: the hold waits for a person", {"thread": tid, "reply": m}):
            return
        card = cards[0]
        action: dict[str, Any] = {"type": "approve"}
        if card.get("stepUp"):
            action["stepUpToken"] = data(
                approver("platform").post("/v1/auth/step-up", json={"password": approver.password})
            )["token"]
        url = f"/chat/threads/{tid}/messages/{m.get('id')}/widgets/{card['id']}/actions"
        decided = approver("agents").post(url, json=action, timeout=180)
        thread = data(lead("agents").get(f"/chat/threads/{tid}"))
        replies = [x for x in thread.get("messages", []) if x.get("role") == "assistant"]
        after = str(replies[-1].get("content") or "") if replies else ""
        step(
            decided.status_code < 300 and "HLD-" in after,
            "write approval: the approver approves and the hold is placed",
            {"decided": decided.status_code, "after": after[:200] or decided.text[:200]},
        )

    def email(self, a: argparse.Namespace) -> None:
        lead, approver = self.people["lead"], self.people["approver"]
        api = lead("agents")
        mailbox = self.spec["mailbox"]["address"]
        intake_id = next(w for w in self.spec["workflows"] if w["key"] == "levy_mail")["id"]
        intake_id = next((x for x in self._workflow_ids() if x == intake_id or x.endswith(f"_{intake_id}")), intake_id)
        suffix = uuid.uuid4().hex[:8]
        sender, subject = f"clerk+{suffix}@court.example", f"Notice of garnishment {suffix}"
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, mailbox, subject
        msg["Message-ID"] = make_msgid(idstring=suffix, domain="court.example")
        msg.set_content("Please find the notice of garnishment attached. Confirm to the registry within five days.")
        msg.add_attachment(NOTICE.read_bytes(), maintype="application", subtype="pdf", filename=f"notice-{suffix}.pdf")
        host, _, port = a.send_smtp.rpartition(":")
        with smtplib.SMTP(host, int(port), timeout=20) as smtp:
            smtp.send_message(msg)

        def run(run_id: str) -> dict[str, Any]:
            return dict(data(api.get(f"/v1/runs/{run_id}")))

        def out_of(r: dict[str, Any], node: str) -> Any:
            return next((s.get("output") for s in r.get("steps", []) if s.get("nodeId") == node), None)

        def intake_run() -> dict[str, Any] | None:
            rows = data(api.get("/v1/runs", params={"workflowId": intake_id}))["data"]
            return next((run(r["id"]) for r in rows[:20] if suffix in json.dumps(run(r["id"]).get("input"))), None)

        intake = until(intake_run, WAIT_S)
        if not step(intake is not None, "email started the intake", f"{intake_id} {(intake or {}).get('id')}"):
            return
        assert intake is not None
        started = until(lambda: (out_of(run(intake["id"]), "each") or {}).get("runs"), WAIT_S)
        doc_id = str(started[0]["runId"]) if started else ""
        if not doc_id:
            step(False, "sender thanked with no approval", "the intake started no document run")
            return
        ack = until(lambda: out_of(run(doc_id), "ack"), WAIT_S) or {}
        step(ack.get("status") == "sent", "sender thanked with no approval", ack)
        read = until(lambda: out_of(run(doc_id), "read"), WAIT_S) or {}
        records = read.get("records") or []
        step(bool(records), f"notice read: {[r['values'].get('name') for r in records]}", doc_id)
        people = until(lambda: (out_of(run(doc_id), "each") or {}).get("runs"), WAIT_S) or []

        def at(run_id: str, nodes: set[str]) -> dict[str, Any] | None:
            got = run(run_id)
            node = (got.get("waiting") or {}).get("node")
            return got if node in nodes or got["status"] in ("succeeded", "failed", "cancelled") else None

        cases, holds, waits, approved = [], [], [], []
        for p in people:
            rid = str(p["runId"])
            got = until(lambda rid=rid: at(rid, {"review", "ask_none", "ask_exempt"}), WAIT_S) or {}
            cases.append(((out_of(got, "case") or out_of(got, "case_none")) or {}).get("caseId"))
            if (got.get("waiting") or {}).get("node") == "review":
                calc = out_of(got, "calc") or {}
                try:
                    decide(approver, rid, {"decision": "hold", "reason": "The hold matches the notice"})
                except Refused as e:
                    holds.append(f"{p['label']}: {e}")
                    continue
                got = until(lambda rid=rid: at(rid, {"ask_held"}), WAIT_S) or {}
                hold = out_of(got, "hold") or {}
                holds.append(f"{p['label']}: {calc.get('holdAmount')} -> {hold.get('id')}")
            node = (got.get("waiting") or {}).get("node")
            waits.append(node in ("ask_held", "ask_none", "ask_exempt"))
            if waits[-1]:
                decide(approver, rid, {"decision": "approved", "reason": "The reply is right"})
                done = until(lambda rid=rid: at(rid, set()), WAIT_S) or {}
                approved.append(done.get("status") == "succeeded")
        step(len(people) == len(records) > 0 and all(cases), "case per debtor", cases)
        step(
            any("HLD-" in h for h in holds) and not any("Refused" in h for h in holds),
            "hold worked out by code and placed",
            holds,
        )
        step(
            bool(waits) and all(waits) and all(approved) and len(approved) == len(waits),
            "reply waits for approval, then approved",
            {"waited": waits, "approved": approved},
        )
        found = until(lambda: self._inbox(a, sender, 1 + len(people)), WAIT_S) or []
        step(
            sum(THANKS in s for s in found) == 1 and len(found) == 1 + len(people),
            "second reply in the sender's inbox",
            found,
        )

    def _inbox(self, a: argparse.Namespace, sender: str, want: int) -> list[str] | None:
        r = httpx.get(f"{a.mailpit}/api/v1/search", params={"query": f'to:"{sender}"'}, timeout=30)
        got = [str(m.get("Snippet", "")) for m in r.json().get("messages", [])]
        return got if len(got) >= want else None

    def _workflow_ids(self) -> list[str]:
        rows = items(data(self.people["lead"]("agents").get("/v1/workflows/definitions", params={"pageSize": 100})))
        return [str(w.get("workflowId")) for w in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    console = f"http://localhost:{os.environ.get('OPS_CONSOLE_PORT', '3016')}"
    run_dir = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run")
    ap.add_argument("--origin", default=console)
    ap.add_argument("--admin-env", type=Path, default=run_dir / "dev-admin.env")
    ap.add_argument("--name", help="the team `make sample-team NAME=` installed")
    gm = f"{os.environ.get('OPS_GREENMAIL_HOST', '127.0.0.1')}:{os.environ.get('OPS_GREENMAIL_SMTP_PORT', '3025')}"
    mp = f"http://{os.environ.get('OPS_MAILPIT_HOST', '127.0.0.1')}:{os.environ.get('OPS_MAILPIT_HTTP_PORT', '8025')}"
    ap.add_argument("--send-smtp", default=gm, help=f"where the notice is emailed from (default GreenMail {gm})")
    ap.add_argument("--mailpit", default=mp, help=f"where sent replies are read (default Mailpit {mp})")
    a = ap.parse_args()
    walk = Walk(a)
    walk.install()
    for part in (walk.chat_skill, walk.guardrail, walk.tools, walk.write_approval):
        try:
            part()
        except (Refused, httpx.HTTPError, KeyError) as e:
            step(False, part.__name__, str(e))
    try:
        walk.email(a)
    except (Refused, httpx.HTTPError, KeyError, OSError) as e:
        step(False, "email", str(e))
    print(f"\n{len(FAILED)} failed", flush=True)
    return len(FAILED)


if __name__ == "__main__":
    sys.exit(main())
