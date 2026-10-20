"""The agent and tool catalogue the Runtime serves until the registry and the tool gateway exist.

Definitions are data loaded from the seed directory (the service's seed/ in dev, none outside it, spec 17 7), so no
demo record lives in package code (spec 17 rule 3). Each agent's version, instructions and grants come from here; the
registry replaces this loader without changing its shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ops_agent_kernel.types import Access, AgentSettings, Guardrail, PromptFragment, Skill, ToolGrant, WidgetTemplate
from ops_contracts.chat import EffectiveSettings

from .agent_limits import AgentLimits


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fragment(_Model):
    text: str
    stable: bool = True


class GuardrailRule(_Model):
    """A pinned guardrail version's rule, as the agent version snapshotted it (kind blocked_topics)."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    guardrail_id: str = Field(alias="guardrailId")
    version: int
    name: str
    kind: str = "blocked_topics"
    topics: list[str]
    message: str
    # Topic to what it covers and what it does not; absent on versions saved before scopes existed.
    scopes: dict[str, str] = {}
    # The builder's switch on the agent version (c-085): off is never checked. Absent on pins saved before it: on.
    enabled: bool = True
    # Shown only once checked (kernel Guardrail.hold); absent on versions saved before the setting: off.
    hold: bool = Field(default=False, alias="holdUntilChecked")


class SkillPinRule(_Model):
    """A pinned skill version, as the agent version snapshotted it (spec 11)."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    skill_id: str = Field(alias="skillId")
    version: int
    name: str
    slug: str
    use_when: str = Field(alias="useWhen")
    loading: Literal["on_match", "always"]
    instructions: str
    guardrails: list[str] = []
    tokens: int = 0
    # The skill's own reply when one of its guardrails refuses; absent on versions saved before it.
    refusal: str = ""


class WidgetPinRule(_Model):
    """A widget template version (c-082): published in the library, and snapshotted on each agent version that pins
    it, so a turn reads its tree and data schema with no lookup."""

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    widget_id: str = Field(alias="widgetId")
    version: int
    name: str
    use_when: str = Field(alias="useWhen")
    tree: dict[str, Any]
    data_schema: dict[str, Any] = Field(alias="dataSchema")
    sample: dict[str, Any] | None = None

    def template(self) -> WidgetTemplate:
        return WidgetTemplate(self.widget_id, self.version, self.name, self.use_when, self.tree, self.data_schema)


class AgentDefinition(_Model):
    id: str
    name: str
    role: str
    version: int
    instructions: list[Fragment]
    tools: list[str]
    default_kb_ids: list[str]
    suggestions: list[str]
    # Per turn. Tool calls may be uncapped (the model-call cap still bounds the turn); model calls are always a number.
    max_tool_calls: int | None = 6
    max_model_calls: int = 8
    # Mask personal data in what the agent's turns show and return (guardrails.redactPii, c-293); on by default.
    redact_pii: bool = True
    # Per conversation (c-103): a chat thread's budget when it starts, and what each Continue adds. Always numbers; the
    # platform defaults stand in for an empty field (agent_registry.PLATFORM_CONVERSATION_*).
    max_conversation_calls: int = 200
    max_conversation_cost: float = 5.0
    # The model alias this agent runs on; None uses the runtime's alias.
    model_alias: str | None = None
    # Pinned guardrails, each its version's rule (c-063).
    guardrails: list[GuardrailRule] = []
    # Pinned skills, each its version's body and guardrails (c-063 slice 2).
    skills: list[SkillPinRule] = []
    # What callers may override, from the published version (c-068); None for a fixture agent with no registry row.
    limits: AgentLimits | None = None
    # Pinned widgets, whether the model may compose layouts, and how many widgets one answer may show (c-082).
    widgets: list[WidgetPinRule] = []
    compose: bool = False
    widgets_per_turn: int | None = None
    # What it remembers about each person (c-124): on by default, with these kinds.
    memory_enabled: bool = True
    memory_kinds: tuple[str, ...] = ("fact", "preference", "episode")


class ApprovalTemplate(_Model):
    """How a gated call is shown to the reviewer: `{field}` placeholders are filled from the call's input."""

    title: str
    action: str
    summary: str
    fields: list[tuple[str, str]]
    risk: Literal["critical", "high", "medium", "low"]
    consequence: str | None = None
    gate: str
    reviewers: str
    result: str


class ToolDefinition(_Model):
    name: str
    server: str
    description: str
    access: Access
    input_schema: dict[str, Any]
    kind: Literal["lookup", "draft"]
    dataset: str | None = None
    match_fields: list[str] = []
    view_title: str | None = None
    view_fields: list[tuple[str, str]] = []
    approval: ApprovalTemplate | None = None
    # Distinct people who approve a call to this write (the registry's `approvers`; 2 also asks for a step-up).
    approvers: int = 1
    # Approving asks for a step-up even with one approver (the registry's `stepUp`).
    step_up: bool = False
    # Whether a write waits for a person's approval; every write declares it (tests/unit/test_write_declarations.py),
    # and one that does not waits.
    requires_approval: bool | None = None

    def grant(self) -> ToolGrant:
        waits = self.access == "write" and self.requires_approval is not False
        return ToolGrant(self.name, self.server, self.description, self.access, self.input_schema, waits)


class PassageDefinition(_Model):
    document_id: str
    title: str
    section: str
    version: str
    text: str
    kb_id: str
    url: str | None = None


class KnowledgeBase(_Model):
    id: str
    name: str


class Catalog(_Model):
    agents: list[AgentDefinition]
    tools: list[ToolDefinition]
    datasets: dict[str, list[dict[str, str]]]
    passages: list[PassageDefinition]
    knowledge_bases: list[KnowledgeBase]
    # Published widget templates an agent version may pin (c-082 P1: seeded from widgets.json).
    widgets: list[WidgetPinRule] = []
    # Agents taken out of service (paused, unpublished): kept so a turn already under way, or an approval decided
    # after the pause, finishes on the definition it started with. No new turn starts on them.
    _retired: dict[str, AgentDefinition] = PrivateAttr(default_factory=dict[str, AgentDefinition])
    # Published versions a deployment pins (c-117), by (id, version): loaded from the registry on first use
    # (api/agent_registry.pinned_definition), so a pinned embed keeps serving its version after a newer one goes live.
    _pinned: dict[tuple[str, int], AgentDefinition] = PrivateAttr(
        default_factory=dict[tuple[str, int], AgentDefinition]
    )

    def agent(self, agent_id: str) -> AgentDefinition | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def agent_in_flight(self, agent_id: str) -> AgentDefinition | None:
        """The live definition, else the one a turn already under way started on."""
        return self.agent(agent_id) or self._retired.get(agent_id)

    def agent_at(self, agent_id: str, version: int) -> AgentDefinition | None:
        """The agent at one published version: the live one when it is that version, else a loaded pin."""
        live = self.agent(agent_id)
        if live is not None and live.version == version:
            return live
        return self._pinned.get((agent_id, version))

    def put_pinned(self, agent: AgentDefinition) -> None:
        self._pinned[(agent.id, agent.version)] = agent

    def put_agent(self, agent: AgentDefinition) -> None:
        """Makes `agent` the live definition under its id. The list is changed in place because the kernel ports, the
        graphs and the chat routes all hold this catalogue; a replacement object would leave them on the old one."""
        self.drop_agent(agent.id)
        self._retired.pop(agent.id, None)
        self.agents.append(agent)

    def drop_agent(self, agent_id: str) -> None:
        """Takes the agent out of service: chat and agent graphs refuse it until it is put back."""
        if (live := self.agent(agent_id)) is not None:
            self._retired[agent_id] = live
        self.agents[:] = [a for a in self.agents if a.id != agent_id]

    def tool(self, name: str) -> ToolDefinition | None:
        return next((t for t in self.tools if t.name == name), None)

    def kb_name(self, kb_id: str) -> str:
        return next((k.name for k in self.knowledge_bases if k.id == kb_id), kb_id)

    def settings_for(
        self, agent: AgentDefinition, model_alias: str, effective: EffectiveSettings | None = None
    ) -> AgentSettings:
        """`model_alias` is the runtime's; an agent that names its own alias runs on that one. `effective` is what the
        override resolver (activities/overrides.py) allowed for this turn: its model and temperature, and instructions
        the person added, placed after the agent's so they never replace them and never break the cached prefix."""
        added = [
            PromptFragment(f"Added by the person for this conversation, after your instructions:\n{text}", False)
            for text in (effective.added_instructions if effective else [])
        ]
        return AgentSettings(
            agent_id=agent.id,
            version=agent.version,
            instructions=[*(PromptFragment(f.text, f.stable) for f in agent.instructions), *added],
            # An empty alias is unset at every layer: the agent's, then the runtime's.
            model_alias=(effective.model if effective else agent.model_alias) or agent.model_alias or model_alias,
            temperature=effective.temperature if effective else None,
            max_tool_calls=agent.max_tool_calls,
            max_steps=agent.max_model_calls,
            redact_pii=agent.redact_pii,
            guardrails=[
                Guardrail(
                    g.guardrail_id, g.version, g.name, tuple(g.topics), g.message, tuple(g.scopes.items()), g.hold
                )
                for g in agent.guardrails
                if g.enabled
            ],
            guardrails_off=[
                Guardrail(
                    g.guardrail_id, g.version, g.name, tuple(g.topics), g.message, tuple(g.scopes.items()), g.hold
                )
                for g in agent.guardrails
                if not g.enabled
            ],
            skills=[
                Skill(
                    k.skill_id,
                    k.version,
                    k.name,
                    k.slug,
                    k.use_when,
                    k.loading,
                    k.instructions,
                    tuple(k.guardrails),
                    k.tokens,
                    k.refusal,
                )
                for k in agent.skills
            ],
            # Callers narrow widgets only: pinned ones switched off, composing off, a lower cap (resolver-checked).
            widgets=[w.template() for w in agent.widgets if not effective or w.widget_id not in effective.widgets_off],
            compose=agent.compose and not (effective and effective.compose_off),
            widgets_per_turn=effective.widgets_per_turn if effective else agent.widgets_per_turn,
        )

    def widget(self, widget_id: str, version: int | None = None) -> WidgetPinRule | None:
        """A published widget template version; the latest when `version` is None."""
        found = [w for w in self.widgets if w.widget_id == widget_id and version in (None, w.version)]
        return max(found, key=lambda w: w.version) if found else None

    def grants_for(self, agent: AgentDefinition) -> list[ToolGrant]:
        return [t.grant() for name in agent.tools if (t := self.tool(name))]


def load_catalog(seed_dir: Path | None, agents_file: Path | None = None) -> Catalog:
    """With no seed directory (outside dev, unless one is named) the catalogue is empty."""

    def read(name: str, empty: Any) -> Any:
        return json.loads((seed_dir / name).read_text()) if seed_dir else empty

    return Catalog(
        agents=json.loads(agents_file.read_text()) if agents_file else read("chat_agents.json", []),
        tools=read("tools.json", []),
        datasets=read("datasets.json", {}),
        passages=read("passages.json", []),
        knowledge_bases=read("knowledge_bases.json", []),
        # Optional: a seed directory without widget templates serves none.
        widgets=json.loads((seed_dir / "widgets.json").read_text())
        if seed_dir and (seed_dir / "widgets.json").exists()
        else [],
    )
