# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""The graphs the Runtime serves, by name."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from . import agent_wrapper, complex_workflow, simple_workflow
from .common import GraphDeps

GRAPHS = {
    "agent_wrapper": agent_wrapper.build,
    "simple_workflow": simple_workflow.build,
    "complex_workflow": complex_workflow.build,
}


def build_graphs(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None
) -> dict[str, CompiledStateGraph[Any, Any, Any, Any]]:
    return {name: build(deps, checkpointer) for name, build in GRAPHS.items()}
