"""Where a registry or deployment row's tenant comes from while those tables carry none, as statements the migration
that adds the column (0106) and the operator preflight both run, so the preflight reports exactly what would stop the
migration (docs/architecture/migration/agents-registry-tenancy.md).

A row's tenant is, in order: a direct reference from a table that has a tenant; the one tenant its team is seen in
across the tables that hold both a team and a tenant; `local`. A reference or team that names more than one tenant is
resolved by environment:
- outside dev, `local` holds only rows nothing could place, so it does not count beside one other tenant: that other
  tenant wins, and a record referenced only from `local` takes its team's tenant. Two or more tenants other than
  `local`, or a team seen in no tenant, stop the migration.
- in dev, anything but exactly one tenant falls back to `local`, where the dev seed and the dev caller live.

Tables and columns are named here as of agents revision 0105, not taken from the models, so a later model change does
not move what a shipped migration did.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.schema import backfill_ddl
from ops_store.team_scope import any_team

CHAIN = "agents"
LOCAL = "local"
# The seed's records: owned by this team, with a version the seed saved or published. They stay in `local`, where the
# start-up seed looks for them by their fixed ids; other tenants' threads get copies of a seeded workflow (0108).
SEED_TEAM = "team_ops"
SEED_BY = "seed"
# Teams an operator places by hand before the upgrade, as `team=tenant` pairs separated by commas: a team that has a
# registry row but no thread, run, case or other row with a tenant yet (docs/deploy/database.md).
DECLARED = "OPS_REGISTRY_TEAM_TENANTS"
# The preflight reads every tenant's references and teams; it writes nothing.
REGISTRY_TENANT_PREFLIGHT = "registry tenant preflight: every tenant's references and teams, read only"
# A registry row's tenant is decided from every team's references to it, before any caller exists.
EVERY_TEAMS_REFERENCES = "a registry row's tenant comes from every team's references to it"

# The tables that hold both a team and a tenant, each team-isolated.
TEAM_TENANT_SOURCES = (
    "graph_threads",
    "graph_runs",
    "cases",
    "mailboxes",
    "team_default_agents",
    "template_copies",
    "widget_deployments",
    "eval_cases",
    "eval_runs",
    "form_links",
    "agent_memories",
    "review_decisions",
    "review_approvals",
)

Placed = Literal["agent", "guardrail", "skill", "widget", "workflow", "deployment"]
TABLES: dict[Placed, str] = {
    "agent": "registry_agents",
    "guardrail": "registry_guardrails",
    "skill": "registry_skills",
    "widget": "registry_widgets",
    "workflow": "registry_workflows",
    "deployment": "deployments",
}


def table(name: str, *columns: str) -> sa.Table:
    """`name` with only `columns`, on metadata of its own, as of revision 0105."""
    return sa.Table(name, sa.MetaData(), *(sa.Column(c, sa.String) for c in columns))


DEPLOYMENT = "deployment:"


@dataclass(frozen=True)
class Declared:
    """What an operator placed by hand in OPS_REGISTRY_TEAM_TENANTS, read by the migrations and the preflight (this
    module reads no environment): (team, tenant) pairs, and (deployment id, tenant) pairs."""

    teams: tuple[tuple[str, str], ...] = ()
    deployments: tuple[tuple[str, str], ...] = ()


NONE = Declared()


def declared_of(text: str) -> Declared:
    """`team=tenant` and `deployment:<id>=tenant` pairs separated by commas; a malformed pair stops the caller."""
    teams: list[tuple[str, str]] = []
    deployments: list[tuple[str, str]] = []
    for item in filter(None, (p.strip() for p in text.split(","))):
        key, sep, tenant = (part.strip() for part in item.partition("="))
        if not sep or not key or not tenant or key == DEPLOYMENT:
            raise ValueError(f"{DECLARED}: {item!r} is not team=tenant or {DEPLOYMENT}<id>=tenant")
        if key.startswith(DEPLOYMENT):
            deployments.append((key.removeprefix(DEPLOYMENT), tenant))
        else:
            teams.append((key, tenant))
    return Declared(tuple(teams), tuple(deployments))


def _literal_pairs(pairs: Iterable[tuple[str, str]]) -> list[sa.Select[Any, Any]]:
    return [
        sa.select(sa.literal(key, sa.String).label("key"), sa.literal(tenant, sa.String).label("tenant_id"))
        for key, tenant in pairs
    ]


def team_tenants(declared: Declared = NONE) -> sa.Subquery:
    """Every distinct (key, tenant_id) pair of a team and a tenant it is seen in, or an operator declared for it; an
    empty team is no team."""
    selects: list[sa.Select[Any, Any]] = [
        sa.select(t.c.team_id.label("key"), t.c.tenant_id).where(t.c.team_id != "")
        for t in (table(name, "team_id", "tenant_id") for name in TEAM_TENANT_SOURCES)
    ]
    selects += _literal_pairs(declared.teams)
    return sa.union(*selects).subquery("team_tenants")


SEED_VERSIONS: dict[Placed, tuple[str, str, str]] = {
    "agent": ("registry_agent_versions", "agent_id", "saved_by"),
    "guardrail": ("registry_guardrail_versions", "guardrail_id", "saved_by"),
    "skill": ("registry_skill_versions", "skill_id", "saved_by"),
    "workflow": ("registry_workflow_versions", "workflow_id", "published_by"),
}


def seeded(kind: Placed, row: sa.TableClause) -> sa.ColumnElement[bool] | None:
    """Whether the `kind` row `row` (correlated, with `id` and `team_id`) is the seed's: the seed team's, with a version
    the seed saved or published. None for widgets and deployments, which carry no such mark."""
    if kind not in SEED_VERSIONS:
        return None
    name, parent, by = SEED_VERSIONS[kind]
    versions = table(name, parent, by).alias(f"seed_{kind}_versions")
    return sa.and_(
        row.c.team_id == SEED_TEAM,
        sa.exists(sa.select(versions.c[parent]).where(versions.c[parent] == row.c.id, versions.c[by] == SEED_BY)),
    )


def references(kind: Placed, declared: Declared = NONE) -> sa.Subquery | None:
    """(key, tenant_id) for each reference to a `kind` row from a table with a tenant; None when nothing names that
    kind. A thread names an agent as `agent:<id>`, a workflow by its id, and the deployment it came through."""
    graph_threads = table("graph_threads", "tenant_id", "team_id", "graph", "deployment_id")
    template_copies = table("template_copies", "tenant_id", "kind", "record_id")
    team_default_agents = table("team_default_agents", "tenant_id", "agent_id")
    widget_deployments = table("widget_deployments", "tenant_id", "agent_id")
    publish_requests = table("registry_publish_requests", "tenant_id", "kind", "subject_id")
    copies = sa.select(template_copies.c.record_id.label("key"), template_copies.c.tenant_id).where(
        template_copies.c.kind == kind, any_team(template_copies, EVERY_TEAMS_REFERENCES)
    )
    requests = sa.select(publish_requests.c.subject_id.label("key"), publish_requests.c.tenant_id).where(
        publish_requests.c.kind == kind
    )
    match kind:
        case "agent":
            # Aliased, so inside an UPDATE of registry_agents this is its own scan, not the updated row.
            agents = table("registry_agents", "id").alias("referenced_agents")
            union = sa.union(
                copies,
                requests,
                sa.select(team_default_agents.c.agent_id, team_default_agents.c.tenant_id).where(
                    any_team(team_default_agents, EVERY_TEAMS_REFERENCES)
                ),
                sa.select(widget_deployments.c.agent_id, widget_deployments.c.tenant_id).where(
                    any_team(widget_deployments, EVERY_TEAMS_REFERENCES)
                ),
                sa.select(agents.c.id, graph_threads.c.tenant_id)
                .join_from(agents, graph_threads, graph_threads.c.graph == sa.literal("agent:") + agents.c.id)
                .where(any_team(graph_threads, EVERY_TEAMS_REFERENCES)),
            )
        case "workflow":
            threads = sa.select(graph_threads.c.graph, graph_threads.c.tenant_id).where(
                any_team(graph_threads, EVERY_TEAMS_REFERENCES)
            )
            union = sa.union(copies, requests, threads)
        case "guardrail" | "skill":
            union = sa.union(copies)
        case "deployment":
            union = sa.union(
                sa.select(graph_threads.c.deployment_id.label("key"), graph_threads.c.tenant_id).where(
                    graph_threads.c.deployment_id.is_not(None), any_team(graph_threads, EVERY_TEAMS_REFERENCES)
                ),
                *_literal_pairs(declared.deployments),
            )
        case "widget":
            return None
    return union.subquery(f"{kind}_references")


def resolved(pairs: sa.Subquery, *, dev: bool) -> sa.Subquery:
    """(key, tenant_id): the one tenant each key resolves to by the rules above. Outside dev a key with two or more
    tenants other than `local` resolves to NULL, so a statement that writes it into a NOT NULL column fails even where
    nothing checked first (offline SQL)."""
    if dev:
        tenant = sa.case(
            (sa.func.count(sa.distinct(pairs.c.tenant_id)) == 1, sa.func.max(pairs.c.tenant_id)), else_=LOCAL
        )
    else:
        other = sa.case((pairs.c.tenant_id != LOCAL, pairs.c.tenant_id))
        others = sa.func.count(sa.distinct(other))
        tenant = sa.case((others == 1, sa.func.max(other)), (others == 0, LOCAL), else_=sa.null())
    return sa.select(pairs.c.key, tenant.label("tenant_id")).group_by(pairs.c.key).subquery()


def tenant_of(kind: Placed, row: sa.TableClause, *, dev: bool, declared: Declared = NONE) -> sa.ColumnElement[Any]:
    """The tenant of the `kind` row `row` (correlated): `local` for the seed's, else its references' tenant, else its
    team's, else `local`. A deployment with no team has only its references."""
    cases: list[tuple[sa.ColumnElement[bool], sa.ColumnElement[Any]]] = []
    if (seed := seeded(kind, row)) is not None:
        cases.append((seed, sa.literal(LOCAL)))
    refs = references(kind, declared)
    if refs is not None:
        direct = resolved(refs, dev=dev)
        found = sa.select(direct.c.tenant_id).where(direct.c.key == row.c.id)
        placed = direct.c.key == row.c.id
        if not dev:
            # Outside dev a reference from `local` alone places nothing: the row's team decides, as for a team.
            placed = sa.and_(placed, sa.or_(direct.c.tenant_id.is_(None), direct.c.tenant_id != LOCAL))
        cases.append((sa.exists(sa.select(direct.c.key).where(placed)), found.scalar_subquery()))
    team = resolved(team_tenants(declared), dev=dev)
    cases.append(
        (
            sa.exists(sa.select(team.c.key).where(team.c.key == row.c.team_id)),
            sa.select(team.c.tenant_id).where(team.c.key == row.c.team_id).scalar_subquery(),
        )
    )
    return sa.case(*cases, else_=LOCAL)


def team_placed(declared: Declared = NONE) -> sa.Subquery:
    """(source, team_id) for each registry or deployment row whose tenant only its team can give, by the outside-dev
    rules: not the seed's, no direct reference from a tenant other than `local`, and a team that is not empty."""
    selects: list[sa.Select[str, Any]] = []
    for kind, name in TABLES.items():
        t = table(name, "id", "team_id")
        q = sa.select(sa.literal(name, sa.String).label("source"), t.c.team_id).where(t.c.team_id != "")
        if (seed := seeded(kind, t)) is not None:
            q = q.where(~seed)
        refs = references(kind, declared)
        if refs is not None:
            q = q.where(t.c.id.not_in(sa.select(refs.c.key).where(refs.c.key.is_not(None), refs.c.tenant_id != LOCAL)))
        selects.append(q)
    return sa.union_all(*selects).subquery("team_placed")


def _non_local(pairs: sa.Subquery) -> sa.Select[Any, Any]:
    """(key, tenant_id) of each key seen in two or more tenants other than `local`, those tenants only."""
    others = sa.select(pairs.c.key, pairs.c.tenant_id).where(pairs.c.tenant_id != LOCAL).subquery()
    shared = sa.select(others.c.key).group_by(others.c.key).having(sa.func.count() > 1)
    return sa.select(others.c.key, others.c.tenant_id).where(others.c.key.in_(shared))


def unmapped_teams(declared: Declared = NONE) -> sa.Select[Any, Any, int]:
    """(team_id, source, rows) for the rows whose team is seen in no tenant."""
    placed, pairs = team_placed(declared), team_tenants(declared)
    return (
        sa.select(placed.c.team_id, placed.c.source, sa.func.count().label("rows"))
        .where(placed.c.team_id.not_in(sa.select(pairs.c.key)))
        .group_by(placed.c.team_id, placed.c.source)
        .order_by(placed.c.team_id, placed.c.source)
    )


def shared_teams(declared: Declared = NONE) -> sa.Select[Any, Any]:
    """(team_id, tenant_id) for each team some row needs that is seen in two or more tenants other than `local`."""
    placed, shared = team_placed(declared), _non_local(team_tenants(declared)).subquery()
    return (
        sa.select(shared.c.key.label("team_id"), shared.c.tenant_id)
        .where(shared.c.key.in_(sa.select(placed.c.team_id)))
        .order_by(shared.c.key, shared.c.tenant_id)
    )


def shared_records(declared: Declared = NONE) -> sa.CompoundSelect[Any, Any, Any]:
    """(source, id, tenant_id) for each existing row referenced from two or more tenants other than `local`, but the
    seed's, which stay in `local` (each tenant on a seeded workflow gets its own copy, agents 0108)."""
    selects: list[sa.Select[Any, Any, Any]] = []
    for kind, name in TABLES.items():
        refs = references(kind, declared)
        if refs is None:
            continue
        shared = _non_local(refs).subquery()
        rows = table(name, "id", "team_id")
        held = sa.select(rows.c.id)
        if (seed := seeded(kind, rows)) is not None:
            held = held.where(~seed)
        selects.append(
            sa.select(sa.literal(name, sa.String).label("source"), shared.c.key.label("id"), shared.c.tenant_id).where(
                shared.c.key.in_(held)
            )
        )
    return sa.union_all(*selects).order_by("source", "id", "tenant_id")


def teamless_deployments(declared: Declared = NONE) -> sa.Select[Any]:
    """(id,) of each deployment with no team and nothing that names its tenant: outside dev it would land in `local`,
    where no tenant's poller sees it."""
    rows, refs = table("deployments", "id", "team_id"), references("deployment", declared)
    assert refs is not None
    return (
        sa.select(rows.c.id)
        .where(rows.c.team_id == "", rows.c.id.not_in(sa.select(refs.c.key).where(refs.c.key.is_not(None))))
        .order_by(rows.c.id)
    )


@dataclass
class Gaps:
    """What stops the migration outside dev."""

    unmapped: list[tuple[str, str, int]] = field(default_factory=list[tuple[str, str, int]])
    teams: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    records: dict[tuple[str, str], list[str]] = field(default_factory=dict[tuple[str, str], list[str]])
    deployments: list[str] = field(default_factory=list[str])

    def lines(self) -> list[str]:
        out = [f"no tenant: team {team} holds {rows} row(s) in {source}" for team, source, rows in self.unmapped]
        out += [f"no tenant: deployment {d} has no team and no thread" for d in self.deployments]
        out += [f"two tenants: team {team} is in {len(ts)} tenants: {', '.join(ts)}" for team, ts in self.teams.items()]
        out += [
            f"two tenants: {source} {key} is referenced from {len(ts)} tenants: {', '.join(ts)}"
            for (source, key), ts in self.records.items()
        ]
        return out


def gap_queries(declared: Declared = NONE) -> tuple[sa.Executable, ...]:
    """The statements whose results `gaps_of` reads, in its order."""
    return (
        unmapped_teams(declared),
        teamless_deployments(declared),
        shared_teams(declared),
        shared_records(declared),
    )


def gaps_of(rows: tuple[Iterable[Any], Iterable[Any], Iterable[Any], Iterable[Any]]) -> Gaps:
    """Gaps from the results of `gap_queries()`, in that order."""
    unmapped, deployments, teams, records = rows
    found = Gaps(
        unmapped=[(r.team_id, r.source, int(r.rows)) for r in unmapped], deployments=[r.id for r in deployments]
    )
    by_team: dict[str, list[str]] = defaultdict(list)
    for r in teams:
        by_team[r.team_id].append(r.tenant_id)
    by_record: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in records:
        by_record[(r.source, r.id)].append(r.tenant_id)
    found.teams, found.records = dict(by_team), dict(by_record)
    return found


class PreflightRefused(RuntimeError):
    """The database cannot be read across tenants without changing its security policies."""


MSSQL_REFUSAL = (
    "SQL Server: every login but the agents system user is held to one tenant by the security policies, and that user "
    "may not read the registry tables, so this check cannot read every tenant without changing a policy. Run the "
    "upgrade online instead (make migrate): migration 0106 makes the same check before it changes any row and stops "
    "with this list. Its offline script cannot list: a team or record in two tenants fails it with a NOT NULL error, "
    "and a team in no tenant takes 'local' unchecked."
)


async def gaps(engine: AsyncEngine, declared: Declared = NONE) -> Gaps:
    """Every gap, read past the tenant by the connecting login. PostgreSQL: row security off for the transaction, which
    the database refuses for a login that does not bypass it, so a login that sees only some tenants fails instead of
    reporting none. Nothing is written and no policy is touched."""
    if engine.dialect.name == "mssql":
        raise PreflightRefused(MSSQL_REFUSAL)
    async with isolation.system_tx(engine, REGISTRY_TENANT_PREFLIGHT) as c:
        before, _after = backfill_ddl([], engine.dialect.name, chain=CHAIN)
        for statement in before:
            await c.execute(sa.text(statement))
        unmapped, deployments, teams, records = gap_queries(declared)
        found = gaps_of(
            (await c.execute(unmapped), await c.execute(deployments), await c.execute(teams), await c.execute(records))
        )
    return found
