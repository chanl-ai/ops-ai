"""The mode switch of the main-chain use cases (uc-752 to uc-756): MODE=mock (default) runs on the scripted model, the
fixture knowledge source and a mock upstream; MODE=real runs on a real model alias, a website knowledge source and the
Salesforce test org. Real mode needs APPROVED_REAL_CALLS=<n> with n at most 40: the runner keeps model keys out of a
script's environment without it. A real check loosens the answer's wording only; the citation, the tool call, the
approval, the call log row and team isolation are checked the same in both modes."""

from __future__ import annotations

import os
import sys

MODE = os.environ.get("MODE", "mock")
REAL = MODE == "real"
REAL_CAP = 40


def real_calls_approved() -> int:
    """The number of real model calls this run may make, or exit with a FAIL when real mode was asked for without one."""
    try:
        n = int(os.environ.get("APPROVED_REAL_CALLS", "0"))
    except ValueError:
        n = 0
    if not 0 < n <= REAL_CAP:
        print(f"FAIL real mode needs APPROVED_REAL_CALLS between 1 and {REAL_CAP}: got {n}")
        sys.exit(1)
    return n


def says(text: str, mock_words: str, real_words: tuple[str, ...]) -> bool:
    """The answer's wording: exact in mock mode (the scripted model), any of the key words in real mode."""
    return mock_words in text if not REAL else any(w.lower() in text.lower() for w in real_words)


if MODE not in ("mock", "real"):
    print(f"FAIL MODE must be mock or real: got {MODE}")
    sys.exit(1)


# ---- the mock upstream and its tool module (mock mode of uc-753, uc-754) ----

import time  # noqa: E402
from typing import Any  # noqa: E402

from fake_bank_https import HOST  # noqa: E402
from usecase_harness import approve_tool_review, check, data  # noqa: E402

SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
TEAM = {"X-Team-Id": "team_ops"}
MAYA = {"X-Dev-User": "Maya Okafor"}
ACCOUNT = "CHQ-2219"


def publish_bank_module(gw: Any, run: int, *, approval: bool, team: dict[str, str] | None = None) -> tuple[str, str, str]:
    """A tool module with a read (an account's balance) and a write (a hold on it) on the mock upstream, reviewed and
    published. `approval` turns the write's own approval switch on, one approver. Returns (module id, read, write)."""
    headers = team or {}
    read, write = f"get_account_{run}", f"freeze_account_{run}"
    made = data(
        gw.post(
            "/v1/tool-modules/blank",
            json={"displayName": f"Accounts {run}", "name": f"accounts-{run}", "type": "http"},
            headers=headers,
        )
    )
    mid = str(made["id"])
    specs = [(read, "read", "GET", "accountId", "Read an account"), (write, "write", "POST", "accountId", "Freeze an account")]
    ops: list[dict[str, Any]] = []
    for name, access, method, _, text in specs:
        suffix = "/holds" if access == "write" else ""
        added = gw.post(
            f"/v1/tool-modules/{mid}/operations",
            json={"name": name, "description": text, "access": access, "method": method, "url": f"https://{HOST}/v1/accounts/{{accountId}}{suffix}"},
            headers=headers,
        )
        ops = data(added)["operations"]
    if approval:
        op_id = next(o["id"] for o in ops if o["name"] == write)
        patched = gw.patch(f"/v1/tool-modules/{mid}/operations/{op_id}", json={"approvers": 1, "requiresApproval": True}, headers=headers)
        check("setup: the write's approval switch is on with one approver", patched.status_code == 200, patched.text[:200])
    data(gw.post(f"/v1/tool-modules/{mid}/reviews", json={"note": "main chains"}, headers=headers))
    approve_tool_review(gw, mid, SECURITY)
    return mid, read, write


def holds(bank: Any) -> list[dict[str, Any]]:
    return [r for r in bank.received if r["method"] == "POST" and r["path"] == f"/v1/accounts/{ACCOUNT}/holds"]


def agent_with(api: Any, run: int, tools: list[str]) -> str:
    """An agent holding `tools`, published. agents-service keeps each tenant's tool list for 30 seconds, so the call waits."""
    time.sleep(31)
    agent = data(api.post("/v1/agents", json={"name": f"Account desk {run}", "role": "Reads and freezes accounts"}, headers=TEAM))
    granted = data(api.patch(f"/v1/agents/{agent['id']}", json={"toolIds": tools}, headers=TEAM))
    api.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": granted["version"], "note": "main chains"}, headers=TEAM)
    return str(agent["id"])
