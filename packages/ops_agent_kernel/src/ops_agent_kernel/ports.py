"""What the kernel needs from outside, as Protocols; the caller constructs them and tests swap in fakes (spec 15 9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai.models import Model

from .types import Passage


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    output: Any
    # A view payload (spec 07 CD-4) the tool returned with its result, rendered as a widget by the host.
    view: dict[str, Any] | None = None


class ToolExecutor(Protocol):
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        """Runs one granted tool. `key` is the idempotency key; writes carry the approval token."""
        ...


class ModelSource(Protocol):
    """The model a turn runs on, by the alias its agent was published with."""

    def model_for(self, alias: str) -> Model: ...


class KnowledgePort(Protocol):
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]: ...


@dataclass(frozen=True)
class KernelPorts:
    model: Model
    tools: ToolExecutor
    knowledge: KnowledgePort
    # When set, each turn runs on `models.model_for(settings.model_alias)`; otherwise every turn runs on `model`.
    models: ModelSource | None = None
