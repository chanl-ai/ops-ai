"""Trying one tool from a skill path or a workflow step (`POST /v1/tool-modules/tries`), on the gateway's one dry-run
seam (`GatewayCalls.call(plan_only=True)`). A read runs for real, as the tool page's Real run does. A write always
comes back first as a plan, what it would send and to which system, and is sent only when the same values come back
with the plan's id: that is the person's yes, and it goes through every check a confirmed test run meets, so a team
that gives the write to a reviewer still refuses it. Nothing here stores a version, a run or a plan.

The account the builder picks decides the run: the app's test account runs a test run, any other account a live run on
that account, and no pick a test run, which takes the app's test account when it has one
(connections.records.account_for)."""

from __future__ import annotations

import hashlib
from typing import cast

from ops_policy import input_hash
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Json, JsonValue

from ..environments import LIVE, TEST
from ..executor import Trial
from ..store.connections import name_key, plugin_app
from ..store.modules import Module
from .schemas import ToolTryIn
from .service import (
    Caller,
    ModuleService,
    NotYetAvailable,
    _can,  # pyright: ignore[reportPrivateUsage]  # the service's one grid check
)


def plan_id(who: Caller, tool: str, args: Json, environment: str, accounts: dict[str, str]) -> str:
    """The id of one plan: the person, team, tool, values, run and account it was made for. Nothing is stored; a
    confirm recomputes it, so values changed after the plan was shown are refused, and it is the write's idempotency
    key, so a second confirm replays the first send."""
    sub = who.principal.sub if who.principal is not None else who.name
    parts = [who.tenant_id, who.team.id, sub, tool, input_hash(args), environment, input_hash(accounts)]
    return "plan_" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


async def _app_of(service: ModuleService, module: Module) -> str | None:
    """The app a module's calls sign in to: a plugin's by its plugin, any other by its connection's app."""
    template = str(module.get("template_id") or "")
    if template.startswith("plugin:"):
        return plugin_app(template.removeprefix("plugin:"))
    if service.auth is None or not module.get("connection_id"):
        return None
    conn = await service.auth.connections.get(str(module["tenant_id"]), str(module["connection_id"]))
    return conn.app_id if conn else None


async def _run_for(
    service: ModuleService, who: Caller, module: Module, accounts: dict[str, str]
) -> tuple[str, dict[str, str], str]:
    """The run and accounts a try is made with, and the account's name for the confirm: the app's test account is a
    test run; any other named account a live run on it; none a test run. An account of another app is refused, since
    the call would quietly take this app's default instead."""
    if not accounts:
        return TEST, {}, "Default"
    if service.auth is None:
        raise NotYetAvailable("This service cannot read the team's accounts.")
    app, name = next(iter(accounts.items()))
    if app != await _app_of(service, module):
        raise ValidationFailed("Pick an account of the app this tool belongs to.", code="account_other_app")
    found = await service.auth.connections.accounts(who.tenant_id, who.team.id, app)
    match = next((a for a in found if name_key(a.account_name or a.name) == name_key(name)), None)
    if match is None:
        raise ValidationFailed(f"{name} is not one of the team's accounts of this app.", code="account_unknown")
    shown = str(match.account_name or match.name)
    if match.sandbox:
        return TEST, {}, shown
    return LIVE, {app: shown}, shown


async def try_tool(service: ModuleService, who: Caller, body: ToolTryIn) -> Json:
    _can(who, "tools", "run", what="tools")
    found = await service.store.operation_named(who.tenant_id, body.tool, who.team.id)
    if found is None:
        raise NotFound("Tool")
    module, op = found
    if service.real_runs is None or who.principal is None:
        raise NotYetAvailable("This service runs no tries.")
    args: Json = dict(body.input)
    environment, accounts, account = await _run_for(service, who, module, dict(body.accounts))
    expected = plan_id(who, body.tool, args, environment, accounts)
    writes = op["access"] == "write"
    if body.plan_id is not None and (not writes or body.plan_id != expected):
        raise Conflict(
            "The values changed after the plan was shown; try it again to see the new plan.", code="plan_stale"
        )
    confirmed = body.plan_id is not None
    trial = Trial()
    ran = await service.real_runs(
        who.principal,
        tool=body.tool,
        args=args,
        environment=environment,
        act=f"try:{who.name}",
        trial=trial,
        secret_values=None,
        confirmed=confirmed,
        plan_only=writes and not confirmed,
        key=expected if confirmed else None,
        accounts=accounts or None,
    )
    out: Json = {
        "access": op["access"],
        "callId": ran["callId"],
        "live": environment == LIVE,
        "account": account,
        "log": [{"atMs": at, "message": message} for at, message in trial.log],
    }
    if trial.request is not None:
        out["request"] = trial.request
    if "code" in ran:
        return {**out, "kind": "refused", "status": ran["status"], "reasons": cast(JsonValue, ran["reasons"])}
    if "planned" in ran:
        plan = ran["planned"]
        # A test run on an app with no test account signs in with a live one: the confirm says so either way.
        on_test = isinstance(plan, dict) and plan.get("testAccount") is True
        return {**out, "kind": "planned", "planId": expected, "plan": plan, "live": environment == LIVE or not on_test}
    if "replayOf" in ran:
        out["replayOf"] = ran["replayOf"]
    return {**out, "kind": "sent" if writes else "ran", "ok": ran["ok"], "output": ran["output"]}
