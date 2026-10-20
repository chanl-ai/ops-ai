"""Brings the imported bank module up to the fake bank's current OpenAPI document and sets the hold's approval
policy (c-057 T003): operations the document lists and the module lacks (search_customers, add_customer_note) are
imported with access preset from their method, `place_hold` is approved by one person of the approving team with no
self-approval, the staged changes are published as a version, and Security's review of it (a new write or a changed
policy is major) is approved in agents-service's Reviews through `--decide-as` (c-163), so the registry serves the new
operations.

    uv run python scripts/reimport_bank_module.py                      # dev auth: the fixed dev user
    uv run python scripts/reimport_bank_module.py --as j.richardson@northfieldbank.com \
        --decide-as n.petrov@northfieldbank.com --secrets-as s.adeyemi@northfieldbank.com

The fake bank must serve the new document (restart `python -m fake_bank` after changing it) and tools-service must
reach it (its OPS_EGRESS_* settings, docs/usecases/tools-service/import-tools.md).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import httpx

HOST = "api.bank.test"
HOLD = "place_hold"
# The levy demo's outside system: a webhook receiver on the same stand-in (fake_bank /webhooks), signed with a secret.
WEBHOOK = "notify_webhook"
# What an operation's input field may carry when it is written back (tools-service SchemaFieldIn).
FIELD_KEYS = ("name", "type", "required", "description", "format", "enum", "example", "default")
# Maya Okafor's team in platform-service's directory and the tools seed (services/tools-service/seed/tool_modules.json).
HOLD_TEAM = "team_ops"


def data(r: httpx.Response) -> Any:
    body = r.json()
    if r.status_code >= 400 or not body.get("success"):
        raise SystemExit(f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}")
    return body["data"]


def pending_review(module: dict[str, Any]) -> str | None:
    """The publish request of the module's version waiting for review, if one is."""
    versions: list[dict[str, Any]] = list(module.get("versions") or [])
    return next((str(v["reviewId"]) for v in versions if v["status"] == "in_review" and v.get("reviewId")), None)


async def decide_pending(
    approver: httpx.AsyncClient | None, api: httpx.AsyncClient, module_id: str, module: dict[str, Any]
) -> dict[str, Any]:
    """A version waiting for Security blocks every edit; with an approver's client (on agents-service) the pending
    review is approved in Reviews first, else the run stops and says so. Returns the module detail afterwards."""
    review = pending_review(module)
    if review is None:
        return module
    if approver is None:
        raise SystemExit(
            f"module {module_id} has review {review} waiting for Security; pass --decide-as <approver> to approve it"
        )
    data(await approver.post(f"/v1/publish-requests/{review}/decision", json={"decision": "approved"}))
    return data(await api.get(f"/v1/tool-modules/{module_id}"))


async def reimport(
    api: httpx.AsyncClient,
    module_id: str,
    *,
    host: str = HOST,
    hold_team: str = HOLD_TEAM,
    approver: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Imports every operation of the host's document the module lacks and sets the hold policy. A version left
    waiting for Security (an earlier run that stopped) is decided first through `approver`. Returns the module detail.
    Idempotent: a module already up to date gets its policy re-checked only."""
    source = {"kind": "openapi", "specUrl": f"https://{host}/openapi.json"}
    found = data(await api.post("/v1/tool-modules/discover", json=source))
    module = await decide_pending(approver, api, module_id, data(await api.get(f"/v1/tool-modules/{module_id}")))
    have = {o["name"] for o in module["operations"]}
    fresh = [o for o in found["operations"] if o["name"] not in have]
    # One at a time: an operation name is unique in the tenant, and a name another module already took is skipped
    # rather than stopping the reimport of the rest.
    for o in fresh:
        chosen = {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"}
        r = await api.post(
            f"/v1/tool-modules/{module_id}/operations/import", json={"source": source, "operations": [chosen]}
        )
        if r.status_code == 409:
            print(f"{o['name']}: skipped, {r.json()['error']['message']}")
            continue
        module = data(r)
    hold = next((o for o in module["operations"] if o["name"] == HOLD), None)
    if hold is None:
        raise SystemExit(f"{HOLD} is not in the module or the document; nothing to approve")
    # One approver from the team and a step-up although one person approves: a hold on funds. Whether the asker may
    # approve is the tenant's requesterMayDecide policy (c-186).
    wanted = {
        "approvers": 1,
        "approverTeam": hold_team,
        "requiresApproval": True,
        "stepUp": True,
    }
    if any(hold.get(k) != v for k, v in wanted.items()):
        module = data(await api.patch(f"/v1/tool-modules/{module_id}/operations/{hold['id']}", json=wanted))
    # The bank's document is the one copy of each operation's wording: an operation imported before its description, or
    # a field's, changed keeps the old text until it is copied over here (get_customer's id, 2026-10-18).
    documented: dict[str, dict[str, Any]] = {str(o["name"]): o for o in found["operations"]}
    for op in list(module["operations"]):
        doc = documented.get(str(op["name"]))
        if doc is None:
            continue
        doc_fields: list[dict[str, Any]] = list(doc.get("input") or [])
        said: dict[str, Any] = {str(f["name"]): f.get("description") for f in doc_fields}
        fields: list[dict[str, Any]] = list(op.get("input") or [])
        same_fields = all(said.get(str(f["name"])) == f.get("description") for f in fields)
        if doc.get("description") == op.get("description") and same_fields:
            continue
        kept: list[dict[str, Any]] = []
        for f in fields:
            merged: dict[str, Any] = {**f, "description": said.get(str(f["name"]), f.get("description"))}
            kept.append({k: v for k, v in merged.items() if k in FIELD_KEYS and v is not None})
        patch = {"description": doc.get("description"), "input": kept}
        module = data(await api.patch(f"/v1/tool-modules/{module_id}/operations/{op['id']}", json=patch))
    # Sending a case's extracted data on is a write that runs at once by default, after the workflow's own review; a
    # team whose toolWritesNeedApproval policy is on still has it wait.
    hook = next((o for o in module["operations"] if o["name"] == WEBHOOK), None)
    if hook is not None and hook.get("requiresApproval") is not False:
        module = data(
            await api.patch(f"/v1/tool-modules/{module_id}/operations/{hook['id']}", json={"requiresApproval": False})
        )
    # Staged changes serve nothing until a version is published; a major one (a new write, a changed policy) waits
    # for Security, and only its approval moves the served operations forward.
    if module.get("pendingChanges"):
        module = data(await api.post(f"/v1/tool-modules/{module_id}/versions", json={"note": "c-057 levy operations"}))
        module = await decide_pending(approver, api, module_id, module)
    return module


async def ensure_secret(api: httpx.AsyncClient, name: str, value: str) -> str:
    """The secret the bank module's X-Api-Key header reads ({{BANK_API_KEY}}); created when the tenant lacks it,
    left alone when it exists (its value never comes back, so it is not compared). Returns what was done."""
    r = await api.post("/v1/secrets", json={"name": name, "value": value})
    if r.status_code == 201:
        return "created"
    if r.status_code == 409:
        return "exists"
    raise SystemExit(f"POST /v1/secrets -> {r.status_code} {r.text[:200]}")


async def ensure_module(api: httpx.AsyncClient, host: str = HOST) -> tuple[str, bool]:
    """The module calling `host`, created from the host's OpenAPI document through tools-service's own discover and
    create routes when none does (a clean stack has none; it then goes through review like any import). Returns its
    id and whether it was created."""
    listed: dict[str, Any] = data(await api.get("/v1/tool-modules", params={"pageSize": 200}))
    if any(host in str(m.get("endpoint") or "") for m in listed["data"]):
        return await find_module(api, host), False
    source = {"kind": "openapi", "specUrl": f"https://{host}/openapi.json"}
    found = data(await api.post("/v1/tool-modules/discover", json=source))
    body = {
        "name": "northfield-core-banking",
        "displayName": "Northfield Core Banking",
        "system": found["system"],
        "type": "openapi",
        "endpoint": found["endpoint"],
        "operations": [
            {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"}
            for o in found["operations"]
        ],
        "source": source,
    }
    return str(data(await api.post("/v1/tool-modules", json=body))["id"]), True


async def find_module(api: httpx.AsyncClient, host: str) -> str:
    """The one module whose endpoint is on `host`. The list answers a page envelope: `data` holds the rows."""
    listed: dict[str, Any] = data(await api.get("/v1/tool-modules", params={"pageSize": 200}))
    rows: list[dict[str, Any]] = list(listed["data"])
    hits = [m for m in rows if host in str(m.get("endpoint") or "")]
    if len(hits) != 1:
        raise SystemExit(f"{len(hits)} modules call {host}; pass --module <id>: {[m['id'] for m in hits] or rows}")
    return str(hits[0]["id"])


def sign_in(platform: str, email: str, password: str) -> dict[str, str]:
    r = httpx.post(f"{platform}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"sign-in as {email} failed: {r.status_code} {r.text[:200]}")
    signed = r.json()["data"]
    # Secrets and modules are written as a team; each person acts in the team they hold a role in.
    team = next(iter(signed["principal"].get("roles") or {}), None)
    return {"Authorization": f"Bearer {signed['token']}"} | ({"X-Team-Id": team} if team else {})


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tools", default=f"http://127.0.0.1:{os.environ.get('OPS_TOOLS_PORT', '8720')}")
    ap.add_argument("--agents", default=f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}")
    ap.add_argument("--platform", default=f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}")
    ap.add_argument("--module", help="the module id; found by its endpoint host when left out")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--team", default=HOLD_TEAM, help="the team whose approver decides a hold")
    ap.add_argument("--as", dest="email", help="sign in through platform-service as this builder (platform auth)")
    ap.add_argument("--decide-as", help="sign in as this Security approver and approve the review")
    ap.add_argument(
        "--secrets-as",
        default="s.adeyemi@northfieldbank.com",
        help="sign in as this Security admin to create BANK_API_KEY (platform auth; only a Security admin may)",
    )
    ap.add_argument("--bank-key", default="dev-bank-key", help="BANK_API_KEY's value, set when the tenant lacks it")
    ap.add_argument(
        "--webhook-secret",
        default=os.environ.get("FAKE_BANK_WEBHOOK_SECRET", "dev-webhook-secret"),
        help="LEVY_WEBHOOK_SECRET's value (the receiver's X-Webhook-Secret), set when the tenant lacks it",
    )
    ap.add_argument("--password", default=os.environ.get("OPS_PLATFORM_DEMO_PASSWORD", "northfield-demo"))
    args = ap.parse_args()

    builder = sign_in(args.platform, args.email, args.password) if args.email else {}
    security = sign_in(args.platform, args.decide_as, args.password) if args.decide_as else None
    # Secrets are the Security team's admins' to change; under dev auth no one signs in and the dev caller may.
    keeper = sign_in(args.platform, args.secrets_as, args.password) if args.email else {}
    async with (
        httpx.AsyncClient(base_url=args.tools, headers=builder, timeout=60) as api,
        httpx.AsyncClient(base_url=args.agents, headers=security or {}, timeout=60) as approver,
        httpx.AsyncClient(base_url=args.tools, headers=keeper, timeout=60) as secrets,
    ):
        print(f"BANK_API_KEY: {await ensure_secret(secrets, 'BANK_API_KEY', args.bank_key)}")
        print(f"LEVY_WEBHOOK_SECRET: {await ensure_secret(secrets, 'LEVY_WEBHOOK_SECRET', args.webhook_secret)}")
        if args.module:
            module_id = args.module
        else:
            module_id, created = await ensure_module(api, args.host)
            if created:
                print(f"created module {module_id} from https://{args.host}/openapi.json")
        module = await reimport(
            api, module_id, host=args.host, hold_team=args.team, approver=approver if security else None
        )
        names = sorted(o["name"] for o in module["operations"])
        hold = next(o for o in module["operations"] if o["name"] == HOLD)
        print(f"module {module_id} ({module['displayName']}): {len(names)} operations: {', '.join(names)}")
        print(f"{HOLD}: approvers={hold['approvers']} team={hold['approverTeam']}")
        current = next(v for v in module["versions"] if v["version"] == module["version"])
        print(
            f"version {module['version']} {current['status']}; "
            f"pending changes {len(module.get('pendingChanges') or [])}; review waiting: {pending_review(module)}"
        )


if __name__ == "__main__":
    asyncio.run(main())
