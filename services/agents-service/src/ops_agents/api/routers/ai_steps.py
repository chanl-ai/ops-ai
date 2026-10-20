"""`/v1/ai-steps/{step}`: a workflow AI step's answer for an agent or an outside caller (c-298, tick 30).

Classify, Summarise, Extract from text and Draft run here exactly as a workflow step runs them (ops_engine.ai_steps.run
over the same prompt port), with the step's settings in the body and the text to read. The answer names the port a
step would leave by. Running one is `workflows.run` in the acting team, and it follows that team's aiSteps and
aiStepsMaskPersonalData, read live, as a step does."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

import jsonschema
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_documents_client import DocumentNotFound, DocumentsClient
from ops_engine import ai_steps, default_registry
from ops_service_kit.errors import ServiceUnavailable, TooManyRequests, Unprocessable
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id

from ...store.tenancy import current_team, current_tenant
from ..ai_steps_gate import OFF, TeamRules
from ..auth import Principal, caller_in, caller_of
from ..deps import Runtime, runtime
from ..engine_agents import KernelPrompts
from ..engine_documents import type_fields
from ..envelope import ok
from ..widget_sessions import RateLimit

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("workflows"))]  # noqa: UP040

router = APIRouter(prefix="/v1/ai-steps")

# The route's name for each AI step type; the type's own parameter schema checks the settings.
STEPS: dict[str, str] = {
    "classify": "ops.ai.classify",
    "summarise": "ops.ai.summarise",
    "extract-text": "ops.ai.extractText",
    "draft": "ops.ai.draft",
}
Step = Literal["classify", "summarise", "extract-text", "draft"]

# Calls a minute per team, in this process (as the widget's limits): models-service budgets the service's model key, so
# without this one team's caller could spend it for every team.
calls = RateLimit()


class AiStepIn(WireModel):
    # What the step reads: text as it is, any other value as JSON.
    text: Any = Field(description="The text to read; any other value is read as JSON.")
    # The step's settings as a workflow step holds them (categories, fields, instructions, model, ...).
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])


class AiStepOut(WireModel):
    # The port a workflow step would leave by: a category, otherwise, ok or error.
    port: str
    output: dict[str, Any]


@router.post("/{step}", response_model=Envelope[AiStepOut])
async def run_ai_step(rt: Rt, me: Me, step: Step, body: AiStepIn) -> JSONResponse:
    """One AI step's answer; 422 `ai_steps_off` where the team has AI steps off, `text_too_long` past the service's
    bound, `invalid_settings` naming a setting the step's type refuses, `document_type_not_found` for a document type
    the team cannot read; 429 past the team's calls a minute; 503 with no model configured."""
    team = current_team() or me.team_id
    if not team:
        raise Unprocessable("Choose a team with the X-Team-Id header; AI steps follow a team's settings.")
    can(caller_of(me), "workflows", "run", team=team, what="an AI step")
    rules = TeamRules(rt.policies, team)
    if not (await rules.rules(None)).allowed:
        # A feature the team has off (register row E03), refused as a save of one is: not an access rule.
        raise Unprocessable(OFF, code="ai_steps_off")
    type_id = STEPS[step]
    # The newest version of the type, as a step saved now would use.
    registry = default_registry()
    versions = registry.versions(type_id)
    node_type = registry.find(type_id, versions[-1]) if versions else None
    if node_type is None:
        raise ServiceUnavailable(f"This service has no {step} step.")
    if len(ai_steps.message_of(body.text)) > rt.settings.ai_step_max_text_chars:
        raise Unprocessable(
            f"The text is longer than {rt.settings.ai_step_max_text_chars} characters.", code="text_too_long"
        )
    params = {**body.settings, "text": body.text}
    problems = sorted(
        cast(Any, jsonschema.Draft202012Validator(dict(node_type.parameters))).iter_errors(params),
        key=lambda e: str(e.path),
    )
    if problems:
        where = ".".join(str(p) for p in problems[0].path) or "settings"
        raise Unprocessable(f"{where}: {problems[0].message}", code="invalid_settings")
    if rt.ports is None:
        raise ServiceUnavailable(rt.model_error or "No model is configured.")
    params = await _with_fields(rt, team, params)
    if (wait := calls.hit(f"{current_tenant()}:{team}", rt.settings.ai_step_calls_per_minute)) is not None:
        raise TooManyRequests(
            f"This team made {rt.settings.ai_step_calls_per_minute} AI step calls this minute; try again in "
            f"{int(wait) + 1} seconds.",
            retry_after_s=int(wait) + 1,
        )
    port, output = await ai_steps.run(
        type_id,
        params,
        KernelPrompts(rt.ports, rt.settings.model_alias, rules),
        turn_id=new_id("ai"),
    )
    return ok(AiStepOut(port=port, output=output).model_dump(by_alias=True))


async def _with_fields(rt: Runtime, team: str, params: dict[str, Any]) -> dict[str, Any]:
    """A named document type's fields, read as the caller's team the way a step reads them as its run's (one lookup,
    ai_steps.resolve_fields), so the route and a step answer alike."""
    if not params.get("documentType") or params.get("fields"):
        return params
    if not rt.settings.documents_url:
        raise ServiceUnavailable("Document types are read from documents-service, which this service cannot reach.")
    client = DocumentsClient.from_settings(rt.settings, service="agents", scopes=["documents:view"])
    try:
        return await ai_steps.resolve_fields(
            params, lambda type_id, version: type_fields(client, team, type_id, version)
        )
    except (DocumentNotFound, LookupError) as e:
        raise Unprocessable(str(e), code="document_type_not_found") from e
    finally:
        await client.aclose()
