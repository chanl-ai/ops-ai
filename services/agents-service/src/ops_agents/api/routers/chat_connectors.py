"""A chat's connectors: which apps one conversation uses, for the composer's picker.

Every connected connector is on in a new chat (owner, 8 November); the picker only narrows. The set is kept as the
thread's own `toolsOff` override, the same one the settings panel switches, so it removes tools from that thread's
turns and nothing else: it cannot add a tool the agent was not granted, a new thread starts with none off, and a run
nobody started in a chat (a schedule, a mailbox) never reads a thread's overrides.

The answer is joined here, so the picker makes one call: the agent's switchable tools grouped by the app their module
belongs to (tools-service's cards, read for the person), each app's state for the person, and whether the thread has
it off. An installed app the team has off is listed so the picker can offer its one action, and it never adds tools.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_agents.activities.overrides import limits_for, parse, resolve
from ops_contracts.chat import WireModel
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso

from ...activities.tool_directory import ToolsUnavailable
from ...store.team_defaults import TeamDefaults
from ..agent_calls import agent_team
from ..auth import Principal, principal, require_chat_use
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import graph_store
from .chat_settings import _thread, merge  # pyright: ignore[reportPrivateUsage] - one reader of a thread's settings

router = APIRouter(prefix="/chat", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# tools-service's appState for the person (its card), read as it is: the states in which the app works in this chat,
# and those in which an admin acts first, listed with no tools.
ON = ("connected", "test_failed")
ADMIN_FIRST = ("off", "needs_auth_config")
PERSON = ("person", "person_or_team")


class ChatConnector(Out):
    app_id: str
    name: str
    logo: str | None = None
    # The app card's state for the person, as tools-service answers it (GET /v1/apps appState), and why.
    app_state: str
    app_state_reason: str | None = None
    # Whether this chat uses it; always False for an app the team has off, which grants no tool.
    on: bool
    # The sign-in the person gives themselves, so the picker offers Connect; False when the team's account signs in.
    personal: bool = False
    tools: list[str] = Field(default_factory=list[str])


class ChatConnectors(Out):
    thread_id: str
    connectors: list[ChatConnector]


class ConnectorsIn(WireModel):
    # The apps this chat leaves out, by id; every other app the agent holds is on.
    off: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(max_length=100)


async def _by_app(rt: Runtime, me: Principal, team: str, held: list[str]) -> list[dict[str, Any]]:
    """The apps whose tools the agent holds, each with those tools, then the installed apps the team has off."""
    try:
        cards = await rt.app_states.cards(me.email or None, team) if rt.app_states is not None else []
    except ToolsUnavailable:
        cards = []
    module_of = {o.name: o.module_id for o in await rt.directory().operations()}
    out: list[dict[str, Any]] = []
    for card in cards:
        state = str(card.get("appState"))
        if card.get("kind") == "builtin" or state not in (*ON, "needs_sign_in", *ADMIN_FIRST):
            continue
        modules = set(cast(list[str], card.get("moduleIds") or []))
        tools = [t for t in held if module_of.get(t) in modules]
        if state in ADMIN_FIRST:
            out.append({**card, "tools": []})
        elif tools:
            out.append({**card, "tools": tools})
    return out


def _view(thread_id: str, apps: list[dict[str, Any]], off: set[str]) -> dict[str, Any]:
    rows = [
        ChatConnector(
            app_id=str(a["id"]),
            name=str(a["name"]),
            logo=a.get("logo"),
            app_state=a["appState"],
            app_state_reason=a.get("appStateReason"),
            on=a["appState"] not in ADMIN_FIRST and not set(a["tools"]) <= off,
            personal=a.get("signIn") in PERSON,
            tools=a["tools"],
        )
        for a in apps
    ]
    return ChatConnectors(thread_id=thread_id, connectors=rows).model_dump(by_alias=True)


@router.get("/connectors")
async def new_chat_connectors(
    rt: Rt, me: Me, agent_id: Annotated[str | None, Query(alias="agentId")] = None
) -> JSONResponse:
    """A new chat's connectors before it exists, for the picker on Chat's home: the agent's (the team's default when
    none is named), every one on. The chosen set goes onto the chat as soon as it is made, before its first message."""
    named = agent_id or await TeamDefaults(rt.db).agent(me.team_id)
    agent = rt.catalog.agent(named) if named else None
    if named and agent is None:
        raise Unprocessable("That agent is not live, so it cannot be chatted with.")
    if agent is not None:
        require_chat_use(me, team_id=await agent_team(rt, agent.id))
    held = list(limits_for(agent, rt.settings.model_alias).switchable_tool_ids) if agent is not None else []
    apps = await _by_app(rt, me, me.team_id, held) if agent is not None else []
    return ok(_view("", apps, set()))


@router.get("/threads/{thread_id}/connectors")
async def get_connectors(rt: Rt, me: Me, thread_id: str) -> JSONResponse:
    """The chat's connectors for the composer's picker: each app the agent holds tools of, with its state for the
    person and whether this chat uses it, then the apps the team has off."""
    row, _, limits = await _thread(rt, me, thread_id)
    apps = await _by_app(rt, me, str(row["team_id"]), list(limits.switchable_tool_ids))
    stored = cast(dict[str, Any], row.get("overrides") or {})
    return ok(_view(thread_id, apps, set(cast(list[str], stored.get("toolsOff") or []))))


@router.put("/threads/{thread_id}/connectors")
async def set_connectors(rt: Rt, me: Me, thread_id: str, body: ConnectorsIn) -> JSONResponse:
    """Which connectors this chat leaves out, as the whole set: their tools go into the thread's toolsOff, an app turned
    back on gets every tool back, and a tool the settings panel switched off one by one stays off while its app is
    on. 422 naming the app for one this chat does not hold."""
    row, agent, limits = await _thread(rt, me, thread_id)
    apps = await _by_app(rt, me, str(row["team_id"]), list(limits.switchable_tool_ids))
    held = {str(a["id"]): a for a in apps if a["appState"] not in ADMIN_FIRST}
    if unknown := [a for a in body.off if a not in held]:
        raise Unprocessable(
            f"This chat has no connector {unknown[0]} to turn off.",
            code="connector_unknown",
            details={"appId": unknown[0]},
        )
    stored = cast(dict[str, Any], row.get("overrides") or {})
    before = set(cast(list[str], stored.get("toolsOff") or []))
    off = set(before)
    for app_id, app in held.items():
        tools = set(app["tools"])
        if app_id in body.off:
            off |= tools
        elif tools <= before:
            off -= tools  # turned back on: every tool of the app runs again
        # an app left on keeps any of its tools the settings panel switched off one by one
    off = sorted(off)
    merged = parse(merge(stored, {"toolsOff": off or None}), "thread")
    resolve(limits, agent.default_kb_ids, thread=merged, widgets_per_turn=agent.widgets_per_turn)
    saved = (merged.model_dump(mode="json", by_alias=True, exclude_none=True) if merged else None) or None
    await graph_store(rt).set_overrides(thread_id, saved, updated_at=now_iso())
    return ok(_view(thread_id, apps, set(off)))
