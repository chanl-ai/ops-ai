"""Check before sending: with the team's checkBeforeSend on, a write that carries no approval is judged against
the team's newest sending policy before it runs. One model call per payload and policy version (kept by input hash);
a failure, a judge that cannot be reached or an answer that cannot be read sends the write to a person with the
reason, never through. A team with no policy has nothing to judge against, and a write with an approval was decided by
a person, so neither is judged."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from ops_service_kit.http import JsonValue
from ops_service_kit.logging import get_logger
from ops_service_kit.model_calls import ModelCallError, ModelCalls

from .modules.policy import CheckBeforeSend
from .store.send_policies import SendPolicies

log = get_logger("ops_tools.send_check")

SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "reason"],
    "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
}
INSTRUCTIONS = (
    "You check an outgoing message or call against a team's sending policy before it is sent. Answer ok true when "
    "nothing in it breaks the policy. Otherwise answer ok false, and give the reason in one sentence that names the "
    "rule it breaks."
)
# The gateway's refusal code for a write that waits for a person; callers turn it into an approval pause.
NEEDS_REVIEW = "needs_review"
NO_JUDGE = "The sending check could not run, so a person decides before it is sent."


class _Verdict(BaseModel):
    """The judge's answer, as SCHEMA asks for it; `ok` must be a real boolean."""

    model_config = ConfigDict(extra="ignore")

    ok: bool
    reason: str | None = None


@dataclass
class SendCheck:
    store: SendPolicies
    setting: CheckBeforeSend
    judge: ModelCalls | None

    async def needs_person(
        self, tenant_id: str, team_id: str | None, tool: str, arguments: dict[str, JsonValue], input_hash: str
    ) -> str | None:
        """Why the write waits for a person; None when it may go."""
        if team_id is None or not await self.setting.on(tenant_id, team_id):
            return None
        policy = await self.store.current(tenant_id, team_id)
        if policy is None:
            return None
        version = policy.version
        if (kept := await self.store.judged(tenant_id, team_id, input_hash, version)) is not None:
            return None if kept.ok else kept.reason
        if self.judge is None:
            return NO_JUDGE
        message = f"Sending policy:\n{policy.text}\n\nOutgoing {tool}:\n{json.dumps(arguments, sort_keys=True)}"
        try:
            answer = await self.judge.structured(
                INSTRUCTIONS, message, SCHEMA, tenant=tenant_id, step=f"send:{input_hash}"
            )
        except ModelCallError as e:
            log.warning("send_check_unreached", tool=tool, error=str(e))
            return NO_JUDGE
        try:
            verdict = _Verdict.model_validate(answer, strict=True)
        except ValidationError:
            return NO_JUDGE
        await self.store.keep(tenant_id, team_id, input_hash, version, ok=verdict.ok, reason=verdict.reason or "")
        return None if verdict.ok else (verdict.reason or "It breaks the team's sending policy.")
