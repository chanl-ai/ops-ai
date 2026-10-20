"""Whether a team's workflows may use AI steps (c-298): the aiSteps policy, a value per team, off until someone who
may manage workflow settings turns it on (owner, 2026-10-18). Read live from platform-service, as publishReview is, so
a change applies to the next listing and publish. With no platform URL, or when platform-service cannot be read, the
steps are off: the default holds."""

from __future__ import annotations

from dataclasses import dataclass

from ops_access import team_off, team_on
from ops_engine.definition import WorkflowDefinition
from ops_engine.node_types import TypeRegistry
from ops_engine.store import RunStore

from ..store.engine import AsyncEngine, EngineTransactions
from ..store.tenancy import NoTenantError
from .deps import Runtime
from .engine_agents import AI_STEPS_OFF, StepRules
from .platform_policies import PolicySource, PolicyUnread

KEY = "aiSteps"
# The executor every AI step type runs on (ops_engine.compiler.ai_prompt), so a new AI step is gated with no change.
EXECUTOR = "ai.prompt"
# One wording, the prompt port's, for a save refused and a step refused at run.
OFF = AI_STEPS_OFF


def ai_nodes(d: WorkflowDefinition, registry: TypeRegistry) -> list[str]:
    """The definition's steps that are AI steps, by id."""
    out: list[str] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is not None and t.executor == EXECUTOR:
            out.append(n.id)
    return out


async def _on(policies: PolicySource | None, team: str | None) -> bool:
    if team is None or policies is None:
        return False
    try:
        return team_on(await policies.value(KEY), team)
    except (NoTenantError, PolicyUnread):
        return False


async def _masks(policies: PolicySource | None, team: str | None) -> bool:
    if team is None or policies is None:
        return True
    try:
        return not team_off(await policies.value(MASK_KEY), team)
    except (NoTenantError, PolicyUnread):
        return True


async def team_rules(policies: PolicySource | None, team: str | None) -> StepRules:
    """A team's AI step rules, read live: off when the team, the source or aiSteps cannot be read; masked unless the
    team set aiStepsMaskPersonalData false (c-321), and masked when that cannot be read. Masking is read only for a
    team whose steps may run."""
    on = await _on(policies, team)
    return StepRules(on, await _masks(policies, team) if on else True)


async def people_see_masked(rt: Runtime, team: str | None) -> bool:
    """Whether people reading a run of `team` see personal data masked (aiStepsMaskPersonalData, c-321): workflow data
    stays real for the steps that use it, and the masking is where people read it."""
    return await _masks(rt.policies, team)


async def allowed(rt: Runtime, team: str | None) -> bool:
    return await _on(rt.policies, team)


MASK_KEY = "aiStepsMaskPersonalData"


@dataclass
class TeamRules:
    """The rules for a team known up front (the AI step route): the caller's team, read once per call."""

    policies: PolicySource | None
    team: str | None

    async def rules(self, run_id: str | None) -> StepRules:
        return await team_rules(self.policies, self.team)


@dataclass
class RunTeamRules:
    """The engine's RunRules: the run's team's rules, read live on every step. A run that cannot be read runs no AI
    step."""

    db: AsyncEngine
    policies: PolicySource | None

    async def rules(self, run_id: str | None) -> StepRules:
        run = await RunStore(EngineTransactions(self.db)).get(run_id) if run_id is not None else None
        if run is None:
            return StepRules(False, True)
        return await team_rules(self.policies, str(run["team_id"]))
