"""The agent spec file (apiVersion ops.ai/v2): its model, the rules that need no lookup, and the mapping between the
document and the stored agent version.

The document is mapped onto today's stored version, so the console's field-by-field editor and the runtime keep
reading the keys they read now. Fields today's version has no key for (loop, helpers, sandbox, hooks, output, the eval
gate) and the document as written live under one key of the version, `specDocument`, beside a digest per field of what
the stored keys said at the save. Export gives the field as written while the stored keys still say what they said
then, and rebuilds it from the stored keys once another save (the console's) changed them, so an export never shows a
value the agent no longer has.

Owns no lookup: rules that need a record (a tool, a helper, a skill) are in `ops_agents.app.agent_spec`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, cast

from pydantic import Field, ValidationError, model_validator

from ops_agent_kernel.layout import LayoutError, check_schema
from ops_service_kit.http import In, Json, JsonValue
from ops_service_kit.ids import canonical_json

API_VERSION: Final = "ops.ai/v2"
# Settings named on the spec page (OPS_AGENTS_SPEC_MAX_BYTES, OPS_AGENTS_MAX_HELPERS, OPS_AGENTS_MAX_EVAL_CASES) at
# their defaults; the helper and case caps are also the schema's maxItems.
SPEC_MAX_BYTES: Final = 262_144
OUTPUT_SCHEMA_MAX_BYTES: Final = 32 * 1024
# The key of a stored version that holds the document as written and the per-field digests.
DOCUMENT_KEY: Final = "specDocument"
# What a version saved without a cap runs on (api/agent_registry.py PLATFORM_MODEL_CALLS).
DEFAULT_STEPS: Final = 50

_HOST = r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
# The 253-character cap is max_length: Pydantic's regex engine has no look-ahead.
Host = Annotated[str, Field(pattern=_HOST, min_length=1, max_length=253)]
AgentId = Annotated[str, Field(pattern=r"^ag_[a-z0-9_]{1,60}$")]
# Today's grants are flat names (`lookup_account`), dotted plugin operations, and `workflow:<id>` or `agent:<id>`;
# the schema's dotted-only pattern would refuse every agent the console has built.
ToolId = Annotated[str, Field(pattern=r"^[a-z0-9_]+([.:][a-z0-9_]+)*$")]
PolicyId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SecretName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class Section(In):
    heading: str = Field(min_length=1, max_length=80)
    text: str = Field(max_length=8000)


class BriefSections(In):
    sections: list[Section] = Field(default_factory=list[Section], max_length=20)


class SkillRef(In):
    id: Annotated[str, Field(pattern=r"^sk_[a-z0-9_]+$")]
    version: int | None = Field(default=None, ge=1)


class GuardrailRef(In):
    id: Annotated[str, Field(pattern=r"^gr_[a-z0-9_]+$")]
    version: int | None = Field(default=None, ge=1)
    enabled: bool = True


class Privacy(In):
    mask_personal_data: bool = True


class Memory(In):
    enabled: bool = True
    kinds: list[Literal["fact", "preference", "episode"]] | None = None


class WidgetRef(In):
    id: str
    version: int | None = Field(default=None, ge=1)


class Widgets(In):
    pins: list[WidgetRef] = Field(default_factory=list[WidgetRef])
    compose: bool = False
    per_turn: int | None = Field(default=None, ge=0, le=10)


class Budget(In):
    default_usd: float | None = Field(default=None, gt=0)
    ceiling_usd: float = Field(gt=0)


class Temperature(In):
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, le=2)


class Limits(In):
    budget: Budget | None = None
    allowed_models: list[str] | None = None
    temperature: Temperature | None = None
    allowed_knowledge_base_ids: list[str] | None = None
    switchable_tool_ids: list[str] | None = None
    callers_may_add_instructions: bool = False


class _LoopCommon(In):
    max_steps: int | None = Field(default=None, ge=1, le=100)
    max_tool_calls: int | None = Field(default=None, ge=1, le=200)
    parallel_reads: bool = True


class LoopAuto(_LoopCommon):
    kind: Literal["auto"]
    replans: int = Field(default=2, ge=0, le=5)


class LoopSingle(_LoopCommon):
    kind: Literal["single"]


class LoopPlanExecute(_LoopCommon):
    kind: Literal["plan_execute"]
    replans: int = Field(default=2, ge=0, le=5)
    show_plan: bool = True
    review_plan: bool = False


class LoopSupervisor(_LoopCommon):
    kind: Literal["supervisor"]


class LoopSwarm(_LoopCommon):
    kind: Literal["swarm"]
    max_handoffs: int = Field(default=4, ge=1, le=20)


class LoopWorkflow(In):
    kind: Literal["workflow"]
    workflow: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    input: dict[str, str] | None = None


class LoopEvaluator(_LoopCommon):
    kind: Literal["evaluator"]
    rubric: str = Field(min_length=1, max_length=2000)
    judge: str | None = None
    max_rounds: int = Field(default=2, ge=1, le=5)


class LoopLongRunning(_LoopCommon):
    kind: Literal["long_running"]
    max_minutes: int = Field(default=60, ge=1, le=720)
    background: bool = False


Loop = Annotated[
    LoopAuto
    | LoopSingle
    | LoopPlanExecute
    | LoopSupervisor
    | LoopSwarm
    | LoopWorkflow
    | LoopEvaluator
    | LoopLongRunning,
    Field(discriminator="kind"),
]


class Helper(In):
    id: AgentId
    use: Literal["tool", "handoff"]
    version: int | None = Field(default=None, ge=1)


class SandboxLimits(In):
    command_minutes: float | None = Field(default=None, gt=0, le=120)
    idle_minutes: float | None = Field(default=None, gt=0, le=120)


class Network(In):
    allow: list[Host] = Field(default_factory=list[Host], max_length=50)


class SecretGrant(In):
    name: SecretName
    hosts: list[Host] = Field(min_length=1)


class SandboxFile(In):
    path: Annotated[str, Field(pattern=r"^[^/\\][^\\]{0,254}$")]
    from_: str | None = Field(default=None, alias="from")
    file_id: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SandboxFile:
        if (self.from_ is None) == (self.file_id is None):
            raise ValueError("name exactly one of from and fileId")
        return self


class Sandbox(In):
    image: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
    size: Literal["small", "standard", "large"] = "standard"
    limits: SandboxLimits | None = None
    network: Network | None = None
    secrets: list[SecretName | SecretGrant] = Field(default_factory=list[SecretName | SecretGrant], max_length=20)
    approve: list[Literal["delete_files", "install_packages", "network_read"]] = Field(
        default_factory=list[Literal["delete_files", "install_packages", "network_read"]]
    )
    files: list[SandboxFile] = Field(default_factory=list[SandboxFile], max_length=50)


class Hooks(In):
    before_model: list[PolicyId] | None = Field(default=None, max_length=10)
    after_model: list[PolicyId] | None = Field(default=None, max_length=10)
    before_tool: list[PolicyId] | None = Field(default=None, max_length=10)
    after_tool: list[PolicyId] | None = Field(default=None, max_length=10)


class Output(In):
    schema_: dict[str, JsonValue] | None = Field(default=None, alias="schema")
    rubric: str | None = Field(default=None, max_length=2000)
    judge: str | None = None
    max_rounds: int = Field(default=2, ge=1, le=5)


class ExpectFile(In):
    path: str = Field(min_length=1, max_length=400)
    contains: str | None = Field(default=None, max_length=400)


Mode = Literal["direct", "plan", "helpers", "sandbox"]


class Expect(In):
    calls: list[str] | None = None
    not_calls: list[str] | None = None
    contains: list[str] | None = None
    refuses: bool | None = None
    output: dict[str, JsonValue] | None = None
    mode: list[Mode] | None = Field(default=None, min_length=1)
    handoff: str | None = None
    pauses_for: Literal["approval", "question", "plan_review"] | None = None
    pauses_on: list[str] | None = None
    files: list[ExpectFile] | None = Field(default=None, max_length=10)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_seconds: float | None = Field(default=None, gt=0)
    rubric: str | None = None


class CaseContext(In):
    collections: list[str] | None = None


class EvalCase(In):
    name: str = Field(min_length=1, max_length=80)
    say: str = Field(min_length=1, max_length=8000)
    context: CaseContext | None = None
    expect: Expect | None = None


class Gate(In):
    pass_rate: float | None = Field(default=None, ge=0, le=1)


class Evals(In):
    gate: Gate | None = None
    repeat: int = Field(default=1, ge=1, le=5)
    cases: list[EvalCase] = Field(default_factory=list[EvalCase], max_length=200)


class AgentSpec(In):
    """The whole document. Unknown fields are refused (rule 1)."""

    api_version: Literal["ops.ai/v2"]
    id: AgentId | None = None
    # 200, as today's agent names; the schema file says 80.
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=400)
    instructions: str | None = Field(default=None, max_length=40000)
    brief: BriefSections | None = None
    prompt_mode: Literal["brief", "full"] | None = None
    model: str | None = Field(default=None, max_length=120)
    model_settings: (
        dict[Annotated[str, Field(pattern=r"^[a-z][a-zA-Z0-9_]{0,39}$")], float | Annotated[str, Field(max_length=120)]]
        | None
    ) = Field(default=None, max_length=12)
    channels: list[Literal["voice", "chat", "email", "api"]] | None = None
    tool_ids: list[ToolId] | None = Field(default=None, max_length=200)
    collections: list[Annotated[str, Field(pattern=r"^kb_[a-z0-9_]+$")]] | None = None
    all_team_knowledge_bases: bool = False
    skills: list[Annotated[str, Field(pattern=r"^sk_[a-z0-9_]+$")] | SkillRef] | None = Field(
        default=None, max_length=50
    )
    skill_menu: Literal["team", "attached", "off"] = "team"
    accounts: dict[str, Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=20)
    guardrails: list[Annotated[str, Field(pattern=r"^gr_[a-z0-9_]+$")] | GuardrailRef] | None = Field(
        default=None, max_length=50
    )
    privacy: Privacy | None = None
    when_unsure: Literal["handoff", "ask", "decline"] = "handoff"
    memory: Memory | None = None
    widgets: Widgets | None = None
    limits: Limits | None = None
    loop: Loop | None = None
    agents: list[Helper] | None = Field(default=None, max_length=12)
    sandbox: Sandbox | None = None
    hooks: Hooks | None = None
    output: Output | None = None
    evals: Evals | None = None


@dataclass(frozen=True)
class Problem:
    """One broken rule: `path` is a JSON pointer into the document."""

    path: str
    code: str
    message: str

    def wire(self) -> Json:
        return {"path": self.path, "code": self.code, "message": self.message}


def pointer(*parts: str | int) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


_ABSENT: Final = object()


def _child(here: JsonValue, part: int | str) -> object:
    if isinstance(here, list) and isinstance(part, int):
        return here[part] if 0 <= part < len(here) else _ABSENT
    if isinstance(here, dict) and isinstance(part, str):
        return here.get(part, _ABSENT)
    return _ABSENT


def _pointer_of(loc: tuple[int | str, ...], raw: JsonValue) -> str:
    """A Pydantic error location as a pointer into `raw`: a union's member label (`supervisor`, `SkillRef`, `str`)
    is not a key of the document, so it is skipped; the last part is kept, since a missing or unknown field is not
    in the document either."""
    out: list[str | int] = []
    here: JsonValue = raw
    for i, part in enumerate(loc):
        last = i == len(loc) - 1
        inside = _child(here, part)
        if inside is not _ABSENT:
            out.append(part)
            here = cast(JsonValue, inside)
        elif last:
            out.append(part)
    return pointer(*out)


_MESSAGES: Final = {"extra_forbidden": "This field is not part of the agent spec."}


def parse(raw: Json) -> tuple[AgentSpec | None, list[Problem]]:
    """The document as the model, or the schema problems that stop it (rule 1)."""
    if len(canonical_json(raw).encode()) > SPEC_MAX_BYTES:
        return None, [Problem("", "schema", f"The spec is larger than {SPEC_MAX_BYTES} bytes.")]
    if "apiVersion" not in raw:
        return None, [Problem("/apiVersion", "schema", f"Set apiVersion: {API_VERSION}.")]
    try:
        return AgentSpec.model_validate(raw), []
    except ValidationError as e:
        problems = [
            Problem(_pointer_of(err["loc"], raw), "schema", _MESSAGES.get(err["type"], err["msg"]))
            for err in e.errors(include_url=False)
        ]
        return None, list({(p.path, p.message): p for p in problems}.values())


def loop_kind(spec: AgentSpec) -> str:
    return spec.loop.kind if spec.loop is not None else "auto"


def modes_available(spec: AgentSpec) -> set[str]:
    """The modes a turn of this spec can take: direct always; a plan under the automatic and plan loops; helpers
    with any helper; the sandbox with a workspace."""
    out = {"direct"}
    if loop_kind(spec) in ("auto", "plan_execute"):
        out.add("plan")
    if spec.agents:
        out.add("helpers")
    if spec.sandbox is not None:
        out.add("sandbox")
    return out


def document_problems(spec: AgentSpec) -> list[Problem]:
    """Rules 2, 6, 8, 12, 13 (the ceiling against the default), 14 (the fallback against the model) and 15: what the
    document breaks on its own."""
    out: list[Problem] = []
    if spec.instructions is not None and spec.brief is not None:
        out.append(Problem("/brief", "instructions_and_brief", "Set instructions or brief, not both."))
    kind = loop_kind(spec)
    for i, h in enumerate(spec.agents or []):
        if h.use == "handoff" and kind != "swarm":
            out.append(
                Problem(pointer("agents", i, "use"), "helper_use_mismatch", "A handoff helper needs loop kind swarm.")
            )
        if h.use == "tool" and kind not in ("auto", "supervisor"):
            out.append(
                Problem(
                    pointer("agents", i, "use"),
                    "helper_use_mismatch",
                    f"A helper used as a tool needs loop kind auto or supervisor, not {kind}.",
                )
            )
    if kind == "long_running":
        if spec.sandbox is None:
            out.append(Problem("/loop", "sandbox_required", "A long-running loop needs a sandbox."))
        out.append(Problem("/loop/kind", "loop_kind_unavailable", "The long-running loop arrives in release 1.5.0."))
    if spec.output is not None and spec.output.schema_ is not None:
        schema = spec.output.schema_
        if len(canonical_json(schema).encode()) > OUTPUT_SCHEMA_MAX_BYTES:
            out.append(Problem("/output/schema", "output_schema_invalid", "The output schema is larger than 32 KiB."))
        else:
            try:
                check_schema(cast(JsonValue, schema))
            except LayoutError as e:
                out.append(Problem("/output/schema", "output_schema_invalid", str(e)))
    budget = spec.limits.budget if spec.limits is not None else None
    if budget is not None and budget.default_usd is not None and budget.default_usd > budget.ceiling_usd:
        out.append(
            Problem(
                "/limits/budget/defaultUsd",
                "budget_over_ceiling",
                f"The default budget {budget.default_usd} is above the ceiling {budget.ceiling_usd}.",
            )
        )
    fallback = (spec.model_settings or {}).get("fallback")
    if fallback is not None and fallback == spec.model:
        out.append(Problem("/modelSettings/fallback", "fallback_same", "The fallback alias is the agent's own model."))
    out.extend(_eval_problems(spec))
    return out


def _eval_problems(spec: AgentSpec) -> list[Problem]:
    if spec.evals is None:
        return []
    tools = set(spec.tool_ids or [])
    helpers = {h.id for h in spec.agents or []}
    modes = modes_available(spec)
    out: list[Problem] = []
    for i, case in enumerate(spec.evals.cases):
        e = case.expect
        if e is None:
            continue
        for key, names in (("calls", e.calls), ("notCalls", e.not_calls)):
            for j, name in enumerate(names or []):
                if name not in tools and name not in helpers:
                    out.append(
                        Problem(
                            pointer("evals", "cases", i, "expect", key, j),
                            "eval_names_unknown",
                            f"{name} is not a tool or helper of this spec.",
                        )
                    )
        if e.handoff is not None and e.handoff not in helpers:
            out.append(
                Problem(
                    pointer("evals", "cases", i, "expect", "handoff"),
                    "eval_names_unknown",
                    f"{e.handoff} is not a helper of this spec.",
                )
            )
        for j, mode in enumerate(e.mode or []):
            if mode not in modes:
                out.append(
                    Problem(
                        pointer("evals", "cases", i, "expect", "mode", j),
                        "eval_mode_unavailable",
                        f"This spec makes no {mode} mode available.",
                    )
                )
    return out


def written(raw: Json) -> Json:
    """The document as it is kept: without `apiVersion` and `id`, which export sets."""
    return {k: v for k, v in raw.items() if k not in ("apiVersion", "id")}


@dataclass(frozen=True)
class Resolved:
    """What the save looked up for the document's references, as today's version stores them."""

    skill_pins: list[Json]
    guardrail_pins: list[Json]
    widget_pins: list[Json]


def to_stored(spec: AgentSpec, raw: Json, resolved: Resolved, *, kept: Mapping[str, JsonValue]) -> Json:
    """The version a save stores for `spec`: today's keys, written from the document, plus the document itself.
    `kept` is the previous version; only what the document never holds (suggestions, the console's patterns) is
    carried over."""
    loop = spec.loop if not isinstance(spec.loop, LoopWorkflow) else None
    settings = {k: v for k, v in (spec.model_settings or {}).items() if k != "fallback"}
    out: Json = {
        "name": spec.name,
        "role": spec.role,
        "model": spec.model or "",
        "channels": list(spec.channels or ["chat"]),
        "instructions": _instructions(spec),
        "toolIds": list(spec.tool_ids or []),
        "collections": list(spec.collections or []),
        "allTeamKnowledgeBases": spec.all_team_knowledge_bases,
        "suggestions": cast(JsonValue, kept.get("suggestions") or []),
        "skillMenu": spec.skill_menu,
        "skillPins": cast(JsonValue, resolved.skill_pins),
        "guardrailPins": cast(JsonValue, resolved.guardrail_pins),
        "widgetPins": cast(JsonValue, resolved.widget_pins),
        "guardrails": {
            "redactPii": spec.privacy.mask_personal_data if spec.privacy is not None else True,
            "maxToolCallsPerTurn": loop.max_tool_calls if loop is not None else None,
            "maxModelCallsPerTurn": (loop.max_steps if loop is not None else None) or DEFAULT_STEPS,
            "maxModelCallsPerConversation": None,
            "maxCostPerConversation": None,
            "whenUnsure": spec.when_unsure,
            "blockedTopics": [],
        },
    }
    if spec.accounts:
        out["accounts"] = dict(spec.accounts)
    if settings:
        out["modelSettings"] = cast(JsonValue, settings)
    if (fallback := (spec.model_settings or {}).get("fallback")) is not None:
        out["modelFallback"] = fallback
    if spec.memory is not None:
        memory: Json = {"enabled": spec.memory.enabled}
        if spec.memory.kinds is not None:
            memory["kinds"] = list(spec.memory.kinds)
        out["memory"] = memory
    if spec.widgets is not None:
        out["widgets"] = {"compose": spec.widgets.compose, "perTurn": spec.widgets.per_turn}
    if spec.limits is not None:
        out["limits"] = _stored_limits(spec)
    if "patterns" in kept:
        out["patterns"] = kept["patterns"]
    doc = written(raw)
    out[DOCUMENT_KEY] = {"written": doc, "digests": {}}
    canon = canonical(out)
    out[DOCUMENT_KEY] = {"written": doc, "digests": {f: _digest(canon.get(f)) for f in FIELDS}}
    return out


def _instructions(spec: AgentSpec) -> str:
    if spec.instructions is not None:
        return spec.instructions
    if spec.brief is not None and spec.brief.sections:
        return "\n\n".join(f"## {s.heading}\n\n{s.text}" for s in spec.brief.sections)
    return f"You are {spec.name}. {spec.role}"


def _stored_limits(spec: AgentSpec) -> Json:
    """Today's `limits` (activities/agent_limits.py AgentLimits) for the document's: the agent's own model and
    knowledge bases are always allowed, as the save's check asks."""
    assert spec.limits is not None
    lim = spec.limits
    model = spec.model or ""
    out: Json = {
        "allowedModels": list[JsonValue](dict.fromkeys([model, *(lim.allowed_models or [])])),
        "defaultModel": model,
        "allowedKnowledgeBaseIds": list[JsonValue](
            dict.fromkeys([*(spec.collections or []), *(lim.allowed_knowledge_base_ids or [])])
        ),
        "switchableToolIds": list(lim.switchable_tool_ids or []),
        "callersMayAddInstructions": lim.callers_may_add_instructions,
    }
    if lim.budget is not None:
        out["budget"] = {
            "ceilingUsd": lim.budget.ceiling_usd,
            "defaultUsd": lim.budget.default_usd if lim.budget.default_usd is not None else lim.budget.ceiling_usd,
        }
    if lim.temperature is not None:
        low = lim.temperature.min if lim.temperature.min is not None else 0.0
        high = lim.temperature.max if lim.temperature.max is not None else 2.0
        set_to = (spec.model_settings or {}).get("temperature")
        default = min(max(float(set_to), low), high) if isinstance(set_to, int | float) else low
        out["temperature"] = {"min": low, "max": high, "default": default}
    return out


# The document's fields in the order export writes them.
FIELDS: Final = (
    "name",
    "role",
    "instructions",
    "brief",
    "promptMode",
    "model",
    "modelSettings",
    "channels",
    "toolIds",
    "collections",
    "allTeamKnowledgeBases",
    "skills",
    "skillMenu",
    "accounts",
    "guardrails",
    "privacy",
    "whenUnsure",
    "memory",
    "widgets",
    "limits",
    "loop",
    "agents",
    "sandbox",
    "hooks",
    "output",
    "evals",
)
# Kept only in the document: today's version has no key for them.
DOCUMENT_ONLY: Final = frozenset({"brief", "promptMode", "agents", "sandbox", "hooks", "output", "evals"})


def _digest(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _doc(stored: Mapping[str, JsonValue]) -> tuple[Json, Json]:
    held = stored.get(DOCUMENT_KEY)
    if not isinstance(held, dict):
        return {}, {}
    return cast(Json, held.get("written") or {}), cast(Json, held.get("digests") or {})


def canonical(stored: Mapping[str, JsonValue]) -> Json:
    """Each document field as today's stored keys give it; a field with no stored value is left out."""
    doc, _ = _doc(stored)
    caps = cast(Json, stored.get("guardrails") or {})
    out: Json = {}
    for key in ("name", "role", "instructions", "channels", "toolIds", "collections", "accounts", "skillMenu"):
        if stored.get(key) not in (None, "", [], {}):
            out[key] = stored[key]
    if stored.get("model"):
        out["model"] = stored["model"]
    if stored.get("allTeamKnowledgeBases"):
        out["allTeamKnowledgeBases"] = True
    settings = dict(cast(Json, stored.get("modelSettings") or {}))
    if stored.get("modelFallback") is not None:
        settings["fallback"] = stored["modelFallback"]
    if settings:
        out["modelSettings"] = settings
    if pins := cast(list[Json], stored.get("skillPins") or []):
        out["skills"] = [{"id": p["skillId"], "version": p["version"]} for p in pins]
    if pins := cast(list[Json], stored.get("guardrailPins") or []):
        out["guardrails"] = [
            {"id": p["guardrailId"], "version": p["version"], **({} if p.get("enabled", True) else {"enabled": False})}
            for p in pins
        ]
    if "redactPii" in caps:
        out["privacy"] = {"maskPersonalData": bool(caps["redactPii"])}
    if caps.get("whenUnsure"):
        out["whenUnsure"] = caps["whenUnsure"]
    if isinstance(stored.get("memory"), dict):
        out["memory"] = stored["memory"]
    widgets = cast(Json, stored.get("widgets") or {})
    if pins := cast(list[Json], stored.get("widgetPins") or []):
        out["widgets"] = {"pins": [{"id": p["widgetId"], "version": p["version"]} for p in pins], **widgets}
    elif widgets:
        out["widgets"] = dict(widgets)
    if isinstance(limits := stored.get("limits"), dict):
        out["limits"] = _limits_of(cast(Json, limits))
    if (loop := _loop_of(doc, caps)) is not None:
        out["loop"] = loop
    for key in DOCUMENT_ONLY:
        if key in doc:
            out[key] = doc[key]
    return out


def _limits_of(limits: Json) -> Json:
    out: Json = {}
    for key in ("budget", "allowedModels", "allowedKnowledgeBaseIds", "switchableToolIds"):
        if limits.get(key) not in (None, []):
            out[key] = limits[key]
    if isinstance(t := limits.get("temperature"), dict):
        out["temperature"] = {"min": t.get("min"), "max": t.get("max")}
    if limits.get("callersMayAddInstructions"):
        out["callersMayAddInstructions"] = True
    return out


def _loop_of(doc: Json, caps: Json) -> Json | None:
    """The loop as written, with its step and tool caps as the stored caps say now (the console edits those)."""
    loop = dict(cast(Json, doc.get("loop") or {}))
    steps, tools = caps.get("maxModelCallsPerTurn"), caps.get("maxToolCallsPerTurn")
    if loop.get("kind") == "workflow":
        return loop
    if steps not in (None, DEFAULT_STEPS):
        loop["maxSteps"] = steps
    elif loop.get("maxSteps") not in (None, DEFAULT_STEPS):
        loop.pop("maxSteps")
    if tools is not None:
        loop["maxToolCalls"] = tools
    else:
        loop.pop("maxToolCalls", None)
    if not loop:
        return None
    loop.setdefault("kind", "auto")
    return loop


def exported(stored: Mapping[str, JsonValue], agent_id: str) -> Json:
    """The document for a stored version: each field as written while the stored keys still say what they said at the
    save, else as the stored keys give it now."""
    doc, digests = _doc(stored)
    canon = canonical(stored)
    out: Json = {"apiVersion": API_VERSION, "id": agent_id}
    for field in FIELDS:
        now = canon.get(field)
        if field in digests and digests[field] == _digest(now):
            if field in doc:
                out[field] = doc[field]
        elif now is not None:
            out[field] = now
    return out


def diff(before: JsonValue, after: JsonValue, path: str = "") -> list[Json]:
    """The changes that turn `before` into `after`: one per object key added, removed or replaced, and per list item
    when both lists are the same length; a list that changed length is replaced whole."""
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[Json] = []
        for key in [*before, *(k for k in after if k not in before)]:
            at = path + pointer(key)
            if key not in after:
                out.append({"op": "remove", "path": at, "before": before[key], "after": None})
            elif key not in before:
                out.append({"op": "add", "path": at, "before": None, "after": after[key]})
            else:
                out.extend(diff(before[key], after[key], at))
        return out
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [c for i, (b, a) in enumerate(zip(before, after, strict=True)) for c in diff(b, a, path + pointer(i))]
    if before == after:
        return []
    return [{"op": "replace", "path": path, "before": before, "after": after}]


def summary(spec: AgentSpec) -> Json:
    return {
        "loopKind": loop_kind(spec),
        "tools": len(spec.tool_ids or []),
        "helpers": len(spec.agents or []),
        "evalCases": len(spec.evals.cases) if spec.evals is not None else 0,
    }
