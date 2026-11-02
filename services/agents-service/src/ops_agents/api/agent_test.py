"""One kernel turn with no thread: the shared path for POST /test and each eval-run case."""

from __future__ import annotations

import time
from typing import Any

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.types import ToolGrant, TurnRequest, TurnResult
from ops_agents.activities.tool_directory import grants_for
from ops_agents.activities.tools import fill
from ops_agents.graphs.common import needs_step_up
from ops_service_kit.errors import ApiError, ServiceUnavailable
from ops_service_kit.ids import new_id

from .agent_registry import definition_of, registry
from .deps import Runtime

# Enough of a cited passage to recognise it in the test panel; the full text is in the knowledge base.
QUOTE_CHARS = 280


def model_refusal(result: TurnResult) -> ApiError | None:
    """A turn the model endpoint refused answers with that refusal: 429 for a rate limit or budget, 403 for an alias
    not cleared for the data, 404 for an alias models-service no longer serves; anything else it refused is 503."""
    if result.error_status is None:
        return None
    error = ApiError(result.error or "The model call was refused.", code=result.error_code or "model_refused")
    error.status = result.error_status if result.error_status in (403, 404, 429) else 503
    return error


def _held(rt: Runtime, grant: ToolGrant) -> dict[str, Any]:
    """A tool the tested agent holds: whether a call pauses for a review (the kernel gates every grant that is not
    read-only or a workflow) and, from its approval template, at which gate and for whom."""
    tool = rt.catalog.tool(grant.name)
    tpl = tool.approval if tool else None
    out: dict[str, Any] = {"name": grant.name, "access": grant.access, "pauses": grant.gated}
    if grant.gated:
        out |= {"gate": tpl.gate if tpl else "Approval", "reviewers": tpl.reviewers if tpl else "a reviewer"}
    return out


async def one_test_turn(
    rt: Runtime,
    agent_id: str,
    message: str,
    *,
    row: dict[str, Any],
    collections: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """The same one-turn harness POST /v1/agents/{id}/test uses. Eval-runs call this per case."""
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.", code="model_unavailable")
    reg = registry(rt)
    defn = definition_of(agent_id, int(row["version"]), (await reg.version(agent_id, int(row["version"])))["spec"])
    req = TurnRequest(
        turn_id=new_id("turn"),
        run_id=new_id("run"),
        settings=rt.catalog.settings_for(defn, rt.settings.model_alias),
        tools=await grants_for(rt.directory(), list(defn.tools)),
        transcript=[],
        user_turn=message,
        kb_ids=list(collections) if collections else defn.default_kb_ids,
    )
    started = time.perf_counter()
    result: TurnResult | None = None
    async for event in run_turn(req, rt.ports):
        if isinstance(event, TurnFinished):
            result = event.result
    assert result is not None
    if (refused := model_refusal(result)) is not None:
        raise refused
    try:
        kb_names = {k.id: k.name for k in await rt.kbs().bases()} if req.kb_ids or result.citations else {}
    except ApiError:
        kb_names = {}
    out: dict[str, Any] = {
        "reply": result.text,
        "toolCalls": [
            {
                "name": c.tool,
                "input": str(c.input),
                "output": "" if c.output is None else str(c.output),
                "status": c.status,
                "access": c.access,
            }
            for c in result.tool_calls
        ],
        "citations": [
            {
                "source": c.passage.title,
                "section": c.passage.section,
                "kbId": c.passage.kb_id,
                "kbName": kb_names.get(c.passage.kb_id, c.passage.kb_id),
                "page": c.passage.page,
                "quote": c.passage.text[:QUOTE_CHARS],
            }
            for c in result.citations
        ],
        "tookMs": round((time.perf_counter() - started) * 1000),
        "model": req.settings.model_alias,
        "knowledgeBases": [{"id": k, "name": kb_names.get(k, k)} for k in req.kb_ids],
        "tools": [_held(rt, g) for g in req.tools],
        "skills": result.skills,
        "guardrails": [{"name": g.get("name"), "version": g.get("version")} for g in result.guardrails_checked],
        "searched": bool(req.kb_ids),
    }
    fired = result.guardrail if result.stop_reason == "guardrail" else None
    if fired is not None and fired.get("when") in ("before", "after"):
        out["blockedBy"] = {"name": fired["name"], "topic": fired["topic"], "when": fired["when"]}
        if fired["when"] == "before":
            out |= {"searched": False, "skills": []}
    if result.interrupt is not None:
        call = result.interrupt.pending_call
        tool = rt.catalog.tool(call.tool)
        tpl = tool.approval if tool else None
        values = {k: str(v) for k, v in call.input.items()}
        out["wouldPause"] = {
            "gate": tpl.gate if tpl else result.interrupt.needed,
            "reviewers": tpl.reviewers if tpl else "a reviewer",
            "tool": call.tool,
            "action": fill(tpl.action, values) if tpl else result.interrupt.needed,
            "stepUp": await needs_step_up(rt.graph_deps, call.tool) if rt.graph_deps else False,
        }
    return out
