"""The override resolver (decision: the agent sets limits, callers override within them; wiki concepts/apis.md, the
override model). One function applies the agent's limits, then the thread's overrides, then the turn's, and returns the
effective settings a turn runs on and records.

Rules, per setting: a model chosen from the allowed models; a temperature within the range; instructions added, never
replaced, and only when the agent allows it; tools switched off, never added, and only those the agent lets callers
switch off; knowledge chosen from the allowed bases, and a turn may only narrow the thread's; a budget at or below the
ceiling, and a turn may only lower the thread's; output schema and variables free. A public widget key may set only
what the agent's `public_key_may` lists. A value outside the limits is refused with 422 naming the field, never
clamped (owner decision, 2026-10-16). Guardrails and approval policy are not settings here at all.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

from ops_agents.activities.agent_limits import AgentLimits
from ops_agents.activities.catalog import AgentDefinition
from ops_contracts.chat import ChatOverrides, EffectiveSettings
from ops_service_kit.errors import Unprocessable

CallerClass = Literal["trusted", "public_key"]
Layer = Literal["thread", "turn"]


# The wire types live in the contract; the resolver's names for them.
Overrides = ChatOverrides


# The public key's names for the fields it may set (agent_limits.PublicKeyOverride) and the fields they cover.
_PUBLIC: dict[str, tuple[str, ...]] = {
    "tools": ("tools_off",),
    "knowledge": ("knowledge_base_ids",),
    "budget": ("budget_usd",),
    "outputSchema": ("output_schema",),
    "variables": ("variables",),
}
_WIRE = {
    "model": "model",
    "temperature": "temperature",
    "instructions": "instructions",
    "tools_off": "toolsOff",
    "knowledge_base_ids": "knowledgeBaseIds",
    "budget_usd": "budgetUsd",
    "output_schema": "outputSchema",
    "variables": "variables",
    "widgets_off": "widgetsOff",
    "compose_off": "composeOff",
    "widgets_per_turn": "widgetsPerTurn",
}


def refuse(layer: Layer, field: str, message: str) -> Unprocessable:
    name = f"overrides.{layer}.{_WIRE[field]}"
    return Unprocessable(f"{name}: {message}", code="override_outside_limits", details={"field": name})


def _check_caller(o: Overrides, layer: Layer, limits: AgentLimits, caller: CallerClass) -> None:
    if caller == "trusted":
        return
    allowed = {f for key in limits.public_key_may for f in _PUBLIC.get(key, ())}
    for field in Overrides.model_fields:
        if getattr(o, field) is not None and field not in allowed:
            raise refuse(layer, field, "a public widget key may not set this.")


def _apply(e: EffectiveSettings, o: Overrides, layer: Layer, limits: AgentLimits) -> None:
    # An empty model is unset, as everywhere settings resolve: the agent's default applies.
    if o.model:
        if o.model not in limits.allowed_models:
            raise refuse(layer, "model", f"{o.model} is not one of {', '.join(limits.allowed_models)}.")
        e.model, e.sources[_WIRE["model"]] = o.model, layer
    if o.temperature is not None:
        t = limits.temperature
        if t is None:
            raise refuse(layer, "temperature", "this agent does not let callers set a temperature.")
        if not t.min <= o.temperature <= t.max:
            raise refuse(layer, "temperature", f"{o.temperature} is outside {t.min} to {t.max}.")
        e.temperature, e.sources[_WIRE["temperature"]] = o.temperature, layer
    if o.instructions is not None and o.instructions.strip():
        if not limits.callers_may_add_instructions:
            raise refuse(layer, "instructions", "this agent does not let callers add instructions.")
        e.added_instructions = [*e.added_instructions, o.instructions.strip()]
        e.sources[_WIRE["instructions"]] = layer
    if o.tools_off is not None:
        if outside := sorted(set(o.tools_off) - set(limits.switchable_tool_ids)):
            raise refuse(layer, "tools_off", f"cannot switch off {', '.join(outside)}.")
        e.tools_off = sorted(set(e.tools_off) | set(o.tools_off))
        e.sources[_WIRE["tools_off"]] = layer
    if o.knowledge_base_ids is not None:
        # Each layer chooses from what the layer before left: the agent's allowed bases, then the thread's choice.
        available = set(limits.allowed_knowledge_base_ids) if layer == "thread" else set(e.knowledge_base_ids)
        if outside := sorted(set(o.knowledge_base_ids) - available):
            where = "the agent's allowed bases" if layer == "thread" else "the thread's bases"
            raise refuse(layer, "knowledge_base_ids", f"{', '.join(outside)} not among {where}.")
        e.knowledge_base_ids = list(dict.fromkeys(o.knowledge_base_ids))
        e.sources[_WIRE["knowledge_base_ids"]] = layer
    if o.budget_usd is not None:
        if limits.budget is None:
            raise refuse(layer, "budget_usd", "this agent sets no budget, so callers may not set one.")
        cap = e.budget_usd if e.budget_usd is not None else limits.budget.ceiling_usd
        if not 0 < o.budget_usd <= cap:
            raise refuse(layer, "budget_usd", f"{o.budget_usd} must be above zero and at most {cap}.")
        e.budget_usd, e.sources[_WIRE["budget_usd"]] = o.budget_usd, layer
    if o.widgets_off is not None:
        if outside := sorted(set(o.widgets_off) - set(limits.switchable_widget_ids)):
            raise refuse(layer, "widgets_off", f"cannot switch off {', '.join(outside)}.")
        e.widgets_off = sorted(set(e.widgets_off) | set(o.widgets_off))
        e.sources[_WIRE["widgets_off"]] = layer
    if o.compose_off:
        # Narrow only: a later layer cannot switch composing back on.
        e.compose_off, e.sources[_WIRE["compose_off"]] = True, layer
    if o.widgets_per_turn is not None:
        cap = e.widgets_per_turn
        if o.widgets_per_turn < 0 or (cap is not None and o.widgets_per_turn > cap):
            raise refuse(layer, "widgets_per_turn", f"{o.widgets_per_turn} must be from 0 to {cap}.")
        e.widgets_per_turn, e.sources[_WIRE["widgets_per_turn"]] = o.widgets_per_turn, layer
    for field in ("output_schema", "variables"):
        if (value := getattr(o, field)) is not None:
            setattr(e, field, value)
            e.sources[_WIRE[field]] = layer


def resolve(
    limits: AgentLimits,
    default_kb_ids: list[str],
    *,
    thread: Overrides | None = None,
    turn: Overrides | None = None,
    caller: CallerClass = "trusted",
    widgets_per_turn: int | None = None,
) -> EffectiveSettings:
    """Agent limits, then the thread's overrides, then the turn's; raises 422 naming the first field out of bounds."""
    effective = EffectiveSettings(
        model=limits.default_model,
        temperature=limits.temperature.default if limits.temperature else None,
        knowledge_base_ids=[k for k in default_kb_ids if k in limits.allowed_knowledge_base_ids]
        or list(default_kb_ids),
        budget_usd=limits.budget.default_usd if limits.budget else None,
        # The agent's own cap; a caller may only lower it.
        widgets_per_turn=widgets_per_turn,
        sources={"model": "agent"},
    )
    layers: list[tuple[Layer, Overrides | None]] = [("thread", thread), ("turn", turn)]
    for layer, o in layers:
        if o is None:
            continue
        _check_caller(o, layer, limits, caller)
        _apply(effective, o, layer, limits)
    return effective


def parse(raw: dict[str, Any] | None, layer: Layer) -> Overrides | None:
    """Overrides from a request body: 422 naming the field for an unknown or mistyped one."""
    if raw is None:
        return None
    try:
        return Overrides.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        loc = str(first["loc"][0]) if first["loc"] else ""
        name = f"overrides.{layer}.{loc}" if loc else f"overrides.{layer}"
        raise Unprocessable(f"{name}: {first['msg']}", code="override_outside_limits", details={"field": name}) from e


def limits_for(agent: AgentDefinition, runtime_alias: str) -> AgentLimits:
    """The published version's limits; for an agent with none (a fixture, or one saved before limits), the defaults
    the decision names: its one model, its default bases, every granted tool switchable off, no added instructions."""
    model = agent.model_alias or runtime_alias
    if agent.limits is not None:
        # A version saved without a model has "" as its default and allowed model; "" is unset, the runtime's alias.
        allowed = [m or runtime_alias for m in agent.limits.allowed_models]
        default = agent.limits.default_model or model
        update = {"allowed_models": list(dict.fromkeys(allowed)), "default_model": default}
        return agent.limits.model_copy(update=update)
    return AgentLimits(
        allowed_models=[model],
        default_model=model,
        allowed_knowledge_base_ids=list(agent.default_kb_ids),
        switchable_tool_ids=list(agent.tools),
        switchable_widget_ids=[w.widget_id for w in agent.widgets],
    )
