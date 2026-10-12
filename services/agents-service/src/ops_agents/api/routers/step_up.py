"""Step-up in dev auth mode: the console's "Confirm it is you" re-authenticates here and gets a signed step-up token
for the calling person, which money decisions then verify (ops_policy.step_up)."""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime
from typing import Annotated, TypeAlias
from urllib.parse import unquote

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_contracts.chat import WireModel
from ops_policy import STEP_UP_TTL_S, mint_step_up
from ops_service_kit.errors import Unauthorized

from ..auth import DEV_PASSWORD, DEV_TOTP, Principal, principal, step_up_signer
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Envelope, StepUpToken

router = APIRouter(prefix="/v1/auth", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class StepUpInput(WireModel):
    password: str
    code: str | None = None


class SsoStepUpInput(WireModel):
    code: str


def _minted(rt: Runtime, subject: str) -> dict[str, str]:
    issued = datetime.now(UTC)
    token = mint_step_up(subject, step_up_signer(rt), now=issued.timestamp())
    expires = datetime.fromtimestamp(int(issued.timestamp()) + STEP_UP_TTL_S, UTC).isoformat().replace("+00:00", "Z")
    return {"token": token, "expiresAt": expires}


@router.post("/step-up", response_model=Envelope[StepUpToken])
async def step_up(rt: Rt, me: Me, body: StepUpInput) -> JSONResponse:
    if not secrets.compare_digest(body.password, DEV_PASSWORD):
        raise Unauthorized("That password is not right.")
    if body.code is not None and not secrets.compare_digest(body.code.replace(" ", ""), DEV_TOTP):
        raise Unauthorized("That code is not right.")
    return ok(_minted(rt, me.email))


@router.post("/step-up/sso", response_model=Envelope[StepUpToken])
async def sso_step_up(rt: Rt, me: Me, body: SsoStepUpInput) -> JSONResponse:
    """The identity provider's step-up callback code. The dev mock IdP's code is the base64 of the account it
    confirmed, so this checks that account is the caller; a real IdP adapter verifies its signed assertion instead."""
    try:
        confirmed = base64.b64decode(unquote(body.code), validate=True).decode().strip().lower()
    except (ValueError, UnicodeDecodeError) as e:
        raise Unauthorized("The identity provider's answer could not be read.") from e
    if not secrets.compare_digest(confirmed, me.email.lower()):
        raise Unauthorized("The identity provider confirmed a different account.")
    return ok(_minted(rt, me.email))
