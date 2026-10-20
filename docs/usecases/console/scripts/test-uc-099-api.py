"""uc-099 a viewer sees the team's records read-only, api layer (the server half, c-115):
docs/usecases/console/viewer-sees-read-only-pages.md. platform-service signs the seeded people in; agents-service and
kb-service verify its tokens. James (builder on team_ops) makes one of each record; Ravi (viewer) and Maya (reviewer)
then send every write the console's builder pages send, with the bodies they send, straight to the services, and each
must answer 403 `role_required`. James's own writes are the control that the bodies and routes are right."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, data, finish, kb, platform

PASSWORD = "northfield-demo"
JAMES = "j.richardson@northfieldbank.com"
RAVI = "r.menon@northfieldbank.com"
MAYA = "m.okafor@northfieldbank.com"

RULE = {"name": "No tax advice 099", "topics": ["tax advice"], "message": "I can't give tax advice."}
SKILL = {
    "name": "Address change 099",
    "useWhen": "The customer asks to change their postal address.",
    "instructions": "Confirm the customer, then record the new address.",
    "ownerTeam": "Retail",
}
DEFINITION = {
    "schemaVersion": 2,
    "id": "uc099_intake",
    "name": "Intake 099",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Start", "parameters": {}},
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "done"}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}
SOURCE = {"type": "file", "name": "Branch PDFs 099", "collection": "Branch", "fileIds": ["file_1"]}


def sign_in(api: httpx.Client, email: str) -> dict[str, str]:
    r = api.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
    if r.status_code != 200:
        raise SystemExit(f"setup: sign-in as {email} answered {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {data(r)['token']}", "X-Team-Id": "team_ops"}


def made(r: httpx.Response, what: str) -> Any:
    """James's setup write: anything but 2xx stops the run, so a refusal later is never read off dead setup."""
    if not r.is_success:
        raise SystemExit(f"setup: {what} as James answered {r.status_code} {r.text[:300]}")
    return data(r) if r.content else None


with platform() as (api, _), tempfile.TemporaryDirectory(prefix="usecase-kb-") as files:
    # kb-service and agents-service verify platform-service's tokens, as the console's stack does under AUTH=platform.
    os.environ |= {
        "OPS_AUTH_MODE": "platform",
        "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    }
    with kb(Path(files)) as know, agents(kb_url=str(know.base_url).rstrip("/")) as svc:
        james, ravi, maya = sign_in(api, JAMES), sign_in(api, RAVI), sign_in(api, MAYA)
        me = data(api.get("/v1/me", headers=ravi))
        roles = {t["id"]: t["role"] for t in me.get("teams") or []}
        check("Ravi is a viewer on team_ops", roles.get("team_ops") == "viewer", me)

        agent = made(
            svc.post("/v1/agents", json={"name": "Payee checker 099", "role": "Checks payees"}, headers=james),
            "create an agent",
        )
        flow = made(
            svc.post("/v1/workflows", json={"name": "Payee check 099", "template": "blank"}, headers=james),
            "create a workflow",
        )
        graph = made(svc.get(f"/v1/workflows/{flow['id']}", headers=james), "read the workflow")["draft"]["graph"]
        rule = made(svc.post("/v1/guardrails", json=RULE, headers=james), "create a guardrail")
        skill = made(svc.post("/v1/skills", json=SKILL, headers=james), "create a skill")
        made(svc.post("/v1/workflows/definitions", json={"definition": DEFINITION}, headers=james), "save a definition")
        base = made(
            know.post("/v1/knowledge-bases", json={"name": "Branch manual 099", "owner": JAMES}, headers=james),
            "create a knowledge base",
        )
        made(know.post("/v1/sources", json=SOURCE, headers=james), "create a source")

        writes: list[tuple[str, httpx.Client, str, str, dict[str, Any] | None]] = [
            ("create an agent", svc, "POST", "/v1/agents", {"name": "Ravi's agent", "role": "Anything"}),
            ("edit an agent", svc, "PATCH", f"/v1/agents/{agent['id']}", {"role": "Changed"}),
            (
                "ask to publish an agent",
                svc,
                "POST",
                f"/v1/agents/{agent['id']}/publish-requests",
                {"version": 1, "note": ""},
            ),
            ("pause an agent", svc, "POST", f"/v1/agents/{agent['id']}/paused", {"paused": True}),
            ("delete an agent", svc, "DELETE", f"/v1/agents/{agent['id']}", None),
            ("create a workflow", svc, "POST", "/v1/workflows", {"name": "Ravi's workflow", "template": "blank"}),
            ("edit a workflow", svc, "PATCH", f"/v1/workflows/{flow['id']}", {"description": "Changed"}),
            ("save a workflow draft", svc, "PUT", f"/v1/workflows/{flow['id']}/draft", {"graph": graph}),
            ("pause a workflow", svc, "POST", f"/v1/workflows/{flow['id']}/status", {"status": "paused"}),
            ("delete a workflow", svc, "DELETE", f"/v1/workflows/{flow['id']}", None),
            ("save a workflow definition", svc, "POST", "/v1/workflows/definitions", {"definition": DEFINITION}),
            ("ask to publish a definition", svc, "POST", "/v1/workflows/definitions/uc099_intake/publish-requests", {}),
            ("delete a definition", svc, "DELETE", "/v1/workflows/definitions/uc099_intake", None),
            ("create a guardrail", svc, "POST", "/v1/guardrails", {**RULE, "name": "Ravi's rule"}),
            ("edit a guardrail", svc, "PATCH", f"/v1/guardrails/{rule['id']}", {"topics": ["tax"]}),
            ("deprecate a guardrail", svc, "POST", f"/v1/guardrails/{rule['id']}/status", {"status": "deprecated"}),
            ("create a skill", svc, "POST", "/v1/skills", {**SKILL, "name": "Ravi's skill"}),
            ("save a skill draft", svc, "PUT", f"/v1/skills/{skill['id']}/draft", {"note": "", "baseVersion": 1}),
            ("create a knowledge base", know, "POST", "/v1/knowledge-bases", {"name": "Ravi's base", "owner": RAVI}),
            ("create a source", know, "POST", "/v1/sources", {**SOURCE, "name": "Ravi's source"}),
        ]
        for who, headers in (("Ravi (viewer)", ravi), ("Maya (reviewer)", maya)):
            wrong = []
            for what, client, method, path, body in writes:
                r = client.request(method, path, json=body, headers=headers)
                code = (r.json().get("error") or {}).get("code") if r.content else None
                if r.status_code != 403 or code != "role_required":
                    wrong.append(f"{what}: {r.status_code} {code or r.text[:120]}")
            check(f"{who} gets 403 role_required on all {len(writes)} writes", not wrong, wrong)

        # The control after the refusals: James's edits to the same records go through.
        check(
            "James edits the agent",
            svc.patch(f"/v1/agents/{agent['id']}", json={"role": "Changed"}, headers=james).status_code == 200,
        )
        check(
            "James saves the workflow draft",
            svc.put(f"/v1/workflows/{flow['id']}/draft", json={"graph": graph}, headers=james).status_code == 200,
        )
        check(
            "James edits the guardrail",
            svc.patch(f"/v1/guardrails/{rule['id']}", json={"topics": ["tax"]}, headers=james).status_code == 200,
        )
        check(
            "James renames the knowledge base",
            know.patch(
                f"/v1/knowledge-bases/{base['id']}", json={"name": "Branch manual 099b"}, headers=james
            ).status_code
            == 200,
        )

finish()
