"""`/v1/send-policy`: the acting team's sending policy (c-300), the written rules check before sending judges each write
against. Every member reads it (`workflows.view`); whoever manages the team's workflow settings (`workflows.manage`)
saves a new version, which the next write is judged against."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import, and
# `caller` is local to the router factory.
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import can
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Envelope, ok

from .callers import caller_in
from .modules.directory import Directory
from .modules.routes import ERRORS, _operation_id  # pyright: ignore[reportPrivateUsage]
from .modules.service import Caller
from .store.send_policies import SendPolicies


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SendPolicyIn(_Wire):
    text: str = Field(min_length=1, max_length=20_000)


class SendPolicyView(_Wire):
    version: int
    text: str
    saved_by: str
    saved_at: str


def _view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return SendPolicyView(**{k: row[k] for k in ("version", "text", "saved_by", "saved_at")}).model_dump(by_alias=True)


def send_policy_router(store: SendPolicies, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(
        prefix="/v1/send-policy", tags=["send-policy"], responses=ERRORS, generate_unique_id_function=_operation_id
    )

    def _principal(who: Caller) -> Any:
        if who.principal is None:
            raise Forbidden("A person or service token is needed for the sending policy.")
        return who.principal

    @r.get("", response_model=Envelope[SendPolicyView | None])
    async def get_send_policy(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's newest sending policy; null when it has none (nothing is judged)."""
        can(_principal(who), "workflows", "view", team=who.team.id, what="the sending policy")
        return ok(_view(await store.current(who.tenant_id, who.team.id)))

    @r.put("", response_model=Envelope[SendPolicyView])
    async def save_send_policy(body: SendPolicyIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Saves the next version; writes from then on are judged against it."""
        can(_principal(who), "workflows", "manage", team=who.team.id, what="the sending policy")
        return ok(_view(await store.save(who.tenant_id, who.team.id, body.text, by=who.name)))

    return r
