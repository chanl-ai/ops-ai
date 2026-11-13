# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-619 A new team's assistant answers from its knowledge and files, api layer:
docs/usecases/agents-service/a-new-team-s-assistant-answers.md.

Own services on a fresh database: platform-service (its relay delivering to this run's tools and agents), tools-service,
agents-service on the scripted model, kb-service with files-service and documents-service. A workspace admin makes a
team through platform-service; nothing seeds it. Its built-in apps and its Ops Assistant arrive through the
team.created event before anyone opens the team, and its assistant then searches the team's knowledge base and reads
its file through the tool gateway. No real model is called."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx
from steps import required
from usecase_harness import (
    AGENTS_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    kb,
    platform,
    signed_in,
    sse,
    tools,
    until,
)

ANSWER = "A cardholder has 120 days from the statement date to file a chargeback."
BUILT_IN = ("builtin:document-types", "builtin:files", "builtin:knowledge", "builtin:mailboxes")
NOTE = "Claims desk handover: call back Mrs Okoye about claim CLM-4410 before Friday."


def upload(files_url: str, team: str, name: str, body: bytes, *, mime: str, purpose: str) -> str:
    with httpx.Client(base_url=files_url, headers={"X-Team-Id": team}, timeout=60) as f:
        meta = {"name": name, "size": len(body), "mime": mime, "purpose": purpose}
        ticket = data(f.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
        f.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
        return str(data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def say(api: httpx.Client, team: str, thread: str, text: str) -> list[dict[str, Any]]:
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": text},
        headers={"X-Team-Id": team, "Accept": "text/event-stream"},
        timeout=120,
    )
    return sse(res.text) if res.status_code == 200 else [{"type": "error", "status": res.status_code, "text": res.text}]


def ended(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e["call"] for e in events if e.get("type") == "tool_end" and e["call"].get("name") == name]


def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="uc619-") as tmp,
        kb(Path(tmp) / "files", documents_env={"OPS_LOG_LEVEL": "info"}) as knowledge,
        tools(
            {
                "OPS_KB_URL": str(knowledge.base_url).rstrip("/"),
                "OPS_FILES_URL": knowledge.files_url,
                "OPS_DOCUMENTS_URL": knowledge.documents_url,
            }
        ) as gw,
        agents(gateway_url=str(gw.base_url).rstrip("/"), kb_url=str(knowledge.base_url).rstrip("/")) as api,
        platform(env={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as (people, _),
    ):
        # 1. A workspace admin makes a team; nothing else is done in it.
        # Wanjiru Kamau, the dev seed's workspace admin.
        owner = bearer(signed_in(people, "w.kamau@harborpine.example"))
        made = people.post(
            "/v1/settings/teams", json={"name": "Claims desk", "admin": "p.shah@harborpine.example"}, headers=owner
        )
        team = str((data(made) or {}).get("id") or "team_missing") if made.status_code == 201 else "team_missing"
        check("1 the workspace admin makes the Claims desk team (201)", made.status_code == 201, made.text[:200])
        on = {"X-Team-Id": team}

        # 2. Before anyone opens it, the team has its built-in apps and its Ops Assistant, from team.created.
        def provisioned() -> tuple[list[str], str] | None:
            # A built-in app has its own menu, not a card on the Apps grid (2026-11-01); its page answers.
            pages = {a: gw.get(f"/v1/apps/{a}", headers=on) for a in BUILT_IN}
            built = sorted(a for a, r in pages.items() if r.status_code == 200 and (data(r) or {}).get("tools"))
            default = (data(api.get("/v1/chat/default-agent", headers=on)) or {}).get("agentId")
            return (built, str(default)) if len(built) == 4 and default else None

        got = until(provisioned, timeout=60) or ([], "")
        check(
            "2 the new team has its four built-in apps and its Ops Assistant as its default, from the event alone",
            got[0] == ["builtin:document-types", "builtin:files", "builtin:knowledge", "builtin:mailboxes"]
            and got[1] == f"ag_ops_{team}",
            got,
        )

        # 3. The team's knowledge base and its file, put there by a person of the team.
        with httpx.Client(base_url=str(knowledge.base_url), headers=on, timeout=120) as k:
            base = data(
                k.post("/v1/knowledge-bases", json={"name": "Card claims", "owner": "j.richardson@harborpine.example"})
            )
            source = data(k.post("/v1/sources", json={"type": "file", "name": "Claims rules", "kbIds": [base["id"]]}))
            doc = upload(
                knowledge.files_url, team, "chargebacks.md", f"# Chargebacks\n\n## Time limits\n\n{ANSWER}\n".encode(),
                mime="text/markdown", purpose="knowledge_source",
            )  # fmt: skip
            k.post(f"/v1/sources/{source['id']}/files", json={"fileIds": [doc]})
            synced = data(k.post(f"/v1/sources/{source['id']}/sync")) or {}
        upload(knowledge.files_url, team, "handover.txt", NOTE.encode(), mime="text/plain", purpose="case_attachment")
        check(
            "3 the team's knowledge base holds the rules",
            int((synced.get("counts") or {}).get("upserted") or 0) >= 1,
            synced,
        )

        # 4. The assistant answers from the knowledge base through search_knowledge.
        thread = required(api.post("/chat/threads", json={"kbIds": []}, headers=on), "/chat/threads")
        searched = say(
            api, team, str(thread.get("id")), 'call search_knowledge {"query": "How long to file a chargeback?"}'
        )
        found = ended(searched, "search_knowledge")
        check(
            "4 the team's assistant searches its knowledge base through the gateway and gets the rule",
            thread.get("agentId") == f"ag_ops_{team}" and bool(found) and ANSWER in json.dumps(found[0].get("output")),
            {"agent": thread.get("agentId"), "calls": found[:1], "events": [e.get("type") for e in searched][-6:]},
        )

        # 5. It reads the team's file through read_file.
        read = say(api, team, str(thread.get("id")), 'call read_file {"file": "handover.txt"}')
        text = ended(read, "read_file")
        check(
            "5 the assistant reads the team's file through the gateway",
            bool(text) and NOTE in json.dumps(text[0].get("output")),
            {"calls": text[:1], "events": [e.get("type") for e in read][-6:]},
        )
    finish()


if __name__ == "__main__":
    main()
