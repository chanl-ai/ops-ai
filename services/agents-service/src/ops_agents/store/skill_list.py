"""The skills list (`GET /v1/skills`) a page at a time in SQL, and the agents pinning one skill (`GET /v1/skills/{id}`).

Each skill is listed with its newest version, or its published one for the `published` view (what chat and the MCP
prompts use), and with what the page shows of the agents that pin it: `used_by` counts the acting team's agents whose
newest version pins the skill (`agent_skill_pins`, agents 0113) and `live_agents` those of them published and not
paused. `status` is deprecated, else in_review while the newest pending publish request names the newest version,
else published once a version is, else draft.

The view counts and the facets cover every skill the menu, `ids` and the search leave, before the view and the facet
filters, and read the newest version, as the page described them when it filtered in memory; a search reads the
newest version's name and use-when line and the slug; the rows, their sort (by name, lower-cased, then id) and the
`loading` filter read the version the view shows."""

from __future__ import annotations

from typing import Any, Literal

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.listing import ListParams
from ops_store.dialect import json_text
from ops_store.listing import ListPage, list_page, listed_rows
from ops_store.rows import rows
from ops_store.team_scope import team_visible

from .agent_registry import agent_skill_pins, publish_requests, registry_agent_versions, registry_agents
from .skills import registry_skill_versions, registry_skills
from .tenancy import current_tenant, tenant_tx

View = Literal["all", "published", "always", "drafts", "in_review", "deprecated", "unused"]
VIEWS: tuple[View, ...] = ("all", "published", "always", "drafts", "in_review", "deprecated", "unused")
FACETS = ("status", "ownerTeam", "origin", "loading")
# The publish request kind of a skill.
SKILL_KIND = "skill"


def _word(word: str) -> sa.ColumnClause[str]:
    """A fixed word written into the statement, not bound: a GROUP BY must name the same expression the select does,
    and two bound copies of one value are two parameters to SQL Server."""
    return sa.literal_column(f"'{word}'", sa.String())


def _pins_of_skill(skill: sa.ColumnElement[str]) -> sa.Select[Any]:
    """The acting team's agents of the caller's tenant pinning `skill` on their newest version."""
    p, a = agent_skill_pins, registry_agents
    return (
        sa.select(sa.func.count())
        .select_from(p.join(a, sa.and_(a.c.id == p.c.agent_id, a.c.tenant_id == p.c.tenant_id)))
        .where(p.c.tenant_id == current_tenant(), p.c.skill_id == skill, team_visible(p), team_visible(a))
    )


def _pending(skill: sa.ColumnElement[str], column: sa.ColumnElement[Any]) -> sa.ScalarSelect[Any]:
    """`column` of the skill's newest pending publish request."""
    r = publish_requests
    return (
        sa.select(column)
        .where(
            r.c.tenant_id == current_tenant(),
            r.c.kind == SKILL_KIND,
            r.c.subject_id == skill,
            r.c.status == "pending",
        )
        .order_by(r.c.created_at.desc(), r.c.id)
        .limit(1)
        .scalar_subquery()
    )


def skill_columns(*, served: bool) -> tuple[sa.Select[Any], dict[str, sa.ColumnElement[Any]]]:
    """The tenant's skills of the acting team (every team with none acting), one row each, and the list's columns by
    name. `served`: the row's content is the published version's."""
    s, newest, shown = registry_skills, registry_skill_versions.alias("newest"), registry_skill_versions.alias("shown")
    a = registry_agents
    used_by = _pins_of_skill(s.c.id).scalar_subquery()
    live = _pins_of_skill(s.c.id).where(a.c.published_version.is_not(None), a.c.paused == sa.false()).scalar_subquery()
    status = sa.case(
        (s.c.deprecated_reason.is_not(None), _word("deprecated")),
        (_pending(s.c.id, publish_requests.c.version) == s.c.version, _word("in_review")),
        (s.c.published_version.is_not(None), _word("published")),
        else_=_word("draft"),
    )
    columns: dict[str, sa.ColumnElement[Any]] = {
        "id": s.c.id,
        "slug": s.c.slug,
        "owner_team": s.c.owner_team,
        "team_id": s.c.team_id,
        "origin": s.c.origin,
        "version": s.c.version,
        "published_version": s.c.published_version,
        "deprecated_reason": s.c.deprecated_reason,
        "updated_at": s.c.updated_at,
        "updated_by": s.c.updated_by,
        "content": shown.c.content,
        "tokens": shown.c.tokens,
        "used_by": used_by,
        "live_agents": live,
        "pending_id": _pending(s.c.id, publish_requests.c.id),
        "status": status,
        # What the search, the facets and the view counts read: the newest version's.
        "name": json_text(newest.c.content, "name"),
        "use_when": json_text(newest.c.content, "useWhen"),
        "loading": json_text(newest.c.content, "loading"),
        # What the sort and the `loading` filter read: the version the row shows.
        "shown_name": sa.func.lower(json_text(shown.c.content, "name")),
        "shown_loading": json_text(shown.c.content, "loading"),
    }
    shown_version = s.c.published_version if served else s.c.version
    joined = s.join(
        newest,
        sa.and_(newest.c.tenant_id == s.c.tenant_id, newest.c.skill_id == s.c.id, newest.c.version == s.c.version),
    ).outerjoin(
        # Outer: a skill with no published version still counts in the published view's counts and facets.
        shown,
        sa.and_(shown.c.tenant_id == s.c.tenant_id, shown.c.skill_id == s.c.id, shown.c.version == shown_version),
    )
    q = (
        sa.select(*(c.label(name) for name, c in columns.items()))
        .select_from(joined)
        .where(s.c.tenant_id == current_tenant(), team_visible(s))
    )
    return q, columns


def offered_by(agent_id: str, *, team: str, menu: str) -> sa.ColumnElement[bool]:
    """The skills an agent's skill menu setting offers in a chat of `team` (`api.skills.usable`): every published, live
    skill of the team for `team`, those the agent's newest version pins for `attached`, none for `off`."""
    if menu == "off":
        return sa.false()
    s, p = registry_skills, agent_skill_pins
    terms = [s.c.team_id == team, s.c.published_version.is_not(None), s.c.deprecated_reason.is_(None)]
    if menu == "attached":
        terms.append(
            sa.exists().where(
                p.c.tenant_id == current_tenant(), p.c.agent_id == agent_id, p.c.skill_id == s.c.id, team_visible(p)
            )
        )
    return sa.and_(*terms)


def in_view(view: View, col: dict[str, sa.ColumnElement[Any]]) -> sa.ColumnElement[bool]:
    """The skills a view shows, by the newest version: a published version stays in use while a newer one is in
    review."""
    status, published = col["status"], col["published_version"]
    return {
        "all": sa.true(),
        "published": sa.and_(published.is_not(None), status != _word("deprecated")),
        "always": col["loading"] == _word("always"),
        "drafts": sa.and_(sa.or_(published.is_(None), col["version"] != published), status != _word("in_review")),
        "in_review": status == _word("in_review"),
        "deprecated": status == _word("deprecated"),
        "unused": col["used_by"] == 0,
    }[view]


async def skills_page(
    engine: AsyncEngine, params: ListParams, *, view: View, offered: sa.ColumnElement[bool] | None = None
) -> tuple[ListPage, dict[str, int]]:
    """One page of the skills list and each view's count. `offered` keeps the skills an agent's menu offers
    (`offered_by`)."""
    async with tenant_tx(engine) as c:
        return await _skills_page(c, params, view=view, offered=offered)


async def _skills_page(
    c: AsyncConnection, params: ListParams, *, view: View, offered: sa.ColumnElement[bool] | None
) -> tuple[ListPage, dict[str, int]]:
    q, col = skill_columns(served=view == "published")
    if offered is not None:
        q = q.where(offered)
    search = [col["name"], col["use_when"], col["slug"]]
    every = params.model_copy(update={"filters": {}})
    listed = listed_rows(q, every, search=search).subquery("listed")
    # Summed outside: SQL Server refuses an aggregate over an expression holding a subquery (the status, `used_by`).
    flags = q.with_only_columns(
        *(sa.case((in_view(v, col), 1), else_=0).label(v) for v in VIEWS), maintain_column_froms=True
    )
    counted = listed_rows(flags, every, search=search).subquery("flags")
    counts = (await c.execute(sa.select(*(sa.func.coalesce(sa.func.sum(counted.c[v]), 0) for v in VIEWS)))).one()
    facets: dict[str, dict[str, int]] = {}
    for facet, name in zip(FACETS, ("status", "owner_team", "origin", "loading"), strict=True):
        grouped = sa.select(listed.c[name], sa.func.count()).group_by(listed.c[name])
        facets[facet] = {str(v): int(n) for v, n in await c.execute(grouped) if v is not None}
    page = await list_page(
        c,
        q.where(in_view(view, col)),
        params,
        search=search,
        default_sort=col["shown_name"].asc(),
        filters={
            "status": col["status"],
            "ownerTeam": col["owner_team"],
            "origin": col["origin"],
            "loading": col["shown_loading"],
        },
    )
    page["facets"] = facets
    return page, {v: int(n) for v, n in zip(VIEWS, counts, strict=True)}


class MenuVersion(BaseModel):
    id: str
    content: dict[str, JsonValue]


class PinningAgent(BaseModel):
    """An agent whose newest version pins a skill."""

    id: str
    team_id: str
    published_version: int | None
    paused: bool
    updated_at: str
    pinned_version: int
    spec: dict[str, JsonValue]


class AgentSpec(BaseModel):
    spec: dict[str, JsonValue]


async def menu_versions(engine: AsyncEngine, ids: list[str]) -> dict[str, dict[str, JsonValue]]:
    """The content of the version an agent's menu reads (the published one, else the newest) of each of `ids`."""
    if not ids:
        return {}
    s, v = registry_skills, registry_skill_versions
    menu = sa.func.coalesce(s.c.published_version, s.c.version)
    q = (
        sa.select(s.c.id, v.c.content)
        .select_from(s.join(v, sa.and_(v.c.tenant_id == s.c.tenant_id, v.c.skill_id == s.c.id, v.c.version == menu)))
        .where(s.c.tenant_id == current_tenant(), s.c.id.in_(ids), team_visible(s), team_visible(v))
    )
    async with tenant_tx(engine) as c:
        return {m.id: m.content for m in await rows(c, q, MenuVersion)}


async def pinning_agents(engine: AsyncEngine, skill_id: str) -> list[PinningAgent]:
    """The acting team's agents of the caller's tenant whose newest version pins `skill_id`, by agent id: the agent's
    id, team, published version, paused flag and update time, the pinned version, and the newest version's spec."""
    p, a, v = agent_skill_pins, registry_agents, registry_agent_versions
    q = (
        sa.select(
            a.c.id,
            a.c.team_id,
            a.c.published_version,
            a.c.paused,
            a.c.updated_at,
            p.c.version.label("pinned_version"),
            v.c.spec,
        )
        .select_from(
            p.join(a, sa.and_(a.c.id == p.c.agent_id, a.c.tenant_id == p.c.tenant_id)).join(
                v, sa.and_(v.c.agent_id == a.c.id, v.c.tenant_id == a.c.tenant_id, v.c.version == a.c.version)
            )
        )
        .where(
            p.c.tenant_id == current_tenant(),
            p.c.skill_id == skill_id,
            team_visible(p),
            team_visible(a),
            team_visible(v),
        )
        .order_by(a.c.id)
    )
    async with tenant_tx(engine) as c:
        return await rows(c, q, PinningAgent)


async def newest_specs(engine: AsyncEngine) -> list[dict[str, JsonValue]]:
    """The newest version's spec of each of the acting team's agents of the caller's tenant, by agent id, in one
    read."""
    a, v = registry_agents, registry_agent_versions
    q = (
        sa.select(v.c.spec)
        .select_from(
            a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.tenant_id == a.c.tenant_id, v.c.version == a.c.version))
        )
        .where(a.c.tenant_id == current_tenant(), team_visible(a), team_visible(v))
        .order_by(a.c.id)
    )
    async with tenant_tx(engine) as c:
        return [a.spec for a in await rows(c, q, AgentSpec)]


__all__ = [
    "FACETS",
    "VIEWS",
    "MenuVersion",
    "PinningAgent",
    "View",
    "menu_versions",
    "newest_specs",
    "offered_by",
    "pinning_agents",
    "skill_columns",
    "skills_page",
]
