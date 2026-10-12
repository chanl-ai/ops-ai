"""GET /v1/model-aliases: the chat aliases an agent may name, so the console's agent picker offers exactly what a
publish request accepts. Read through `rt.model_aliases`, the port the publish check uses."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Envelope, ModelAlias

router = APIRouter(prefix="/v1/model-aliases", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


@router.get("", response_model=Envelope[list[ModelAlias]])
async def list_model_aliases(rt: Rt) -> JSONResponse:
    assert rt.model_aliases is not None
    return ok(await rt.model_aliases.chat_models())
