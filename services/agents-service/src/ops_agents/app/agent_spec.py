"""Checking an agent spec against the records it names: the rules of the spec page that need a lookup (3, 4, 5, 7,
13 and 14), over `SpecRecords`, which the route answers from this service's stores and the other services.

Not checked yet, because nothing owns the record: hook policies (rule 4 for `hooks`), the sandbox's image, sizes,
caps, the tenant's egress list and the team's secrets (rules 9 to 11), and the team's budget policy cap (rule 13's
second half). The sandbox takes effect in release 1.5.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ops_agents.domain.agent_spec import (
    AgentSpec,
    GuardrailRef,
    LoopWorkflow,
    Problem,
    SkillRef,
    document_problems,
    parse,
    pointer,
)
from ops_service_kit.http import Json


@dataclass(frozen=True)
class Versions:
    """A versioned record (a skill, a guardrail) as the check needs it: its published versions."""

    published: frozenset[int]
    newest_published: int | None


@dataclass(frozen=True)
class HelperFacts:
    team_id: str
    published: bool
    helpers: frozenset[str] = field(default_factory=frozenset[str])


class SpecRecords(Protocol):
    """The lookups a check makes. A dependency that cannot answer raises; nothing is checked half."""

    async def tools(self) -> set[str]: ...
    async def knowledge_bases(self) -> set[str]: ...
    async def skill(self, skill_id: str) -> Versions | None: ...
    async def guardrail(self, guardrail_id: str) -> Versions | None: ...
    async def agent(self, agent_id: str) -> HelperFacts | None: ...
    async def aliases(self) -> set[str]: ...


@dataclass(frozen=True)
class Checked:
    spec: AgentSpec | None
    problems: list[Problem]

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.problems


async def check(
    raw: Json, records: SpecRecords, *, team_id: str, agent_id: str | None, aliases: bool = True
) -> Checked:
    """Every rule of the spec page this release can check, in one pass. `agent_id` is the agent the spec is saved
    on (None for a new one), so a helper list naming it is refused. `aliases=False` leaves the model aliases to the
    caller: a publish checks them itself and answers `unknown_model_alias`."""
    spec, problems = parse(raw)
    if spec is None:
        return Checked(None, problems)
    own = agent_id or spec.id
    out = [
        *document_problems(spec),
        *await _reference_problems(spec, records, team_id=team_id, agent_id=own, aliases=aliases),
    ]
    return Checked(spec, out)


async def _reference_problems(
    spec: AgentSpec, records: SpecRecords, *, team_id: str, agent_id: str | None, aliases: bool
) -> list[Problem]:
    out: list[Problem] = []
    if spec.tool_ids or isinstance(spec.loop, LoopWorkflow):
        offered = await records.tools()
        for i, t in enumerate(spec.tool_ids or []):
            if t not in offered:
                out.append(Problem(pointer("toolIds", i), "unknown_tool", f"{t} is not a tool this team may use."))
        if isinstance(spec.loop, LoopWorkflow) and f"workflow:{spec.loop.workflow}" not in offered:
            out.append(
                Problem(
                    "/loop/workflow",
                    "workflow_unknown",
                    f"{spec.loop.workflow} is not a published workflow of this team.",
                )
            )
    if spec.collections:
        bases = await records.knowledge_bases()
        for i, kb in enumerate(spec.collections):
            if kb not in bases:
                out.append(Problem(pointer("collections", i), "record_unknown", f"{kb} is not a knowledge base."))
    for i, s in enumerate(spec.skills or []):
        ref = s if isinstance(s, SkillRef) else SkillRef(id=s)
        out.extend(_versioned(await records.skill(ref.id), ref.id, ref.version, pointer("skills", i), "skill"))
    for i, g in enumerate(spec.guardrails or []):
        gref = g if isinstance(g, GuardrailRef) else GuardrailRef(id=g)
        out.extend(
            _versioned(await records.guardrail(gref.id), gref.id, gref.version, pointer("guardrails", i), "guardrail")
        )
    for i, h in enumerate(spec.agents or []):
        out.extend(await _helper_problems(records, h.id, i, team_id=team_id, agent_id=agent_id))
    if not aliases:
        return out
    aliases_named = [("/model", spec.model)] if spec.model else []
    fallback = (spec.model_settings or {}).get("fallback")
    if isinstance(fallback, str):
        aliases_named.append(("/modelSettings/fallback", fallback))
    if aliases_named:
        known = await records.aliases()
        for path, alias in aliases_named:
            if alias not in known:
                out.append(Problem(path, "alias_unknown", f"{alias} is not a model alias this team may use."))
    return out


def _versioned(found: Versions | None, record_id: str, version: int | None, path: str, what: str) -> list[Problem]:
    if found is None:
        return [Problem(path, "record_unknown", f"{record_id} is not a {what} of this tenant.")]
    if version is None and found.newest_published is None:
        return [Problem(path, "record_not_published", f"{record_id} has no published version.")]
    if version is not None and version not in found.published:
        return [Problem(path, "record_not_published", f"{record_id} v{version} is not published.")]
    return []


async def _helper_problems(
    records: SpecRecords, helper_id: str, i: int, *, team_id: str, agent_id: str | None
) -> list[Problem]:
    path = pointer("agents", i, "id")
    if helper_id == agent_id:
        return [Problem(path, "helper_cycle", "An agent cannot be its own helper.")]
    found = await records.agent(helper_id)
    if found is None:
        return [Problem(path, "helper_unknown", f"{helper_id} is not an agent of this tenant.")]
    if found.team_id != team_id:
        return [Problem(path, "helper_other_team", f"{helper_id} belongs to another team.")]
    if not found.published:
        return [Problem(path, "helper_not_published", f"{helper_id} is not published.")]
    if agent_id is not None and agent_id in found.helpers:
        return [Problem(path, "helper_cycle", f"{helper_id} lists this agent as its own helper.")]
    return []
