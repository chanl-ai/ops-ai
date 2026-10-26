"""`/v1/expressions`: evaluates a workflow's formulas (the Calculate step) in the tools gateway's sandbox, for the
engine's step and the step's test box in the editor. It reads nothing and changes nothing, so anyone signed in and any
service holding `tools:view` may call it."""

# No `from __future__ import annotations`: FastAPI resolves the request model's annotations at import.

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_identity import Principal
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Envelope, Out, error_responses, ok

from .callers import tools_reader
from .expressions import MAX_FORMULAS, evaluate


class EvaluateIn(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    # Formulas by the name their value takes, run in this order; each sees the values and the earlier ones.
    expressions: dict[str, str] = Field(min_length=1, max_length=MAX_FORMULAS)
    # The step's resolved values, by name: what the formulas read.
    values: dict[str, Any] = Field(default_factory=dict)


class EvaluateOut(Out):
    out: dict[str, Any]


def expressions_router() -> APIRouter:
    r = APIRouter(
        prefix="/v1/expressions",
        tags=["expressions"],
        responses=error_responses(),
    )

    @r.post("/evaluate", response_model=Envelope[EvaluateOut])
    async def evaluate_formulas(  # pyright: ignore[reportUnusedFunction]
        body: EvaluateIn, _: Annotated[Principal, Depends(tools_reader)]
    ) -> JSONResponse:
        out, why = await evaluate(body.expressions, body.values)
        if out is None:
            raise ValidationFailed(why or "The formulas failed.", code="formula_failed")
        return ok({"out": out})

    return r
