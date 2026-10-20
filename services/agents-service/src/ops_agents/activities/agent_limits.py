"""The limits an agent version sets for callers who override its settings (decision: the agent sets limits, callers
override within them; wiki concepts/apis.md, the override model).

The builder saves them on the agent version and they publish through the same review as the rest of the agent, so a
caller can only narrow what a reviewed version allows. This module holds the limits and their own consistency; the
resolver that checks a caller's overrides against them is M1b's.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import Field

from ops_contracts.chat import WireModel
from ops_service_kit.errors import Unprocessable

# What a public widget key may override. Model, temperature and instructions are never in it.
PublicKeyOverride = Literal["tools", "knowledge", "budget", "outputSchema", "variables"]
PUBLIC_KEY_DEFAULT: list[PublicKeyOverride] = ["tools", "knowledge", "budget", "outputSchema", "variables"]
# The temperature range the model providers accept.
TEMPERATURE_FLOOR, TEMPERATURE_CEILING = 0.0, 2.0


class TemperatureLimits(WireModel):
    min: float
    max: float
    default: float


class BudgetLimits(WireModel):
    """Per run, in US dollars. A caller may lower the budget, never raise it past the ceiling."""

    ceiling_usd: float
    default_usd: float


class AgentLimits(WireModel):
    allowed_models: list[str]
    default_model: str
    # None: callers may not set a temperature; the model's default applies.
    temperature: TemperatureLimits | None = None
    # None: no budget is set on the agent; a caller still may not set one above a ceiling that does not exist.
    budget: BudgetLimits | None = None
    allowed_knowledge_base_ids: list[str] = Field(default_factory=list[str])
    # Granted tools a caller may switch off; a caller never adds one.
    switchable_tool_ids: list[str] = Field(default_factory=list[str])
    callers_may_add_instructions: bool = False
    # Pinned widgets a caller may switch off (c-082 widgets, narrowed by c-071); a caller never adds one, may switch
    # composing off and may lower the per-answer cap.
    switchable_widget_ids: list[str] = Field(default_factory=list[str])
    public_key_may: list[PublicKeyOverride] = Field(default_factory=lambda: list(PUBLIC_KEY_DEFAULT))


def _pinned_widget_ids(spec: dict[str, Any]) -> list[str]:
    pins = cast(list[dict[str, Any]], spec.get("widgetPins") or [])
    return [str(p.get("widgetId")) for p in pins]


def default_limits(spec: dict[str, Any]) -> AgentLimits:
    """For a version saved before limits existed (owner assumption, 2026-10-16): its one model, its default knowledge
    bases, every granted tool switchable off, no added instructions."""
    model = str(spec.get("model") or "")
    return AgentLimits(
        allowed_models=[model],
        default_model=model,
        allowed_knowledge_base_ids=list(spec.get("collections") or []),
        switchable_tool_ids=list(spec.get("toolIds") or []),
        switchable_widget_ids=_pinned_widget_ids(spec),
    )


def limits_of(spec: dict[str, Any]) -> AgentLimits:
    raw = spec.get("limits")
    return AgentLimits.model_validate(raw) if raw else default_limits(spec)


def refuse(field: str, message: str) -> Unprocessable:
    """422 naming the field, never a silent clamp (owner decision, 2026-10-16)."""
    return Unprocessable(f"limits.{field}: {message}", code="invalid_limits", details={"field": f"limits.{field}"})


def check_limits(limits: AgentLimits, spec: dict[str, Any]) -> None:
    """Limits must agree with the version they are saved on: the default model is the agent's model and allowed, the
    defaults sit inside their ranges, and every allowed base and switchable tool is one the version has."""
    model = str(spec.get("model") or "")
    if not limits.allowed_models:
        raise refuse("allowedModels", "name at least the agent's model.")
    if len(set(limits.allowed_models)) != len(limits.allowed_models):
        raise refuse("allowedModels", "names a model twice.")
    if limits.default_model not in limits.allowed_models:
        raise refuse("defaultModel", f"{limits.default_model or 'the runtime model'} is not one of the allowed models.")
    if limits.default_model != model:
        raise refuse("defaultModel", f"must be the agent's model, {model or 'the runtime model'}.")
    if (t := limits.temperature) is not None:
        if not TEMPERATURE_FLOOR <= t.min <= t.max <= TEMPERATURE_CEILING:
            raise refuse("temperature", f"min and max must satisfy {TEMPERATURE_FLOOR} <= min <= max <= 2.")
        if not t.min <= t.default <= t.max:
            raise refuse("temperature.default", f"{t.default} is outside {t.min} to {t.max}.")
    if (b := limits.budget) is not None:
        if b.ceiling_usd <= 0:
            raise refuse("budget.ceilingUsd", "must be above zero.")
        if not 0 < b.default_usd <= b.ceiling_usd:
            raise refuse("budget.defaultUsd", f"{b.default_usd} must be above zero and at most {b.ceiling_usd}.")
    bases = set(spec.get("collections") or [])
    if missing := sorted(bases - set(limits.allowed_knowledge_base_ids)):
        raise refuse(
            "allowedKnowledgeBaseIds", f"must include the agent's default bases; missing {', '.join(missing)}."
        )
    granted = set(spec.get("toolIds") or [])
    if extra := sorted(set(limits.switchable_tool_ids) - granted):
        raise refuse("switchableToolIds", f"names tools the agent is not granted: {', '.join(extra)}.")
    pinned = set(_pinned_widget_ids(spec))
    if extra := sorted(set(limits.switchable_widget_ids) - pinned):
        raise refuse("switchableWidgetIds", f"names widgets the agent does not pin: {', '.join(extra)}.")
