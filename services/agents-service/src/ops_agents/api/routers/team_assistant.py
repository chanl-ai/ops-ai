"""POST /v1/team-assistant/app-tools: give the team's assistant an app's read tools, the Turn on window's choice.

An admin turning an app on decides whether the team's assistant gets the app's read tools (app-setup design: on by
default). The read tools are the app's operations the team added and agents may be granted (tools-service's grantable
list, read as this team); the assistant is the team's default agent, or its Ops Assistant when it has set none. The
change is a new version of the assistant, recorded as the admin's and published at once unless the team's publish
policy asks for a review, which the answer says. A draft someone else is editing, or an open review, is never stepped
over: the answer says the assistant is waiting and nothing changes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_service_kit.http import Envelope, Out

from ...store.team_defaults import TeamDefaults
from ..agent_registry import agent_review_body, go_live, registry
from ..auth import Principal, caller_in, caller_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..ops_tools import ensure_ops_assistant
from ..publish_policy import decide

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("agents"))]  # noqa: UP040

router = APIRouter(prefix="/v1/team-assistant")

GiveState = Literal["given", "in_review", "waiting", "already", "none"]


class AppToolsIn(WireModel):
    # The app's tool modules (its card's moduleIds), whose added read operations the assistant gets.
    module_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=1, max_length=20)


class AppToolsGiven(Out):
    agent_id: str
    agent_name: str
    # The read tools the assistant now holds from the app, by operation name, including any it held before.
    tools: list[str]
    # given: published at once; in_review: a new version waits on the team's publish review; waiting: someone's draft
    # or an open review comes first, so nothing changed; already: it held them all; none: the app has no read tools.
    state: GiveState


async def give_app_tools(rt: Runtime, me: Principal, module_ids: list[str]) -> AppToolsGiven:
    team = me.team_id
    can(caller_of(me), "agents", "edit", team=team, what="the team's assistant")
    agent_id = await TeamDefaults(rt.db).agent(team)
    agent = rt.catalog.agent(agent_id) if agent_id else None
    if agent is None:
        agent = await ensure_ops_assistant(rt, team)
    directory = rt.directory()
    # Read fresh: the app was turned on moments ago, after the kept list was read.
    if (forget := getattr(directory, "forget", None)) is not None:
        forget()
    ops = await directory.operations()
    wanted = set(module_ids)
    reads = sorted({o.name for o in ops if o.module_id in wanted and o.access == "read"})

    def answer(state: GiveState) -> AppToolsGiven:
        # The app's state changed for the team: its apps line is read again on the next turn.
        if rt.apps_line is not None:
            rt.apps_line.forget(team)
        return AppToolsGiven(agent_id=agent.id, agent_name=agent.name, tools=reads, state=state)

    if not reads:
        return answer("none")
    reg = registry(rt)
    row = await reg.row(agent.id)
    published = row["published_version"]
    live = dict((await reg.version(agent.id, int(published)))["spec"]) if published is not None else {}
    held = [str(t) for t in cast(list[Any], live.get("toolIds") or [])]
    if set(reads) <= set(held):
        return answer("already")
    if row["version"] != published or any(r["status"] == "pending" for r in await reg.requests("agent", agent.id)):
        return answer("waiting")
    spec = {**live, "toolIds": [*held, *(t for t in reads if t not in held)]}
    note = f"Given the read tools of {', '.join(module_ids)} when the app was turned on"
    n = await reg.save(agent.id, spec, by=me.email, note=note)
    decision = await decide(rt, area="agents", team_id=team, old=live, new=spec)
    if not decision.review_required:
        await reg.publish(agent.id, n, by=me.email, review_id="app_turn_on")
        if not row["paused"]:
            go_live(rt, agent.id, n, spec)
        return answer("given")
    v = await reg.version(agent.id, n)
    body = {**agent_review_body(agent.id, spec, row, v, note=note, by=me.email), **decision.record()}
    await reg.open_request("agent", agent.id, n, note=note, by=me.email, body=body, approved=False)
    return answer("in_review")


@router.post("/app-tools", response_model=Envelope[AppToolsGiven])
async def give_assistant_app_tools(rt: Rt, me: Me, body: AppToolsIn) -> JSONResponse:
    """Gives the team's assistant an app's read tools, as a new version recorded as the caller's: someone who may edit
    the team's agents. Says whether it was published at once, waits on a review, or waits on someone's draft."""
    return ok((await give_app_tools(rt, me, body.module_ids)).model_dump(by_alias=True))
