"""A review step that names a task type (c-288), by failure mode: a step naming no version opens with no version, so
the screen would follow whatever is newest when someone looks; the type's params reach the task unresolved, so it
shows `$.input.vendor` instead of the vendor; a step naming a type that is not published opens a task with no screen."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine import default_registry
from ops_engine.compiler import compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts

from .test_compiler import FakeReviews, FakeTools, config


class FakeTaskTypes:
    """write_approval is published up to v3; nothing else is."""

    async def pin(self, type_id: str, version: int | None) -> int:
        if type_id != "write_approval" or (version is not None and version > 3):
            raise LookupError(f"task type {type_id} v{version} is not published")
        return version or 3


def flow(task_type: dict[str, Any]) -> Any:
    review = {
        "id": "check",
        "type": "ops.flow.humanReview",
        "typeVersion": 1,
        "parameters": {
            "title": "Bank change",
            "taskType": task_type,
            "params": {"title": "Change the bank account for {$.input.vendor}?", "facts": "$.input.facts"},
        },
    }
    return parse(
        {
            "schemaVersion": 2,
            "id": "typed",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                review,
                {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
                {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
            ],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "check", "port": "in"}},
                {"from": {"node": "check", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
                {"from": {"node": "check", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            ],
        }
    )


async def _pause(task_type: dict[str, Any], thread: str) -> dict[str, Any]:
    d = flow(task_type)
    assert validate(d, default_registry()) == []
    ports = EnginePorts(tools=FakeTools(), reviews=FakeReviews(), task_types=FakeTaskTypes())
    g = compile_definition(d, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    facts = [{"label": "New account", "value": "****4410"}]
    await g.ainvoke({"input": {"vendor": "Acme", "facts": facts}}, config(thread), durability="sync")
    return (await g.aget_state(config(thread))).interrupts[0].value


async def test_a_step_naming_no_version_pins_the_newest_published_when_it_pauses() -> None:
    paused = await _pause({"id": "write_approval"}, "tt1")
    assert paused["taskType"] == {"id": "write_approval", "version": 3}
    assert paused["params"] == {
        "title": "Change the bank account for Acme?",
        "facts": [{"label": "New account", "value": "****4410"}],
    }


async def test_a_named_version_is_kept() -> None:
    assert (await _pause({"id": "write_approval", "version": 2}, "tt2"))["taskType"]["version"] == 2


async def test_a_type_that_is_not_published_fails_the_step() -> None:
    with pytest.raises(LookupError):
        await _pause({"id": "no_such_type"}, "tt3")
