"""The one call path: every tool call, whichever route took it, is decided and run here. POST /v1/calls and the
MCP adapter build a `CallRequest`, call `GatewayCalls.call` with the verified caller, and map the outcome to their own
wire form, so a call over MCP meets every rule a REST call meets: the registry decides the access class, the schema and
limits hold, check before sending judges a write with no approval, OPA checks the approval token, writes are claimed
once, the per-operation rate is spent, the executor runs on the egress policy, and the call log keeps the row.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from ops_access import BY_KEY, Access
from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ActingForPerson, Principal
from ops_policy import input_hash
from ops_service_kit.errors import ApiError, Forbidden
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.logging import get_logger

from .auth import SIGNED_WITH, Authenticator
from .environments import TEST
from .executor import Executor, Trial, invalid_fields
from .limits import amount_refusal
from .modules.policy import WriteApprovals, asker_refusal
from .modules.review_events import SYSTEM_TOOLS
from .opa import OpaClient
from .registry import Resolved, ToolRegistry
from .secrets import scrub
from .send_check import NEEDS_REVIEW, SendCheck
from .store import CallAbandonedError, CallLog, LeaseSupersededError
from .store.modules import Aggregate
from .store.rate_windows import RateWindows
from .tokens import claims_of
from .tools import ToolCaller

log = get_logger("ops_tools.gateway_calls")

API, MCP = "api", "mcp"
# A person's Real run from a tool page: the same checks as any call, logged under that person.
CONSOLE = "console"

# Turns a call's input into what is sent, and names the values to scrub from its answer (code runs).
Prepare = Callable[[Resolved | None, dict[str, Any]], Awaitable[tuple[dict[str, Any], list[str]]]]


@dataclass(frozen=True)
class CallRequest:
    tool: str
    input: dict[str, Any]
    key: str
    # thread, step, act and environment, as POST /v1/calls' runContext carries them.
    run_context: dict[str, Any] = field(default_factory=dict[str, Any])
    approval_token: str | None = None
    # The person the call acts for, from a verified acting-for token; never from `run_context`.
    acting_for: ActingForPerson | None = None
    # The person's own yes to a test run that asks them first, from the console's approval card. Honoured only on the
    # console channel, only for the answer "ask the person", and only for the person the call acts for.
    confirmed: bool = False


@dataclass(frozen=True)
class Allowed:
    call_id: str
    ok: bool
    output: Any
    view: Any = None
    replay_of: str | None = None


@dataclass(frozen=True)
class Refused:
    call_id: str
    status: int
    code: str
    reasons: list[str]
    # What the refusal adds for the caller: the rate limit and its reset, or the fields that failed the schema.
    details: dict[str, Any] = field(default_factory=dict[str, Any])


Outcome = Allowed | Refused


def _token_ref(token: str | None) -> str | None:
    """What the call log keeps of an approval token: a fingerprint that identifies it and cannot be replayed."""
    return "apt:" + hashlib.sha256(token.encode()).hexdigest()[:32] if token else None


# The refusal for a call acting for a person who has not connected their own account, made before the request is
# built (auth.Authenticator._not_linked).
NOT_LINKED = "CONNECTION_NOT_LINKED"


def _error_of(outcome: ToolOutcome) -> dict[str, Any] | None:
    """The executor's {code, message} on a failed call, for the call log."""
    output: Any = outcome.output
    if outcome.ok or not isinstance(output, dict):
        return None
    error: Any = cast(dict[str, Any], output).get("error")
    return cast(dict[str, Any], error) if isinstance(error, dict) else None


def system_call(token: str | None, workflow: str) -> bool:
    """Whether a verified approval token was minted for a run of `workflow` while it is a system workflow."""
    try:
        claims = claims_of(token) if token else {}
    except (IndexError, ValueError):
        return False
    return claims.get("system") is True and claims.get("workflow") == workflow


def _approvers(token: str | None) -> list[str]:
    try:
        return list(claims_of(token).get("approvers", [])) if token else []
    except (IndexError, ValueError):
        return []


WRITES = {"write"}
# Decides whether an approval the asker gave themselves still counts (asker_refusal).
ACCESS = Access()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def chosen_accounts(value: object) -> dict[str, str]:
    """The run context's `accounts`, app id to account name, keeping only text entries: what a step, an agent or a
    chat chose for each app. The registry reads the entry for the call's own app (PluginHost.for_call)."""
    if not isinstance(value, dict):
        return {}
    given = cast(dict[object, object], value)
    return {k: v.strip() for k, v in given.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}


def _before_policy(resolved: Resolved | None, args: dict[str, Any]) -> tuple[int, str, str, dict[str, Any]] | None:
    """Registry checks that need no decision from OPA: a hidden operation, an unpublished or drifted module, or input
    that fails the operation's schema, or an amount over its limit, is refused before the policy is asked and before
    anything leaves the gateway."""
    if resolved is None or resolved.operation is None or resolved.module is None:
        return None
    op, module = resolved.operation, resolved.module
    # A tool the team's plugin version lacks is refused as that (operation_hidden, naming the update below): adding it
    # from the catalog cannot help until the team takes the update.
    version_hidden = not op["enabled"] and bool(op.get("hidden_reason"))
    if module.get("tools_on") is not None and op["name"] not in module["tools_on"] and not version_hidden:
        # The team has not added this tool from its app's catalog: refused before any sign-in is asked for.
        app = str(module.get("app_title") or module["display_name"])
        title = str(cast(dict[str, Any], module.get("tool_titles") or {}).get(op["name"]) or op["name"])
        who = "someone who manages the team's apps"
        said = f"{app}'s {title} is not added to this team; {who} adds it from {app}'s Tools tab."
        # What the chat's card offers in place: Turn on <tool> on the app's Tools tab, or Ask an admin.
        template = str(module.get("template_id") or "")
        app_id = template if template.startswith("plugin:") else f"module:{module['id']}"
        return 403, "TOOL_NOT_ADDED", said, {"app": app, "appId": app_id, "tool": op["name"], "toolTitle": title}
    if module.get("sign_in_needed"):
        # Each person signs in, and the account has no instance yet: the plugin is on. Refused as a
        # missing sign-in, not as the plugin being off, so the tool page does not say the team admin must sign in.
        return 403, "CONNECTION_NOT_LINKED", str(module["sign_in_needed"]), {}
    if module.get("instance_missing"):
        # The team account has not signed in yet. The plugin is on.
        return 403, "NOT_SIGNED_IN", str(module["instance_missing"]), dict(module.get("team_sign_in") or {})
    if module.get("app_off"):
        # Installed and off for the caller's team: refused before approval, naming the app and team as
        # CONNECTION_NOT_LINKED names its account, so the caller can show who turns it on.
        return 403, "APP_OFF_FOR_TEAM", str(module["plugin_off"]), dict(module["app_off"])
    if module.get("account_choice"):
        # The person holds two accounts of the app and chose no default: refused before any sign-in is used, naming the
        # accounts, so chat asks which and the person may save it as their default.
        choice = dict(module["account_choice"])
        said = f"You have {len(choice['accounts'])} {choice['app']} accounts connected; choose which this uses."
        return 403, "ACCOUNT_CHOICE_NEEDED", said, choice
    if module.get("plugin_off"):
        # A plugin the install does not load: refused before approval, so no write waits for a person.
        return 403, "PLUGIN_DISABLED", str(module["plugin_off"]), {}
    if module.get("account_missing"):
        # The account a call named is not one of the team's accounts of the app: refused, never defaulted.
        return 404, "ACCOUNT_NOT_FOUND", str(module["account_missing"]), {}
    if module.get("account_not_yours"):
        # One person's own account, named by a call that does not act for them (a step, a schedule, someone else).
        return 403, "ACCOUNT_NOT_YOURS", str(module["account_not_yours"]), {}
    if module.get("sandbox_required"):
        # A test run named a live account and the app has no test account to use in its place.
        return 409, "SANDBOX_REQUIRED", str(module["sandbox_required"]), {}
    if module.get("package_missing"):
        # A package app on an account whose last Test found the package's objects missing: refused before the call
        # reaches the system, which would answer with an error naming an object nobody chose.
        return 409, "PACKAGE_MISSING", str(module["package_missing"]), {}
    if not op["enabled"]:
        why = op.get("hidden_reason") or f"{op['name']} is hidden in {module['display_name']}"
        return 403, "operation_hidden", str(why), {}
    if module["status"] != "published":
        return 403, "module_not_published", f"{module['display_name']} is not published", {}
    if module["drift"]:
        # The server's tools no longer match what was reviewed; nothing runs until the module is reviewed again.
        return 403, "module_drifted", f"{module['display_name']} has drifted from its reviewed tool list", {}
    problems = invalid_fields(op["input"], args)
    if problems:
        fields = ", ".join(f"{p['field']} ({p['message']})" for p in problems)
        return 422, "invalid_input", f"input does not match {op['name']}'s schema: {fields}", {"invalid": problems}
    # The amount limit holds before the policy and before any request is built (shared with the test panel).
    if (over := amount_refusal(op, args)) is not None:
        return over.status, over.code, over.message, {}
    return None


async def sign_in_details(
    auth: Authenticator | None,
    tenant_id: str,
    module: dict[str, Any] | None,
    person: ActingForPerson | None,
    access: str,
) -> dict[str, Any]:
    """A person's missing sign-in refused before the sign-in step names the account, its app and a link, as the one
    the sign-in step refuses does, so chat draws its Connect card; without them the chat showed a bare error."""
    module = module or {}
    connection_id = module.get("connection_id")
    details: dict[str, Any] = {"reason": "not_connected", "access": "write" if access == "write" else "read"}
    if module.get("display_name"):
        details["app"] = str(module.get("app_title") or module["display_name"])
    if auth is not None and person is not None and connection_id:
        details |= await auth.sign_in_request(tenant_id, str(connection_id), person)
    return details


class GatewayCalls:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        log: CallLog,
        opa: OpaClient,
        executor: Executor,
        counters: RateWindows,
        send_check: SendCheck | None,
        clock: Callable[[], float] = time.time,
        approvals: WriteApprovals | None = None,
        approver: Callable[[Principal], bool] | None = None,
        requester_may_decide: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.registry = registry
        # The tenant's requesterMayDecide, read live at each call; without it the policy's default (off) holds.
        self.requester_may_decide = requester_may_decide
        self.log = log
        self.opa = opa
        self.executor = executor
        self.counters = counters
        self.send_check = send_check
        # The team's and apps' approval settings; without them only the tool's own setting and MCP decide.
        self.approvals = approvals or WriteApprovals()
        # Whether the caller holds the approver role in the team (can() over the roles grid); nobody without it.
        self.approver = approver
        self.clock = clock

    async def _run(self, resolved: Resolved, tool: str, args: dict[str, Any], **kw: Any) -> ToolOutcome:
        """The executor's outcome, or a failed one when it raises. A write's row was claimed as running, and a row left
        running answers every retry "already running", so the run's step could neither finish nor fail."""
        try:
            return await self.executor.run(resolved, tool, args, **kw)
        except Exception as e:
            # The exception's text can carry a filled request or a secret, so only its class is kept.
            log.exception("gateway_call_failed", tool=tool, error=type(e).__name__)
            return ToolOutcome(False, {"error": {"code": "CALL_FAILED", "message": f"{tool} failed before an answer."}})

    async def console_run(
        self,
        caller: Principal,
        *,
        tool: str,
        args: dict[str, Any],
        environment: str,
        act: str,
        trial: Trial,
        secret_values: dict[str, str] | None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """A tool page's Real run as one gateway call, so it meets every rule an agent's call meets: approvals,
        limits, the egress policy, the team's account and the call log. The answer is plain data, so the module
        service needs no gateway types: {callId, ok, output} when it ran, {callId, status, code, reasons} when not."""
        # The person who pressed Run is whom the call acts for: their own sign-in signs it on an app each person
        # signs in to, and Usage names them.
        person = (
            ActingForPerson(sub=caller.sub, email=caller.email, name=caller.name, team_id=caller.team_id)
            if caller.kind == "person" and caller.team_id
            else None
        )
        req = CallRequest(
            tool=tool,
            input=args,
            key=new_id("console"),
            run_context={"environment": environment, "act": act},
            acting_for=person,
            confirmed=confirmed,
        )
        out = await self.call(caller, req, channel=CONSOLE, trial=trial, secret_values=secret_values)
        if isinstance(out, Refused):
            return {"callId": out.call_id, "status": out.status, "code": out.code, "reasons": out.reasons}
        return {"callId": out.call_id, "ok": out.ok, "output": out.output}

    async def _with_live_policy(self, caller: Principal) -> Principal:
        """`caller` carrying the tenant's requesterMayDecide as read at this call, in place of the token's copy."""
        if self.requester_may_decide is None:
            return caller
        may_decide = await self.requester_may_decide(caller.tenant_id)
        return caller.model_copy(update={"policies": {**caller.policies, "requesterMayDecide": may_decide}})

    async def _asker_refusal(self, tenant_id: str, req: CallRequest) -> Forbidden | None:
        """`can`'s own_request refusal when the call's approval names the person it acts for and the tenant's
        requesterMayDecide, read now, does not let an asker decide; the token alone cannot say, since the policy may
        have changed after it was minted."""
        if req.acting_for is None:
            return None
        may_decide = (
            await self.requester_may_decide(tenant_id)
            if self.requester_may_decide is not None
            else BY_KEY["requesterMayDecide"].default is True
        )
        approvers = _approvers(req.approval_token)
        return asker_refusal(ACCESS, req.acting_for, tenant_id, approvers, may_decide=may_decide)

    async def call(
        self,
        caller: Principal,
        req: CallRequest,
        *,
        generation: int | None = None,
        channel: str = API,
        client_name: str | None = None,
        prepare: Prepare | None = None,
        sees: Callable[[Aggregate], bool] | None = None,
        trial: Trial | None = None,
        secret_values: dict[str, str] | None = None,
    ) -> Outcome:
        """One call for `caller`, the verified principal of whichever route took it. `generation` is a run's lease
        generation (writes are fenced on it); `channel` and `client_name` say where the call came from, for the log.
        `sees` is the caller's team's view of the modules: an operation of a module outside it is refused. A tool page's
        Real run passes `trial`, which records the request as sent with its secrets hidden, and `secret_values`, values
        typed for this one call in place of unset secrets (never stored or logged)."""
        call_id = new_id("gwc")
        shown = {"trial": trial, "secret_values": secret_values} if trial is not None else {}
        started = time.monotonic()

        def elapsed() -> int:
            return round((time.monotonic() - started) * 1000)

        # The run the call is made in, live (production) or test; the registry picks the account it signs in with
        # from it (connections.records.account_for).
        run = str(req.run_context.get("environment") or TEST)
        resolved = await self.registry.resolve(
            req.tool,
            tenant_id=caller.tenant_id,
            team_id=caller.team_id,
            run=run,
            account=_text(req.run_context.get("account")),
            accounts=chosen_accounts(req.run_context.get("accounts")),
            person=req.acting_for.sub if req.acting_for else None,
        )
        access = resolved.access if resolved else "unknown"
        digest = input_hash(req.input)
        ctx = req.run_context
        row: dict[str, Any] = {
            "id": call_id,
            "tenant_id": caller.tenant_id,
            # The team the call acts in, so Usage shows a team only its own calls, also on a module every team shares;
            # a caller with no team (a service acting for the tenant) leaves the module's own team.
            "team_id": caller.team_id or (resolved.module.get("team_id") if resolved and resolved.module else None),
            "tool": req.tool,
            "access": access,
            "input_hash": digest,
            "idempotency_key": req.key,
            "thread_id": ctx.get("thread"),
            "step": ctx.get("step"),
            "sub": caller.sub,
            "act": ctx.get("act"),
            "approvers": _approvers(req.approval_token),
            "created_at": now_iso(),
            "module_id": resolved.module["id"] if resolved and resolved.module else None,
            "approval_token_id": _token_ref(req.approval_token),
            # The run the call was made in; connection_id names the account it signed in with.
            "environment": run,
            "connection_id": resolved.module.get("connection_id") if resolved and resolved.module else None,
            "channel": channel,
            "client_name": client_name,
            "acting_for": req.acting_for.email if req.acting_for else None,
        }

        async def over_rate() -> Refused | None:
            """Spends one of the operation's calls this minute; past the limit the call is refused and logged. Only a
            call that passed every other check and is about to run spends one."""
            if resolved is None or resolved.operation is None:
                return None
            op = resolved.operation
            limit = int(op["rate_limit_per_min"])
            spent = await self.counters.spend(caller.tenant_id, op.get("rate_key") or op["name"], limit)
            if spent.allowed:
                return None
            reason = f"rate limit of {limit} calls a minute reached for {op['name']}"
            row.update(decision="deny", reasons=[reason])
            error = {"code": "RATE_LIMITED", "message": reason}
            if access in WRITES:
                await self.log.refuse_claimed(call_id, reasons=[reason], error=error, latency_ms=elapsed())
            else:
                await self.log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return Refused(call_id, 429, "RATE_LIMITED", [reason], {"limit": limit, "resetAt": spent.reset_at})

        if sees is not None and resolved is not None and resolved.module is not None and not sees(resolved.module):
            reason = f"{req.tool} belongs to a module outside this team"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row, outcome="refused", latency_ms=elapsed(), error={"code": "team_forbidden", "message": reason}
            )
            return Refused(call_id, 403, "team_forbidden", [reason])
        args, hide = req.input, list[str]()
        if prepare is not None:
            # A code run's call: its secret handles become values here, after the input hash was taken, so
            # neither the hash nor the log row holds a value, and the answer is scrubbed of them.
            try:
                args, hide = await prepare(resolved, req.input)
            except ApiError as e:
                row.update(decision="deny", reasons=[e.message])
                error = {"code": e.code, "message": e.message}
                await self.log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
                return Refused(call_id, e.status, e.code, [e.message])
        early = _before_policy(resolved, args)
        if early is not None:
            status, code, reason, details = early
            if code == NOT_LINKED:
                module = resolved.module if resolved else None
                details = await sign_in_details(
                    self.executor.http.auth, caller.tenant_id, module, req.acting_for, access
                )
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row, outcome="refused", latency_ms=elapsed(), error={"code": code, "message": reason}
            )
            return Refused(call_id, status, code, [reason], details)
        policy = await self.registry.policy_for(req.tool, caller.tenant_id, caller.team_id) if resolved else None
        # From the registry and the team's settings, never the caller: whether this write needs an approval token.
        # `effective_answer` is the one rule: the tool's own setting, then its app's, then the team's; MCP always waits.
        module = resolved.module if resolved else None
        # A write signed in with the app's test account changes nothing real; the team's checkbox decides if it asks.
        on_test_account = bool((module or {}).get("sandbox"))
        needs = False
        # An answer of "person" is the asker's own confirmation in chat, so the four-eyes check below does not apply.
        confirmed_by_asker = False
        if access in WRITES:
            setting, setting_role = await self.registry.approval_setting(req.tool, caller.tenant_id, caller.team_id)
            answer = await self.approvals.answer(
                caller.tenant_id,
                caller.team_id,
                module,
                access=access,
                setting=setting,
                reviewer_role=setting_role,
                approvers=(policy or {}).get("approvers") or 1,
                channel=(
                    "mcp"
                    if channel == MCP
                    else "test"
                    if channel == CONSOLE
                    # Nobody in a chat to confirm (a workflow, a schedule): "ask the person" goes to the reviewer role.
                    else "workflow"
                    if req.acting_for is None
                    else "chat"
                ),
                test_account=on_test_account,
                tool=req.tool,
            )
            needs = bool(answer["waits"])
            confirmed_by_asker = answer["answer"] == "person"
        # When approval is on, roles decide: a person holding the approver role in the team is not
        # asked, and the log names them as the write's approver; anyone else needs an approval token.
        # requesterMayDecide is read now: the token's copy dates from when it was minted and may since be off.
        self_approved = bool(
            needs
            and req.approval_token is None
            and self.approver
            and self.approver(await self._with_live_policy(caller))
        )
        if (
            needs
            and confirmed_by_asker
            and req.confirmed
            and channel == CONSOLE
            and req.acting_for is not None
            and req.approval_token is None
        ):
            # A test run that asks the person: their yes on the console's card is the whole approval.
            self_approved = True
        if self_approved:
            row["approvers"] = [caller.email]
        approval_required = access not in WRITES or (needs and not self_approved)
        if access in WRITES and req.approval_token is None and self.send_check is not None:
            # Check before sending: a write the team's sending policy forbids, or one the check could not
            # judge, waits for a person; a write that carries an approval was decided by one and is not judged again.
            why = await self.send_check.needs_person(caller.tenant_id, caller.team_id, req.tool, req.input, digest)
            if why is not None:
                row.update(decision="deny", reasons=[why])
                await self.log.record(
                    **row, outcome="refused", latency_ms=elapsed(), error={"code": NEEDS_REVIEW, "message": why}
                )
                return Refused(call_id, 409, NEEDS_REVIEW, [why])
        decision = await self.opa.decide(
            {
                "tool": req.tool,
                "access": access,
                "approval_required": approval_required,
                # From the registry, never the caller: how many distinct people the token must name.
                "approvers_required": policy["approvers"] if policy else None,
                "input_hash": digest,
                "run_context": {**ctx, "sub": caller.sub},
                "token": req.approval_token,
                "now_ns": int(self.clock() * 1_000_000_000),
                # Set from the route that took the call, never by the caller: the registered rule reads it.
                "channel": channel,
            }
        )
        row.update(decision="allow" if decision.allow else "deny", reasons=decision.reasons)
        if not decision.allow:
            error = {"code": "gateway_refused", "message": "; ".join(decision.reasons)}
            await self.log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return Refused(call_id, 403, "gateway_refused", decision.reasons)
        asked_again = needs and not confirmed_by_asker and req.approval_token
        if asked_again and (own := await self._asker_refusal(caller.tenant_id, req)) is not None:
            # The token was valid when minted, but the person the call acts for approved it themselves and today's
            # policy no longer lets an asker decide (it changed mid-turn, or the write now needs a reviewer).
            row.update(decision="deny", reasons=[own.message])
            await self.log.record(
                **row, outcome="refused", latency_ms=elapsed(), error={"code": own.code, "message": own.message}
            )
            return Refused(call_id, own.status, own.code, [own.message])
        if req.tool in SYSTEM_TOOLS and not system_call(req.approval_token, SYSTEM_TOOLS[req.tool]):
            # The token is verified by now; it must have been minted for the one system workflow this tool serves.
            reason = f"{req.tool} is applied only by the {SYSTEM_TOOLS[req.tool]} system workflow"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row,
                outcome="refused",
                latency_ms=elapsed(),
                error={"code": "system_workflow_only", "message": reason},
            )
            return Refused(call_id, 403, "system_workflow_only", [reason])
        if access not in WRITES:
            if (limited := await over_rate()) is not None:
                return limited
            signing = SIGNED_WITH.set(None)
            outcome = await self._run(
                resolved or Resolved(access, "local"),
                req.tool,
                args,
                key=req.key,
                caller=ToolCaller.of(caller, acting_for=req.acting_for),
                environment=ctx.get("environment"),
                **shown,
            )
            row["credential"] = SIGNED_WITH.get()
            SIGNED_WITH.reset(signing)
            if hide:
                outcome = ToolOutcome(outcome.ok, scrub(outcome.output, hide), outcome.view)
            failed = _error_of(outcome)
            await self.log.record(**row, outcome="ok" if outcome.ok else "error", latency_ms=elapsed(), error=failed)
            return Allowed(call_id, outcome.ok, outcome.output, outcome.view)
        try:
            # The caller's lease generation arrives as the X-Lease-Generation header; the fence is checked in the
            # claim's own transaction, before the dedup lookup (ADR-0016).
            first = await self.log.claim(generation=generation, **row)
        except LeaseSupersededError:
            row.update(decision="deny", reasons=["lease superseded"])
            await self.log.record(**row, outcome="refused")
            return Refused(call_id, 409, "lease_superseded", ["lease superseded"])
        except CallAbandonedError:
            # Its caller found no record of it and moved on (a workflow's error port); running it now would act twice.
            reason = "this write's caller abandoned its key after losing the answer; it does not run"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(**row, outcome="refused", error={"code": "CALL_ABANDONED", "message": reason})
            return Refused(call_id, 409, "call_abandoned", [reason])
        if first is not None:
            if first["outcome"] == "running":
                reason = "the same write is already running; retry after it finishes"
                # A refusal like any other, so the log, the module's Denied count and the response agree.
                row.update(decision="deny", reasons=[reason])
                error = {"code": "WRITE_IN_PROGRESS", "message": reason}
                await self.log.record(**row, outcome="in_progress", latency_ms=elapsed(), error=error)
                return Refused(call_id, 409, "write_in_progress", [reason])
            # The same approved write again: answer with the first result, run nothing.
            await self.log.record(
                **row, outcome="replayed", output=first["output"], view=first["view"], replay_of=first["id"]
            )
            return Allowed(call_id, first["outcome"] == "ok", first["output"], first["view"], replay_of=first["id"])
        if (limited := await over_rate()) is not None:
            return limited
        approvers = (caller.email,) if self_approved else tuple(_approvers(req.approval_token))
        signing = SIGNED_WITH.set(None)
        outcome = await self._run(
            resolved or Resolved(access, "local"),
            req.tool,
            req.input,
            key=req.key,
            caller=ToolCaller.of(caller, approvers=approvers, acting_for=req.acting_for),
            environment=ctx.get("environment"),
            **shown,
        )
        credential = SIGNED_WITH.get()
        SIGNED_WITH.reset(signing)
        failed = _error_of(outcome)
        await self.log.finish(
            call_id,
            outcome="ok" if outcome.ok else "error",
            output=outcome.output,
            view=outcome.view,
            latency_ms=elapsed(),
            error=failed,
            credential=credential,
            # Refused at sign-in for a person with no account of their own: nothing was sent, and the run waiting for
            # them sends this write again under its key once they connect.
            unsent=(failed or {}).get("code") == NOT_LINKED,
        )
        return Allowed(call_id, outcome.ok, outcome.output, outcome.view)
