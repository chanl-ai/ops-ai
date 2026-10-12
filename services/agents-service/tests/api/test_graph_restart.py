# pyright: reportUnknownMemberType=false
"""A pause must survive the process: the review interrupt is written by one checkpointer and resumed through a
fresh connection pool and freshly compiled graphs, as after a restart. Runs against the compose PostgreSQL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.knowledge import KeywordPassageStore
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor
from ops_agents.graphs.checkpointer import open_checkpointer
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.registry import build_graphs
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model

EMAIL: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "seed" / "dispute_emails.json").read_text()
)[1]


def deps() -> GraphDeps:
    catalog = load_catalog(SEED)
    ports = KernelPorts(scripted_model(), LocalToolExecutor(catalog), KeywordPassageStore(catalog))
    return GraphDeps(catalog, ports, FakeGraphModels(), LocalReplySender(), "test-model")


@pytest.mark.usefixtures("local_tenant")
async def test_interrupt_survives_restart() -> None:
    url = Settings().database_url
    config: RunnableConfig = {"configurable": {"thread_id": new_id("restart")}}
    async with open_checkpointer(url) as saver:
        graph = build_graphs(deps(), saver)["complex_workflow"]
        await graph.ainvoke({"email": EMAIL}, config)
        assert (await graph.aget_state(config)).next == ("human",)

    async with open_checkpointer(url) as saver:
        graph = build_graphs(deps(), saver)["complex_workflow"]
        snap = await graph.aget_state(config)
        assert snap.interrupts and snap.interrupts[0].value["kind"] == "review"
        shown = snap.interrupts[0].value["review_id"]
        await graph.ainvoke(Command(resume={"decision": "approved"}), config)
        final = await graph.aget_state(config)
        assert final.values["status"] == "replied" and final.next == ()
        assert final.values["review_id"] == shown
