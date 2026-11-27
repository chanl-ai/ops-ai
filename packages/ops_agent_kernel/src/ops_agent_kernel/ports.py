"""What the kernel needs from outside, as Protocols; the caller constructs them and tests swap in fakes (spec 15 9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from ops_contracts.chat import SignedIn
from ops_service_kit.http import Json

from .contract import LoopName
from .tool_cache import ToolCaches
from .types import Passage


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    output: Any
    # A view payload (spec 07 CD-4) the tool returned with its result, rendered as a widget by the host.
    view: dict[str, Any] | None = None
    # Why the call must wait for a person before it runs (the gateway's check before sending); the kernel
    # pauses the turn for approval with it, as a gated write's.
    needs_review: str | None = None
    # What the model is told in place of `output`, when the person is shown the outcome another way (a Connect card):
    # a plain line with no code, link or address to repeat. `output` stays on the call record for the card.
    for_model: Any = None
    # Whose login of the app the call ran as (the gateway's `signedIn`: the team's or the person's), for the chat card.
    signed_in: SignedIn | None = None


class ToolExecutor(Protocol):
    async def execute(self, tool: str, arguments: Json, *, key: str, approval_token: str | None) -> ToolOutcome:
        """Runs one granted tool. `key` is the idempotency key; writes carry the approval token."""
        ...


class BudgetReachedError(Exception):
    """Raised by the model port in place of a model call the turn's budget no longer covers. The kernel ends the
    reply, first asking for one closing answer with no tools (purpose "closing"), which the gateway admits once per
    replay key; a refused closing call ends the reply with the budget notice alone."""

    def __init__(self) -> None:
        super().__init__("The budget this reply spends from is spent.")


# Sent on every model call: what the call is for. The models gateway admits a "closing" call once per replay key past
# a spent budget, and "check" or "judge" calls up to its cap; a "turn" call is refused there.
PURPOSE_HEADER = "X-Call-Purpose"


def purpose(name: str) -> ModelSettings:
    """Settings that mark one model call's purpose, passed as `model_settings` to the run that makes it."""
    return {"extra_headers": {PURPOSE_HEADER: name}}


class ModelSource(Protocol):
    """The model a turn runs on, by the alias its agent was published with."""

    def model_for(self, alias: str) -> Model: ...


class KnowledgeUnavailableError(Exception):
    """The knowledge service cannot be asked (down, or none configured): the turn says so rather than answer uncited."""


class KnowledgePort(Protocol):
    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        """Passages for `query` from `kb_ids`, best first, as many as the bases' own settings return; raises
        KnowledgeUnavailableError when it cannot answer. A `KnowledgeFound` also carries each base's answer settings."""
        ...


@dataclass(frozen=True)
class KernelPorts:
    model: Model
    tools: ToolExecutor
    knowledge: KnowledgePort
    # When set, each turn runs on `models.model_for(settings.model_alias)`; otherwise every turn runs on `model`.
    models: ModelSource | None = None
    # The reads of the conversation and person a call is made for (tool_cache.py); None reads every time.
    tool_caches: ToolCaches | None = None
    # The agent loop a new turn runs on (contract.py); None takes contract.LOOP.default. A paused turn resumes on the
    # loop that paused it, whatever this says.
    loop: LoopName | None = None
