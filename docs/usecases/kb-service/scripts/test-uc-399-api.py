# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-399 People and services read knowledge usage, refs, search and workflow refs on one route each, api layer:
docs/usecases/kb-service/people-and-services-read-knowledge-usage.md.

Own services in dev: kb-service with its files-service, and agents-service with its seeded agents and workflows.
People are dev callers naming their team; services sign their own tokens with the dev key (c-222)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from usecase_harness import (
    AGENTS_DIR,
    DB,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    data,
    finish,
    kb,
    service_headers,
)

OPS = {"X-Team-Id": "team_ops", "X-Dev-User": "j.richardson@harborpine.example"}
FRAUD = {"X-Team-Id": "team_fraud", "X-Dev-User": "o.haddad@harborpine.example"}
CARDS = {"X-Team-Id": "team_cards", "X-Dev-User": "j.richardson@harborpine.example"}


def ids(rows: Any) -> list[str]:
    return [str(r["id"]) for r in rows or []]


def svc(audience: str, service: str, scopes: list[str], team: str | None = None) -> dict[str, str]:
    return service_headers(audience, service=service, scopes=scopes, team=team)


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with (
        tempfile.TemporaryDirectory(prefix="uc399-") as tmp,
        kb(Path(tmp) / "files") as knowledge,
        agents(kb_url=str(knowledge.base_url).rstrip("/")) as api,
    ):
        usage = data(api.get("/v1/knowledge-usage", headers=OPS)) or []
        elsewhere = data(api.get("/v1/knowledge-usage", headers=FRAUD)) or []
        named = {r["kbId"]: ids(r["agents"]) for r in usage}
        counted = {r["kbId"]: (ids(r["agents"]), r["elsewhere"]) for r in elsewhere}
        cited = next((kb_id for kb_id, agents_of in named.items() if agents_of), None)
        as_kb = api.get("/v1/knowledge-usage", headers=svc("agents", "kb", ["agents:view"]))
        check(
            # Usage stays in one team (c-507): another team neither names nor counts a team's agents.
            "1 a person reads which of their team's agents cite each base; another team sees none of them",
            cited is not None
            and all(not agents_of and n == 0 for agents_of, n in counted.values())
            and as_kb.status_code == 200,
            {"named": named, "counted": counted, "service": as_kb.status_code},
        )

        bases = "/v1/knowledge-bases"
        mine = data(knowledge.post(bases, json={"name": "Ops desk", "owner": "j@x.com"}, headers=OPS))
        theirs = data(knowledge.post(bases, json={"name": "Fraud desk", "owner": "o@x.com"}, headers=FRAUD))
        refs = ids(data(knowledge.get(f"{bases}/refs", headers=OPS)))
        ask_mine = {"kbIds": [mine["id"]], "question": "opening hours"}
        ask_theirs = {"kbIds": [theirs["id"]], "question": "opening hours"}
        search_mine = knowledge.post(f"{bases}/search", json=ask_mine, headers=OPS)
        search_theirs = knowledge.post(f"{bases}/search", json=ask_theirs, headers=OPS)
        tenant_wide = ids(data(knowledge.get(f"{bases}/refs", headers=svc("kb", "agents", ["knowledge:view"]))))
        check(
            "2 a person lists and searches their team's bases, never another team's; a service lists the tenant's",
            mine["id"] in refs
            and theirs["id"] not in refs
            and search_mine.status_code == 200
            and search_theirs.status_code == 404
            and {mine["id"], theirs["id"]} <= set(tenant_wide),
            {"refs": refs, "mine": search_mine.status_code, "theirs": search_theirs.text[:200], "service": tenant_wide},
        )

        refused = {
            "usage": api.get("/v1/knowledge-usage", headers=svc("agents", "kb", [])),
            "refs": knowledge.get(f"{bases}/refs", headers=svc("kb", "agents", [])),
            "workflow refs": api.get("/v1/workflow-refs", headers=svc("agents", "tools", [])),
        }
        check(
            "3 a service without the route's scope is refused, naming the scope",
            all(r.status_code == 403 and r.json()["error"]["code"] == "scope_required" for r in refused.values()),
            {k: (r.status_code, r.text[:120]) for k, r in refused.items()},
        )

        body = {"name": "Cards intake uc399", "trigger": "manual"}
        created = data(api.post("/v1/workflows", json=body, headers=CARDS))
        ops_flows = data(api.get("/v1/workflow-refs", headers=OPS)) or []
        tools = api.get("/v1/workflow-refs", headers=svc("agents", "tools", ["workflows:view"]))
        everyone = data(tools) or []
        check(
            "4 a person reads their team's workflows; tools-service still reads every team's, with each owner",
            bool(ops_flows)
            and {w["teamId"] for w in ops_flows} == {"team_ops"}
            and created["id"] not in ids(ops_flows)
            and next((w["teamId"] for w in everyone if w["id"] == created["id"]), None) == "team_cards",
            {"ops": ids(ops_flows)[:5], "tools": tools.status_code},
        )

        gone = api.post(
            "/v1/publish-requests/imports", json={"id": "rev_1"}, headers=svc("agents", "tools", [], "team_ops")
        )
        check(
            "5 the old review import is gone",
            gone.status_code in (404, 405),
            {"status": gone.status_code, "body": gone.text[:200]},
        )
    finish()


if __name__ == "__main__":
    main()
