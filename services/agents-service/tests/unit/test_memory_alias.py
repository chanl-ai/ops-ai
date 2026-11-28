"""Memory extraction runs on its own alias, `memory-extract`, through models-service, so a reply's end does not wait on
the turn's slower model; while models-service has no such alias it runs on the runtime's alias as before."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ops_agent_kernel import aliases
from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.testing import Reply, Structured
from ops_agents.api.memory import MEMORY_ALIAS, extractor_for
from ops_service_kit.http import Json
from tests.conftest import model_on
from tests.unit.test_guardrails_kernel import NoKnowledge, NoTools

SCHEMA: Json = {"type": "object", "properties": {"memories": {"type": "array"}}, "required": ["memories"]}


def answering(value: str) -> ModelEndpoint:
    return model_on(lambda messages, tools: Structured({"memories": [{"value": value}]}))


def failing(refused: Reply) -> ModelEndpoint:
    return model_on(lambda messages, tools: refused)


class Source:
    """models-service by alias: `memory-extract` answers "fast" (or is refused with `memory`), every other alias
    "turn"."""

    def __init__(self, memory: Reply | None = None) -> None:
        self.memory = memory

    def model_for(self, alias: str) -> ModelEndpoint:
        if alias != MEMORY_ALIAS:
            return answering("turn")
        return answering("fast") if self.memory is None else failing(self.memory)


@pytest.fixture(autouse=True)
def _forget_unbound() -> None:
    aliases._unbound_until.clear()  # pyright: ignore[reportPrivateUsage]


async def read(source: Source) -> Any:
    ports = KernelPorts(model=answering("turn"), tools=NoTools(), knowledge=NoKnowledge(), models=source)
    rt: Any = SimpleNamespace(memory_extractor=None, ports=ports, settings=SimpleNamespace(model_alias="default"))
    said = "<remember>My timezone is Eastern.</remember>"
    return await extractor_for(rt).structured("Extract.", said, SCHEMA, key="m")


async def test_extraction_runs_on_the_memory_alias_when_models_service_binds_it() -> None:
    assert await read(Source()) == {"memories": [{"value": "fast"}]}


async def test_an_unbound_memory_alias_uses_the_runtime_alias() -> None:
    unbound = Reply(status=404, error={"error": {"code": "alias_not_found"}})
    assert await read(Source(unbound)) == {"memories": [{"value": "turn"}]}
