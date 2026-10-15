"""The agent and tool catalogue the Runtime serves until the registry and Protobox's tool gateway exist.

Definitions are data loaded from the seed directory (`tests/fixtures/seed/` by default, spec 17 7), so no demo
record lives in package code (spec 17 rule 3). Each agent's version, instructions and grants come from here; the
registry replaces this loader without changing its shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr

from ops_agent_kernel.types import Access, AgentSettings, PromptFragment, ToolGrant


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fragment(_Model):
    text: str
    stable: bool = True


class AgentDefinition(_Model):
    id: str
    name: str
    role: str
    version: int
    instructions: list[Fragment]
    tools: list[str]
    default_kb_ids: list[str]
    suggestions: list[str]
    max_tool_calls: int = 6
    # The model alias this agent runs on; None uses the runtime's alias.
    model_alias: str | None = None


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

    def grant(self) -> ToolGrant:
        return ToolGrant(self.name, self.server, self.description, self.access, self.input_schema)


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
    # Agents taken out of service (paused, unpublished): kept so a turn already under way, or an approval decided
    # after the pause, finishes on the definition it started with. No new turn starts on them.
    _retired: dict[str, AgentDefinition] = PrivateAttr(default_factory=dict[str, AgentDefinition])

    def agent(self, agent_id: str) -> AgentDefinition | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def agent_in_flight(self, agent_id: str) -> AgentDefinition | None:
        """The live definition, else the one a turn already under way started on."""
        return self.agent(agent_id) or self._retired.get(agent_id)

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

    def settings_for(self, agent: AgentDefinition, model_alias: str) -> AgentSettings:
        """`model_alias` is the runtime's; an agent that names its own alias runs on that one."""
        return AgentSettings(
            agent_id=agent.id,
            version=agent.version,
            instructions=[PromptFragment(f.text, f.stable) for f in agent.instructions],
            model_alias=agent.model_alias or model_alias,
            max_tool_calls=agent.max_tool_calls,
        )

    def grants_for(self, agent: AgentDefinition) -> list[ToolGrant]:
        return [t.grant() for name in agent.tools if (t := self.tool(name))]


def load_catalog(seed_dir: Path, agents_file: Path | None = None) -> Catalog:
    def read(name: str) -> Any:
        return json.loads((seed_dir / name).read_text())

    return Catalog(
        agents=json.loads(agents_file.read_text()) if agents_file else read("chat_agents.json"),
        tools=read("tools.json"),
        datasets=read("datasets.json"),
        passages=read("passages.json"),
        knowledge_bases=read("knowledge_bases.json"),
    )
