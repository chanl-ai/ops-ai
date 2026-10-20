"""Which writes wait for approval is declared once per tool, and fails closed (c-219), by failure mode: a write that
declares nothing, so its approval depends on a default somewhere; a write other than open_case declared to run at once
without anyone deciding it; a team's toolWritesNeedApproval read for the wrong team; and a policy that cannot be read
letting a write through unapproved. platform-service is a fake HTTP endpoint here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import PLATFORM_TOOLS
from ops_tools.registry import WORKFLOW_TOOLS

from .service_clients import claims, fake_service

ROOT = Path(__file__).resolve().parents[3]
MODULE_SEEDS = [
    ROOT / "services/tools-service/seed/tool_modules.json",
    ROOT / "services/tools-service/tests/fixtures/tool_modules.json",
]
CATALOGS = [
    ROOT / "services/agents-service/seed/tools.json",
    ROOT / "services/agents-service/tests/fixtures/seed/tools.json",
]
# The writes that run without approval, each decided by a person (owner via orch, 2026-10-18): open_case changes only
# the team's own case list; log_activity is an internal note. book_appointment books with the bank, so it waits.
AT_ONCE = {"open_case", "log_activity"}


def _declared() -> dict[str, list[Any]]:
    """Every write any seed or declaration holds, with what it says about approval: `missing` when it says nothing."""
    found: dict[str, list[Any]] = {}
    for path in MODULE_SEEDS:
        seed: dict[str, Any] = json.loads(path.read_text())
        tools: dict[str, dict[str, Any]] = {t["name"]: t for t in seed["tools"]}
        for module in seed["modules"]:
            for op in module["operations"]:
                base: dict[str, Any] = tools.get(op["name"]) or op.get("tool") or {}
                if base.get("access") == "write":
                    found.setdefault(op["name"], []).append(op.get("requiresApproval", "missing"))
    for path in CATALOGS:
        for tool in json.loads(path.read_text()):
            if tool["access"] == "write":
                found.setdefault(tool["name"], []).append(tool.get("requires_approval", "missing"))
    for tool in PLATFORM_TOOLS:
        if tool["access"] == "write":
            found.setdefault(tool["name"], []).append(tool.get("requires_approval", "missing"))
    for name, (access, waits) in WORKFLOW_TOOLS.items():
        if access == "write":
            found.setdefault(name, []).append(waits)
    return found


def test_every_write_declares_whether_it_waits_and_only_the_decided_ones_run_at_once() -> None:
    declared = _declared()
    assert {"open_case", "send_reply", "place_hold"} <= set(declared), sorted(declared)
    implicit = sorted(n for n, says in declared.items() if "missing" in says)
    assert implicit == [], f"writes that declare no approval: {implicit}"
    at_once = sorted(n for n, says in declared.items() if False in says)
    assert at_once == sorted(AT_ONCE), f"writes declared to run at once without a decision: {at_once}"


def _platform(stored: dict[str, Any]) -> WriteApprovals:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/policies/toolWritesNeedApproval" or claims(request)["tenant_id"] != "t_a":
            return httpx.Response(404)
        return httpx.Response(200, json={"success": True, "data": {"key": "toolWritesNeedApproval", "value": stored}})

    return WriteApprovals(fake_service(answer, "platform", ["settings:view"]))


async def test_the_policy_is_read_for_the_calling_team_and_a_failed_read_has_every_write_wait() -> None:
    policy = _platform({"team_ops": True})
    assert await policy.all_writes("t_a", "team_ops") is True
    assert await policy.all_writes("t_a", "team_fraud") is False, "a team that set nothing follows each write's flag"
    assert await policy.all_writes("t_b", "team_fraud") is True, "a policy that cannot be read has every write wait"
