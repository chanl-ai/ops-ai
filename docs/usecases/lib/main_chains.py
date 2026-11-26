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

from fake_bank_https import HOST, fake_bank  # noqa: E402
from usecase_harness import approve_tool_review, check, data, save_agent  # noqa: E402

SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
TEAM = {"X-Team-Id": "team_ops"}
MAYA = {"X-Dev-User": "Maya Okafor"}
ACCOUNT = "CHQ-2219"


def publish_bank_module(
    gw: Any, run: int, *, approval: bool, team: dict[str, str] | None = None, security: dict[str, str] | None = None
) -> tuple[str, str, str]:
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
    if security is None:
        approve_tool_review(gw, mid, SECURITY)
    else:
        # Platform sign-in: the owner reads its own module, Security decides the review in agents-service.
        import httpx
        from usecase_harness import AGENTS_PORT

        shown = data(gw.get(f"/v1/tool-modules/{mid}", headers=headers))
        waiting = next(v for v in shown["versions"] if v["status"] == "in_review")
        with httpx.Client(base_url=f"http://127.0.0.1:{AGENTS_PORT}", timeout=30) as reviews:
            decided = reviews.post(f"/v1/publish-requests/{waiting['reviewId']}/decision", json={"decision": "approved"}, headers=security)
        check(f"the review of {mid} is approved (200)", decided.status_code == 200, decided.text[:300])
    return mid, read, write


def holds(bank: Any) -> list[dict[str, Any]]:
    return [r for r in bank.received if r["method"] == "POST" and r["path"] == f"/v1/accounts/{ACCOUNT}/holds"]


def agent_with(api: Any, run: int, tools: list[str], headers: dict[str, str] | None = None) -> str:
    """An agent holding `tools`, published. agents-service keeps each tenant's tool list for 30 seconds, so the call waits.
    `headers` act as a signed-in person (platform sign-in); the default is the dev team header."""
    as_who = headers or TEAM
    time.sleep(31)
    agent = data(api.post("/v1/agents", json={"name": f"Account desk {run}", "role": "Reads and freezes accounts"}, headers=as_who))
    granted = data(save_agent(api, agent["id"], {"toolIds": tools}, headers=as_who))
    api.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": granted["version"], "note": "main chains"}, headers=as_who)
    return str(agent["id"])


from collections.abc import Generator  # noqa: E402
from contextlib import ExitStack, contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402


@contextmanager
def bank_stack(*, worker: str | None = None) -> Generator[SimpleNamespace]:
    """platform-service with the dev seed's people, tools-service and agents-service both verifying their tokens, and the
    mock upstream: the stack the sdk and cli layers of uc-753 sign in to. Yields `bank`, `gw` (tools), `api` (agents),
    `accounts` (platform) and `who`, the headers of each seeded role. Writes need platform-service (approval rules are
    read from it), so every layer of a write case runs on this stack or the UI runner's. `worker` names a workflow worker
    to start on the same stack, with a knowledge service seeded with the fixture passages for its knowledge steps."""
    from apps_walk import AUTH
    from usecase_harness import AGENTS_PORT as agents_port
    from usecase_harness import TOOLS_PORT as tools_port
    from usecase_harness import agents, as_role, bearer, platform, signed_in, tools

    with fake_bank() as bank, platform() as (accounts, _):
        # Team writes need approval only once the admin turns the policy on (off by default). The change refuses tokens
        # issued before it, so every person signs in after it.
        admin = bearer(signed_in(accounts, "w.kamau@harborpine.example"), "team_ops")
        on = accounts.put("/v1/policies/toolWritesNeedApproval", json={"value": True}, headers=admin)
        check("setup: the admin turns write approvals on for the team", on.status_code == 200, on.text[:200])
        # The two-person rule is opt-in: the use cases on this stack prove a writer cannot decide their own request.
        rule = accounts.put("/v1/policies/requesterMayDecide", json={"value": False}, headers=admin)
        check("setup: the admin turns the two-person rule on", rule.status_code == 200, rule.text[:200])
        who = {role: as_role(accounts, role) for role in ("builder", "approver", "security")}
        team_settings = {**bank.settings, **AUTH, "OPS_AGENTS_URL": f"http://127.0.0.1:{agents_port}"}
        with ExitStack() as extra:
            kb_url: str | None = None
            if worker:
                import tempfile
                from pathlib import Path

                from usecase_harness import kb, seed_fixture_knowledge

                files = extra.enter_context(tempfile.TemporaryDirectory(prefix="usecase-kb-"))
                kb_client = extra.enter_context(kb(Path(files)))
                seed_fixture_knowledge(str(kb_client.base_url), kb_client.files_url)
                kb_url = str(kb_client.base_url).rstrip("/")
            api = extra.enter_context(agents(gateway_url=f"http://127.0.0.1:{tools_port}", env=AUTH, kb_url=kb_url))
            gw = extra.enter_context(tools(settings=team_settings))
            if worker:
                from usecase_harness import engine_worker

                env = {"OPS_GATEWAY_URL": f"http://127.0.0.1:{tools_port}", "OPS_KB_URL": str(kb_url), **AUTH}
                extra.enter_context(engine_worker(worker, env))
            for path, value in (("hosts", HOST), ("ranges", bank.range)):
                gw.post(f"/v1/egress/{path}", json={"value": value, "note": "main chains mock upstream"}, headers=who["security"])
            yield SimpleNamespace(bank=bank, gw=gw, api=api, accounts=accounts, who=who)
