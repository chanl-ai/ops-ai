"""GET /health: 200 when the process, the database and the graph runtime are up; 503 with the reason when the graph
runtime did not start (no model key), so a load balancer or a person sees the degraded state instead of a green
check over routes that answer 503."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope

from ...store.base import ping
from ..deps import Runtime, runtime
from ..envelope import error_body, ok
from ..schemas import Out

router = APIRouter()


class HealthStatus(Out):
    status: str
    database: str
    model: str


@router.get("/health", response_model=Envelope[HealthStatus])
async def health(rt: Annotated[Runtime, Depends(runtime)]) -> JSONResponse:
    await ping(rt.db)
    if rt.ports is None or not rt.graphs:
        reason = rt.model_error or "The graph runtime did not start."
        body = error_body(503, "degraded", reason)
        body["error"]["details"] = {"database": "ok", "model": reason}
        return JSONResponse(body, status_code=503)
    return ok({"status": "ok", "database": "ok", "model": "ok"})
