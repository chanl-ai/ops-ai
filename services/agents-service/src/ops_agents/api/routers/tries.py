"""GET /v1/try-targets: what a builder can try from a skill's side panel or a workflow step, as paths of tool steps.
A skill gives one path per way its `if`s can go (app/try_paths.py); a workflow step gives one path of that one step.
Each tool step comes with its access, the values a call would send and a sample result: the tool's last answer in
one of the team's live runs, else a skeleton of its output schema, else empty. The try itself runs in tools-service
(`POST /v1/tool-modules/tries`), where a write is only planned until the person confirms it.

Nothing here writes: no version, run, thread or working copy is made or changed. Reads only this service's rows and
the tool directory, so it answers with no request transaction open while tools-service is asked."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_engine.store import RunStore
from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.http import Envelope, Json, JsonValue, Out
from ops_service_kit.narrow import json_object

from ...app import try_paths
from ...app.skill_content import program_of
from ...store.engine import EngineTransactions
from ...store.tenancy import current_team
from ..auth import Principal, principal, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..skills import skills
from .engine import definitions

router = APIRouter()
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

SampleFrom = Literal["last_run", "schema", "none"]
TOOL_NODE = "ops.action.tool"


class TryStep(Out):
    key: str
    number: int
    do: str
    # The tool the step calls; none for a step the model does itself, which a try shows and does not run.
    tool: str | None = None
    access: str | None = None
    # The step's `if` and which way this path takes it.
    test: str | None = None
    holds: bool | None = None
    input: Json = Field(default_factory=Json)
    sample: JsonValue = None
    sample_from: SampleFrom = "none"
    # A workflow step's own account per app, which the picker starts from.
    accounts: dict[str, str] = Field(default_factory=dict[str, str])


class TryPath(Out):
    id: str
    label: str
    ends: str
    steps: list[TryStep]


class TryTargets(Out):
    kind: Literal["skill", "workflow_step"]
    id: str
    name: str
    paths: list[TryPath]
    # More paths than are listed: the list holds the first.
    more: bool = False


def skeleton(schema: object, depth: int = 0) -> JsonValue:
    """A sample shaped like `schema`: each property with an empty value of its type, so a tool with no answer yet
    still offers its fields. A schema this cannot read gives an empty object."""
    s = json_object(schema)
    kind = s.get("type")
    if kind == "object" or "properties" in s:
        props = json_object(s.get("properties"))
        return {k: skeleton(v, depth + 1) for k, v in props.items()} if depth < 4 else {}
    if kind == "array":
        return [skeleton(s.get("items"), depth + 1)] if depth < 4 else []
    return {"string": "", "integer": 0, "number": 0, "boolean": False}.get(str(kind))


def _fields(schema: Json) -> Json:
    """The values a call would send when nothing names them: each input field's default, else empty."""
    props = json_object(schema.get("properties"))
    out: Json = {}
    for name, spec in props.items():
        s = json_object(spec)
        out[name] = s.get("default", "")
    return out


async def _step(rt: Runtime, runs: RunStore, team: str, step: TryStep) -> TryStep:
    if step.tool is None:
        return step
    ops = {o.name: o for o in await rt.directory().operations()}
    found = ops.get(step.tool)
    policy = await rt.tools.tool_policy(step.tool) if rt.tools is not None else None
    access = str(policy["access"]) if policy is not None else (found.access if found else "unknown")
    given = step.input or (_fields(json_object(found.input_schema)) if found else {})
    last = await runs.last_tool_output(team, step.tool)
    schema = policy.get("outputSchema") if policy is not None else None
    if last is not None:
        sample, source = last, "last_run"
    elif isinstance(schema, dict) and schema:
        sample, source = skeleton(schema), "schema"
    else:
        sample, source = {}, "none"
    return step.model_copy(update={"access": access, "input": given, "sample": sample, "sample_from": source})


async def _skill(rt: Runtime, me: Principal, skill_id: str) -> TryTargets:
    reg = skills(rt)
    row = await reg.row(skill_id)
    require_builder(me, area="skills", team_id=row.team_id, action="edit", what=f"skill {row.slug}")
    newest = (await reg.versions(skill_id))[0]
    program = program_of(newest.content)
    if program is None or not program.steps:
        raise ValidationFailed("This skill has no steps to try; write its steps first.", code="no_steps")
    found, more = try_paths.paths(program)
    runs = RunStore(EngineTransactions(rt.db))
    team = row.team_id or current_team() or ""
    out: list[TryPath] = []
    for p in found:
        steps = [
            await _step(
                rt,
                runs,
                team,
                TryStep(key=f"{p.id}:{s.number}", number=s.number, do=s.do, tool=s.tool, test=s.test, holds=s.holds),
            )
            for s in p.steps
        ]
        out.append(TryPath(id=p.id, label=p.label, ends=p.ends, steps=steps))
    return TryTargets(kind="skill", id=skill_id, name=row.slug, paths=out, more=more)


async def _workflow_step(rt: Runtime, me: Principal, workflow_id: str, node_id: str) -> TryTargets:
    store = definitions(rt)
    row = await store.row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    require_builder(me, area="workflows", team_id=row.team_id, action="save", what="this workflow")
    copy = await store.working_copy(workflow_id, team=current_team())
    held = copy.definition if copy is not None and copy.base_version >= row.version else row.definition
    listed = held.get("nodes")
    nodes = [json_object(n) for n in listed if isinstance(n, dict)] if isinstance(listed, list) else []
    node = next((n for n in nodes if n.get("id") == node_id), None)
    if node is None:
        raise NotFound(f"Step {node_id}")
    if node.get("type") != TOOL_NODE:
        raise ValidationFailed("Only a step that calls a tool can be tried.", code="not_a_tool_step")
    params = json_object(node.get("parameters"))
    given = json_object(params.get("input"))
    accounts = params.get("accounts")
    named = {str(k): str(v) for k, v in json_object(accounts).items() if v} if isinstance(accounts, dict) else {}
    step = TryStep(
        key=node_id,
        number=1,
        do=str(node.get("name") or node_id),
        tool=str(params.get("operation") or "") or None,
        input=given,
        accounts=named,
    )
    team = row.team_id or current_team() or ""
    tried = await _step(rt, RunStore(EngineTransactions(rt.db)), team, step)
    path = TryPath(id="step", label=tried.do, ends="done", steps=[tried])
    return TryTargets(kind="workflow_step", id=workflow_id, name=row.name, paths=[path])


@router.get("/v1/try-targets", response_model=Envelope[TryTargets])
async def try_targets(
    rt: Rt,
    me: Me,
    skill: Annotated[str | None, Query(max_length=80)] = None,
    workflow: Annotated[str | None, Query(max_length=80)] = None,
    step: Annotated[str | None, Query(max_length=80)] = None,
) -> JSONResponse:
    """The paths a builder can try: `skill` for a skill's paths, or `workflow` and `step` for one tool step of a
    workflow. A builder of the skill's or workflow's team only (403); the samples are that team's own runs' answers."""
    if skill is not None and workflow is None:
        return ok((await _skill(rt, me, skill)).model_dump(by_alias=True))
    if workflow is not None and step is not None and skill is None:
        return ok((await _workflow_step(rt, me, workflow, step)).model_dump(by_alias=True))
    raise ValidationFailed("Name a skill, or a workflow and one of its steps.", code="target_required")
