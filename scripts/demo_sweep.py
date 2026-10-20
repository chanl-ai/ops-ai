"""Every demo scenario on the shared stack, through the public API, one PASS or FAIL line each (`make demo-sweep`).

  a. chat: Advisor's Helper loads its skill and answers from its knowledge base with a citation (seed-walk a)
  b. guardrail: a savings question is answered and a shares question is blocked (seed-walk b)
  c. tools: the advisor finds a customer by name and reads their accounts from the fake bank
  d. write approval: Wire Fraud Sentinel's wire hold waits for a person, who approves it, and the hold is placed
  e. workflow: a v2 run goes through the queue to its end (seed-walk c)
  f. workflow as a tool: the advisor starts the customer summary workflow and answers with its outcome
  g. mailbox: an emailed levy notice becomes cases, Human Tasks and a reply (make demo-mailbox)

Runs on whatever models the stack routes to: real OpenAI on the shared stack after `make up`. Each sweep makes about a
dozen model calls. Exit status is the number of failed scenarios.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_mailbox
import seed_walk

ADVISOR, FRAUD = "ag_advisor", "ag_fraud"
MAYA = "m.okafor@northfieldbank.com"
# Two approvers: Operations' approver, then Fraud's admin (the hold's reviewers are Fraud Operations).
APPROVERS = (MAYA, "o.haddad@northfieldbank.com")


_seed_result = seed_walk.result


def _result(name: str, ok: bool, evidence: Any) -> None:
    # seed-walk letters its v2 run "c"; in this sweep it is scenario e.
    _seed_result("e." + name[2:] if name.startswith("c. a v2") else name, ok, evidence)


seed_walk.result = _result


def tool_ends(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last result of each tool the turn called, by tool name."""
    return {e["call"]["name"]: e["call"] for e in events if e.get("type") == "tool_end" and e.get("call")}


def customer_by_name(api: httpx.Client) -> None:
    _, message, events = seed_walk.chat(api, ADVISOR, "What does Priya Natarajan have with us?")
    calls = tool_ends(events)
    read = calls.get("list_accounts", {})
    answer = str(message.get("content") or "")
    seed_walk.result(
        "c. the advisor finds a customer by name and reads their accounts from the bank",
        read.get("status") == "success" and ("CHQ-" in answer or "SAV-" in answer or "account" in answer.lower()),
        {"tools": {k: v.get("status") for k, v in calls.items()}, "answer": answer[:400]},
    )


def wire_hold_approval(api: httpx.Client) -> None:
    ask = "Wire W-88213 for $48,500 went to a payee added today. Put a 24 hour hold on it."
    tid, message, events = seed_walk.chat(api, FRAUD, ask)
    widgets = [e["widget"] for e in events if e.get("type") == "widget" and e["widget"].get("kind") == "approval"]
    if not widgets:
        no_card = {"answer": message.get("content")}
        seed_walk.result("d. a wire hold waits for a person, who approves it", False, no_card)
        return
    card = widgets[0]
    url = f"/chat/threads/{tid}/messages/{message.get('id')}/widgets/{card['id']}/actions"
    decided: list[int] = []
    # The hold's policy asks for two approvers, each re-authenticated as the console's step-up dialog does.
    for email in APPROVERS:
        person = demo_mailbox.sign_in(email)
        person["X-Team-Id"] = api.headers.get("X-Team-Id", "team_ops")
        action: dict[str, Any] = {"type": "approve"}
        if card.get("stepUp"):
            stepped = httpx.post(
                f"{seed_walk.PLATFORM}/v1/auth/step-up",
                json={"password": seed_walk.PASSWORD},
                headers={"Authorization": person["Authorization"]},
                timeout=20,
            )
            action["stepUpToken"] = seed_walk.data(stepped)["token"]
        res = api.post(url, json=action, headers=person, timeout=180)
        decided.append(res.status_code)
        if res.status_code >= 300 or (res.json().get("data") or {}).get("state") != "awaiting_second":
            break
    thread = seed_walk.data(api.get(f"/chat/threads/{tid}"))
    replies = [m for m in thread.get("messages", []) if m.get("role") == "assistant"]
    after = str(replies[-1].get("content") or "") if replies else ""
    seed_walk.result(
        "d. a wire hold waits for a person, who approves it, and the hold is placed",
        all(c < 300 for c in decided) and len(replies) >= 2 and "hold" in after.lower(),
        {"card": card.get("title"), "decided": decided, "after": after[:300]},
    )


def workflow_as_tool(api: httpx.Client) -> None:
    _, message, events = seed_walk.chat(api, ADVISOR, "Run the customer summary workflow for Priya Natarajan.")
    ran = tool_ends(events).get("workflow__customer_summary", {})
    output = ran.get("output") or {}
    answer = str(message.get("content") or "")
    seed_walk.result(
        "f. the advisor starts the customer summary workflow and answers with its outcome",
        ran.get("status") == "success" and "Priya" in answer,
        {"run": output.get("runId") if isinstance(output, dict) else None, "answer": answer[:300]},
    )


def main() -> int:
    api = httpx.Client(base_url=seed_walk.AGENTS, headers=seed_walk.headers(), timeout=60)
    seed_walk.skill_and_citation(api)
    seed_walk.blocked_topic(api)
    customer_by_name(api)
    wire_hold_approval(api)
    seed_walk.v2_run(api)
    workflow_as_tool(api)
    print("g. the levy mailbox:", flush=True)
    mailbox_failed = demo_mailbox.main()
    seed_walk.result("g. an emailed levy notice becomes cases, Human Tasks and a reply", mailbox_failed == 0, {})
    return len(seed_walk.failed)


if __name__ == "__main__":
    sys.exit(main())
