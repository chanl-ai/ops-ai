"""The tools behind the gateway. Until real tool servers exist these are the Runtime's local demo tools, now
run here after the gateway has allowed the call instead of inside the Runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ops_agent_kernel.ports import ToolOutcome
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.tools import LocalToolExecutor
from ops_email import MailNotConfiguredError, MailSender, OutboundMessage
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ApiError

from .modules.review_events import APPLY_ACCESS

# The local executor refuses a write without a token. By the time a call reaches it the gateway has decided, so
# this marker only says so; the token itself was checked by OPA.
DECIDED = "gateway-allowed"


@dataclass(frozen=True)
class ToolCaller:
    """Who a tool runs for: the verified caller the gateway decided for, the one way identity reaches tool code. Its
    tenant picks the modules, secrets and egress allow-list; its team is the team the call acts in."""

    tenant_id: str
    team_id: str | None
    sub: str
    kind: str
    # The people the call's approval token names, after the gateway verified it; empty for a call with none.
    approvers: tuple[str, ...] = ()

    @classmethod
    def of(cls, p: Any, *, approvers: tuple[str, ...] = ()) -> ToolCaller:
        """From an ops_identity Principal; a tenant is required, never defaulted."""
        if not p.tenant_id:
            raise ValueError("A tool call names no tenant.")
        return cls(tenant_id=str(p.tenant_id), team_id=p.team_id, sub=str(p.sub), kind=str(p.kind), approvers=approvers)


class AccessDecisions(Protocol):
    async def apply_access_decision(
        self,
        tenant_id: str,
        module_id: str,
        *,
        approval_id: str,
        decision: str,
        reason: str | None,
        by: str | None,
        team_id: str | None = None,
        deciders: Sequence[str] = (),
    ) -> dict[str, Any]: ...


class ToolRunner(Protocol):
    async def run(self, tool: str, arguments: dict[str, Any], *, key: str, caller: ToolCaller) -> ToolOutcome: ...


class LocalToolRunner:
    def __init__(
        self,
        catalog: Catalog,
        mail: MailSender | None = None,
        *,
        mail_for: Callable[[ToolCaller], MailSender] | None = None,
        mailbox_sender: Callable[[str, str, str], Awaitable[MailSender]] | None = None,
        cases: ServiceClient | None = None,
        decisions: AccessDecisions | None = None,
    ) -> None:
        """`mail_for` builds the sender for a caller, from the provider settings picked (ops_email.EmailProviders),
        reading that caller's tenant's secrets; `mail` is one fixed sender (tests). With neither, or none configured,
        every send_reply fails with that reason. `mailbox_sender(tenant, team, address)` is the sender of a named
        mailbox of the caller's team (mailboxes.MailboxSenders), used when send_reply names `mailbox`. `cases` is
        agents-service, where open_case opens a case in the caller's team (c-219)."""
        self.tools = LocalToolExecutor(catalog)
        self.mail = mail
        self.mail_for = mail_for
        self.mailbox_sender = mailbox_sender
        self.cases = cases
        self.decisions = decisions

    async def run(self, tool: str, arguments: dict[str, Any], *, key: str, caller: ToolCaller) -> ToolOutcome:
        if tool == "send_reply":
            message = OutboundMessage(key, (arguments["to"],), arguments["subject"], arguments["body"])
            mailbox = str(arguments.get("mailbox") or "")
            try:
                sender = await self._mailbox_sender(caller, mailbox) if mailbox else self._process_sender(caller)
                reference = await sender.send(message)
            except MailNotConfiguredError as e:
                return ToolOutcome(False, {"status": "failed", "error": str(e)})
            return ToolOutcome(True, {"status": "sent", "reference": reference})
        if tool == "open_case":
            return await self._open_case(arguments, key, caller)
        if tool == APPLY_ACCESS:
            return await self._apply_access(arguments, caller)
        return await self.tools.execute(tool, arguments, key=key, approval_token=DECIDED)

    async def _apply_access(self, arguments: dict[str, Any], caller: ToolCaller) -> ToolOutcome:
        """A tool access request's decision, applied to the module's grant (c-257). Who decided is the person the
        verified approval token names; the request must be one the calling team decides."""
        if self.decisions is None:
            return ToolOutcome(False, {"error": "This tools-service applies no access decisions."})
        if not caller.approvers:
            return ToolOutcome(False, {"error": "An access decision needs the approval of the person who made it."})
        try:
            approval = await self.decisions.apply_access_decision(
                caller.tenant_id,
                str(arguments["moduleId"]),
                approval_id=str(arguments["approvalId"]),
                decision=str(arguments["decision"]),
                reason=arguments.get("reason"),
                by=caller.approvers[0],
                team_id=caller.team_id,
                deciders=caller.approvers,
            )
        except ApiError as e:
            return ToolOutcome(False, {"error": str(e), "code": e.code})
        return ToolOutcome(True, {"approvalId": approval["id"], "status": approval["status"]})

    async def _open_case(self, arguments: dict[str, Any], key: str, caller: ToolCaller) -> ToolOutcome:
        """A case in the caller's team, keyed by the call so a retried call finds the case it opened."""
        if self.cases is None:
            return ToolOutcome(False, {"error": "This tools-service opens no cases: agents-service is not configured."})
        if not caller.team_id:
            return ToolOutcome(False, {"error": "A case belongs to a team; this call acts in none."})
        body = {
            "subject": arguments["subject"],
            "priority": arguments.get("priority") or "normal",
            "customerId": arguments.get("customerId"),
            "customerName": arguments.get("customerName"),
            "producerKey": f"tool:{key}",
        }
        try:
            case = await self.cases.post("/v1/cases", body, tenant=caller.tenant_id, team=caller.team_id)
        except ServiceCallError as e:
            return ToolOutcome(False, {"error": str(e), "code": e.code})
        except ServiceUnreachable:
            return ToolOutcome(False, {"error": "Cases cannot be reached; try again shortly."})
        return ToolOutcome(True, {"caseId": case["id"], "status": case["status"]})

    def _process_sender(self, caller: ToolCaller) -> MailSender:
        sender = self.mail_for(caller) if self.mail_for is not None else self.mail
        if sender is None:
            raise MailNotConfiguredError("No mail provider is configured for send_reply.")
        return sender

    async def _mailbox_sender(self, caller: ToolCaller, mailbox: str) -> MailSender:
        """A reply from a named mailbox goes out only through a mailbox of the team the call acts in."""
        if not caller.team_id:
            raise MailNotConfiguredError(
                f"A reply from {mailbox} needs a call that acts in a team; this one names none."
            )
        if self.mailbox_sender is None:
            raise MailNotConfiguredError(f"This tools-service sends from no mailbox, so {mailbox} cannot reply.")
        return await self.mailbox_sender(caller.tenant_id, caller.team_id, mailbox)
