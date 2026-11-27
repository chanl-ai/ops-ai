"""A job's own model alias through models-service (the guardrail checks, memory extraction), so an operator can give
that job a faster or stronger model than the turn's. While the alias is not bound the job runs on the turn's model, so
nothing changes without the binding. Only models-service's "no such alias" falls back; any other failure fails."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel

from .contract import ModelEndpoint
from .ports import ModelSource

# models-service logs every refused call, so an unbound alias is not asked again for a minute; a binding made with
# `make demo-model ALIAS=<alias>` is used from then on.
UNBOUND_SECONDS = 60.0
_unbound_until: dict[tuple[int, str], float] = {}


def preferred(source: ModelSource | None, alias: str, fallback: Model) -> Model:
    """`alias` through models-service, or `fallback` while models-service has no such alias."""
    key = (id(source), alias)
    if source is None or time.monotonic() < _unbound_until.get(key, 0.0):
        return fallback

    def unbound(status: int, body: object) -> bool:
        if status == 404 and "alias_not_found" in str(body):
            _unbound_until[key] = time.monotonic() + UNBOUND_SECONDS
            return True
        return False

    return _Preferred(source.model_for(alias), fallback, unbound)


class _Preferred(FallbackModel):
    """The alias's model, or the fallback while models-service has no such alias: on either loop."""

    def __init__(self, first: Model, fallback: Model, unbound: Callable[[int, object], bool]) -> None:
        def on(e: Exception) -> bool:
            return isinstance(e, ModelHTTPError) and unbound(e.status_code, e.body)

        super().__init__(first, fallback, fallback_on=on)
        self.first, self.spare, self.unbound = first, fallback, unbound

    def loop_endpoint(self) -> ModelEndpoint:
        from .kernel import model_endpoint  # noqa: PLC0415 - kernel imports this module

        main = model_endpoint(self.first)
        return dataclasses.replace(main, fallback=model_endpoint(self.spare), falls_back=self.unbound)


class PreferredAlias:
    """A ModelSource that answers every alias with `alias` first, falling back to the alias asked for."""

    def __init__(self, source: ModelSource, alias: str) -> None:
        self.source, self.alias = source, alias

    def model_for(self, alias: str) -> Model:
        return preferred(self.source, self.alias, self.source.model_for(alias))
