"""GET /v1/graphs: what this Runtime can run, with the input each needs, so the console can offer a picker.

Code graphs are the ones compiled at start (`registry.GRAPHS`); agent graphs, `agent:<id>`, one per published agent;
definitions are the published workflows, at their latest version. A definition's input is the email its nodes read
(`WorkflowState.email`).
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...store.graphs import GraphStore
from ..auth import principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Envelope, GraphInfo

router = APIRouter(prefix="/v1/graphs", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases

EMAIL = {"name": "email", "label": "Email", "type": "email", "required": True}
# Titles and inputs of the code graphs, from their state types (agent_wrapper.AgentState and the others).
CODE_GRAPHS: dict[str, tuple[str, list[dict[str, Any]]]] = {
    "agent_wrapper": (
        "Agent with approvals (built-in)",
        [
            {"name": "agent_id", "label": "Agent", "type": "agent", "required": True},
            {"name": "message", "label": "Message", "type": "text", "required": True},
        ],
    ),
    "simple_workflow": (
        "Product question (built-in)",
        [{"name": "question", "label": "Question", "type": "text", "required": True}],
    ),
    # "(built-in)" because a published definition can carry the same name: dispute_email is this graph's twin.
    "complex_workflow": ("Dispute email (built-in)", [EMAIL]),
}


def _title(name: str) -> str:
    return name.replace("_", " ").capitalize()


@router.get("", response_model=Envelope[list[GraphInfo]])
async def list_graphs(rt: Rt) -> JSONResponse:
    out: list[dict[str, Any]] = []
    for name in rt.graphs:
        if name.startswith("agent:"):
            # A published agent's own graph (agent_registry.go_live): the agent's name, a message in.
            agent = rt.catalog.agent(name.removeprefix("agent:"))
            if agent is None:
                continue  # paused or withdrawn: its graph stays compiled only so turns under way can finish
            title, fields = (agent.name if agent else name), [CODE_GRAPHS["agent_wrapper"][1][1]]
            version = agent.version if agent else None
            out.append(
                {
                    "name": name,
                    "title": title,
                    "kind": "agent",
                    "builtIn": False,
                    "latestVersion": version,
                    "input": fields,
                }
            )
            continue
        title, fields = CODE_GRAPHS.get(name, (_title(name), []))
        out.append(
            {"name": name, "title": title, "kind": "code", "builtIn": True, "latestVersion": None, "input": fields}
        )
    # Published definitions are rows: listed with or without a model; only the code graphs need one to compile.
    latest = sorted((await GraphStore(rt.db).latest_versions()).items())
    out.extend(
        {"name": n, "title": _title(n), "kind": "definition", "builtIn": False, "latestVersion": v, "input": [EMAIL]}
        for n, v in latest
    )
    return ok(out)
