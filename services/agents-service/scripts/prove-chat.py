"""End-to-end proof of the chat API against a running Runtime (default http://127.0.0.1:8700).

Lists agents, asks a policy question and prints the streamed text and citations, asks for a wire hold and prints the
approval widget, approves it (first without a step-up token to show the refusal), and prints the continuation the
Runtime stored on the thread.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8700"
HEADERS = {"X-Team-Id": "team_all"}


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def data(res: httpx.Response) -> Any:
    body = res.json()
    if not body.get("success"):
        raise SystemExit(f"{res.request.method} {res.request.url.path} -> {res.status_code} {body}")
    return body["data"]


def stream(client: httpx.Client, thread_id: str, content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    out(f"\n> {content}")
    with client.stream(
        "POST",
        f"/chat/threads/{thread_id}/messages",
        json={"content": content},
        headers={"Accept": "text/event-stream"},
    ) as res:
        res.raise_for_status()
        buf = ""
        for chunk in res.iter_text():
            buf += chunk
            *frames, buf = buf.split("\n\n")
            for frame in frames:
                payload = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
                if not payload:
                    continue
                event = json.loads(payload)
                events.append(event)
                kind = event["type"]
                if kind == "text":
                    sys.stdout.write(event["delta"])
                    sys.stdout.flush()
                elif kind == "status":
                    out(f"[status {event['phase']}]")
                elif kind in ("tool_start", "tool_end"):
                    c = event["call"]
                    gate = f" gated by {c['gated']['reviewers']}" if c.get("gated") else ""
                    out(f"\n[{kind} {c['name']} {c['status']} input={json.dumps(c['input'])}{gate}]")
                elif kind == "widget":
                    w = event["widget"]
                    state, fields = w.get("state", "-"), json.dumps(w.get("fields"))
                    out(f"\n[widget {w['kind']} '{w['title']}' state={state} fields={fields}]")
                elif kind == "citations":
                    out("\n[citations]")
                    for c in event["citations"]:
                        out(f"  [{c['n']}] {c['title']} — {c['section']} ({c['version']})")
                elif kind == "done":
                    out(f"\n[done message={event['message']['id']} model={event['message'].get('model')}]")
                elif kind == "error":
                    out(f"\n[error {event['message']}]")
    return events


def main() -> None:
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=180) as client:
        agents = data(client.get("/chat/agents"))
        out("Agents:")
        for a in agents:
            out(f"  {a['id']}  {a['name']} — {a['role']} (v{a['version']}, {a['model']}, kbs {a['defaultKbIds']})")
        fraud = next(a for a in agents if a["id"] == "ag_fraud")
        thread = data(client.post("/chat/threads", json={"agentId": fraud["id"], "kbIds": fraud["defaultKbIds"]}))
        out(f"\nThread {thread['id']} with {thread['agentName']} on {thread['kbNames']}")

        stream(client, thread["id"], "What is the daily wire limit for a personal account?")
        events = stream(client, thread["id"], "Place a 24-hour hold on wire W-88213, the payee was added this morning.")
        mid = next(e["messageId"] for e in events if e["type"] == "start")
        widget = next(
            (e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None
        )
        if widget is None:
            raise SystemExit("The write tool did not produce an approval widget.")
        url = f"/chat/threads/{thread['id']}/messages/{mid}/widgets/{widget['id']}/actions"

        refused = client.post(url, json={"type": "approve"})
        out(f"\nApprove without step-up -> {refused.status_code} {refused.json()['error']['message']}")
        decided = data(client.post(url, json={"type": "approve", "stepUpToken": "stepup_prove_chat"}))
        out(f"Approve with step-up    -> state={decided['state']} decidedBy={decided['decidedBy']}")

        final = data(client.get(f"/chat/threads/{thread['id']}"))
        cont = final["messages"][-1]
        out(f"\nContinuation from GET /chat/threads/{thread['id']} ({len(final['messages'])} messages):")
        for call in cont.get("toolCalls", []):
            out(f"  tool {call['name']} {call['status']} output={json.dumps(call['output'])}")
        out(f"  assistant ({cont.get('model')}): {cont['content']}")


if __name__ == "__main__":
    main()
