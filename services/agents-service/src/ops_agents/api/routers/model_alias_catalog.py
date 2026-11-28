"""GET /v1/model-aliases: the chat aliases an agent may name, so the console's agent picker offers exactly what a
publish request accepts. Read through `rt.model_aliases`, the port the publish check uses, which asks models-service,
so the route reads no row and takes no request transaction (`Tx`)."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope

from ..auth import Principal, principal, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import ModelAlias, ModelAliasKnobs

router = APIRouter(prefix="/v1/model-aliases", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


@router.get("", response_model=Envelope[list[ModelAlias]])
async def list_model_aliases(rt: Rt, _: Annotated[Principal, Depends(reader_of("agents"))]) -> JSONResponse:
    assert rt.model_aliases is not None
    return ok(await rt.model_aliases.chat_models())


@router.get("/{name}/knobs", response_model=Envelope[ModelAliasKnobs])
async def model_alias_knobs(name: str, rt: Rt, _: Annotated[Principal, Depends(reader_of("agents"))]) -> JSONResponse:
    """The settings an agent on alias `name` may save: only the knobs its model takes, each with its range and catalog
    default, for the agent page's model settings; 422 `unknown_model_alias` for an alias models-service does not
    serve."""
    assert rt.model_aliases is not None
    return ok(await rt.model_aliases.knobs(name))
