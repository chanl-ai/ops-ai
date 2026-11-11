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
from ops_service_kit.errors import Conflict, ServiceUnavailable
from ops_service_kit.http import Envelope, Out
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ...store.team_defaults import TeamDefaults
from ...store.template_copies import TemplateCopies
from ..agent_registry import agent_review_body, go_live, registry
from ..auth import Principal, caller_in, caller_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..ops_tools import ensure_ops_assistant
from ..publish_policy import decide
from ..skills import pin, skills
from . import templates as template_routes
from .templates import _offered, _skill_content  # pyright: ignore[reportPrivateUsage] - one rule for a copy's content

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("agents"))]  # noqa: UP040

router = APIRouter(prefix="/v1/team-assistant")
log = get_logger("ops_agents.team_assistant")

GiveState = Literal["given", "in_review", "waiting", "already", "none"]


class AppToolsIn(WireModel):
    # The app's tool modules (its card's moduleIds), whose added read operations the assistant gets.
    module_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=1, max_length=20)


class AppToolsGiven(Out):
    agent_id: str
    agent_name: str
    # The read tools the assistant now holds from the app, by operation name, including any it held before.
    tools: list[str]
    # The app's skills pinned on the assistant with this change, by name: those whose every tool the team has added
    # (a skill that writes waits until an admin adds its write tool).
    skills: list[str] = Field(default_factory=list[str])
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

    added = {o.name for o in ops if o.module_id in wanted}
    shipped = [
        t
        for t in await _shipped(rt, team)
        if t.get("kind") == "skill" and set(cast(list[str], t["requires"]["tools"])) <= added
    ]
    pinned: list[str] = []

    def answer(state: GiveState) -> AppToolsGiven:
        # The app's state changed for the team: its apps line is read again on the next turn.
        if rt.apps_line is not None:
            rt.apps_line.forget(team)
        return AppToolsGiven(agent_id=agent.id, agent_name=agent.name, tools=reads, skills=pinned, state=state)

    if not reads and not shipped:
        return answer("none")
    reg = registry(rt)
    row = await reg.row(agent.id)
    published = row["published_version"]
    live = dict((await reg.version(agent.id, int(published)))["spec"]) if published is not None else {}
    held = [str(t) for t in cast(list[Any], live.get("toolIds") or [])]
    # A skill brings the tools it names, writes included once the team has added them; a write still waits for a
    # person's approval at the gate on every call.
    needed = [*reads, *(str(n) for t in shipped for n in cast(list[Any], t["requires"]["tools"]))]
    holds = {str(p.get("skillId")) for p in cast(list[dict[str, Any]], live.get("skillPins") or [])}
    if set(needed) <= set(held) and not await _unpinned(rt, shipped, holds):
        return answer("already")
    if row["version"] != published or any(r["status"] == "pending" for r in await reg.requests("agent", agent.id)):
        return answer("waiting")
    spec = {**live, "toolIds": [*held, *dict.fromkeys(t for t in needed if t not in held)]}
    for skill_id, name, version, renewed in await _skill_copies(rt, me, team, shipped):
        if skill_id in holds and not renewed:
            continue
        spec["skillPins"] = await pin(rt, spec, skill_id, version, by=me.email, at=now_iso())
        pinned.append(name)
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


async def _shipped(rt: Runtime, team: str) -> list[dict[str, Any]]:
    """The templates of the team's plugins; none when tools-service cannot list them, so the tools are still given and
    the skills follow on the next turn-on."""
    if rt.tool_reviews is None:
        return []
    try:
        return await _offered(rt, team)
    except ServiceUnavailable:
        log.warning("app_skills_unlisted", team=team)
        return []


async def _unpinned(rt: Runtime, shipped: list[dict[str, Any]], holds: set[str]) -> list[dict[str, Any]]:
    """The app's skills the team holds no pinned copy of yet, or whose copy the app's template has since changed."""
    copies = TemplateCopies(rt.db)
    out: list[dict[str, Any]] = []
    for t in shipped:
        held = await copies.live(str(t["source"]), str(t["id"]))
        if held is None or str(held["record_id"]) not in holds or await _stale(rt, held, t):
            out.append(t)
    return out


async def _newest_digest(rt: Runtime, skill_id: str) -> tuple[int, str | None]:
    row = await skills(rt).row(skill_id)
    found = await skills(rt).version(skill_id, int(row["version"]))
    return int(row["version"]), (str(found["digest"]) if found else None)


async def _stale(rt: Runtime, held: dict[str, Any], t: dict[str, Any]) -> bool:
    """Whether the team's copy was made from a template body the app has since changed, and the team has not edited
    the copy since, so taking the app's text overwrites nothing of theirs. A copy made with no record digest counts as
    edited once it has a version past its first."""
    if not t.get("digest") or held.get("digest") == t.get("digest"):
        return False
    version, newest = await _newest_digest(rt, str(held["record_id"]))
    kept = held.get("record_digest")
    return newest == kept if kept else version == 1


async def _skill_copies(
    rt: Runtime, me: Principal, team: str, shipped: list[dict[str, Any]]
) -> list[tuple[str, str, int, bool]]:
    """The team's published copy of each of the app's skills, made on first turn-on as the template install makes a
    copy, through the skill's content checks; published at once, since the admin turning the app on chose to give it
    to the assistant. A name the team already uses takes a number, as a slug is unique within its team. A copy the
    app's template has since changed, and the team has not edited, takes the new text as its next published version
    (the plugin's update reaches the assistant); each entry is (skill id, name, version to pin, renewed)."""
    copies, out = TemplateCopies(rt.db), list[tuple[str, str, int, bool]]()
    for t in shipped:
        source, tid, version = str(t["source"]), str(t["id"]), int(t["version"])
        held = await copies.live(source, tid)
        if held is not None:
            sid = str(held["record_id"])
            row = await skills(rt).row(sid)
            now = cast(dict[str, Any], (await skills(rt).versions(sid))[0]["content"])
            name = str(now.get("name") or row.get("name") or tid)
            if not await _stale(rt, held, t):
                out.append((sid, name, int(row["published_version"] or row["version"]), False))
                continue
            content = await _skill_content(rt, team, t, name, list(now.get("knowledgeBases") or []))
            note = f"Update from {cast(dict[str, Any], t.get('plugin') or {}).get('title') or source}"
            n = await skills(rt).save_draft(sid, content, by=me.email, note=note)
            await skills(rt).publish(sid, n, by=me.email, review_id="app_turn_on")
            await copies.updated(
                str(held["id"]), version=version, digest=cast(str | None, t.get("digest")),
                record_digest=(await _newest_digest(rt, sid))[1], base=template_routes.copy_base("skill", content),
            )  # fmt: skip
            out.append((sid, name, n, True))
            continue
        base = str(cast(dict[str, Any], t.get("body") or {}).get("name") or t["title"])
        for n in range(1, 10):
            name = base if n == 1 else f"{base} {n}"
            content = await _skill_content(rt, team, t, name, [])
            try:
                sid = await skills(rt).create(
                    content, owner_team=team, team_id=team, origin="imported", by=me.email, published=True
                )
            except Conflict as e:
                if e.code == "name_taken":
                    continue
                raise
            await copies.add(
                team_id=team,
                kind="skill",
                record_id=sid,
                source=source,
                template_id=tid,
                version=version,
                by=me.email,
                digest=cast(str | None, t.get("digest")),
                record_digest=(await _newest_digest(rt, sid))[1],
                base=template_routes.copy_base("skill", content),
            )
            out.append((sid, name, 1, False))
            break
    return out


@router.post("/app-tools", response_model=Envelope[AppToolsGiven])
async def give_assistant_app_tools(rt: Rt, me: Me, body: AppToolsIn) -> JSONResponse:
    """Gives the team's assistant an app's read tools, as a new version recorded as the caller's: someone who may edit
    the team's agents. Says whether it was published at once, waits on a review, or waits on someone's draft."""
    return ok((await give_app_tools(rt, me, body.module_ids)).model_dump(by_alias=True))
