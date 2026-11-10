"""An app's accounts under `/v1/apps/{app_id}/accounts`, the caller's own under `/v1/me/accounts`, connect links and
`/v1/connection-kinds`: the console's Apps pages and the SDK read these. An account is found only under its
own app, so an id moved to another app's address answers 404."""

# No `from __future__ import annotations`: the routes' `caller` dependency is a local of accounts_router, and FastAPI
# resolves string annotations against module globals, where it does not exist.

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from ops_service_kit.http import Envelope, error_responses, ok

from ..callers import caller_in
from ..modules.directory import Directory
from ..modules.service import Caller
from .schemas import (
    AccountDetail,
    AccountPatchIn,
    AccountTestIn,
    AnotherOwnIn,
    ConnectionKinds,
    ConnectLinkIn,
    MyAccount,
    PersonCredentialsIn,
    SignInCompleteIn,
    SignInFinished,
    SignInIn,
    SignInStart,
)
from .service import ConnectionService

ACCOUNT = "/v1/apps/{app_id}/accounts/{account_id}"


def accounts_router(service: ConnectionService, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(tags=["apps"], responses=error_responses())

    async def _of(who: Caller, app_id: str, account_id: str) -> str:
        await service.account_of(who, app_id, account_id)
        return account_id

    @r.get("/v1/connection-kinds", response_model=Envelope[ConnectionKinds])
    async def connection_kinds(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Each way an account signs in, with its fields; the console builds the form from it."""
        return ok(service.kinds())

    @r.get(ACCOUNT, response_model=Envelope[AccountDetail])
    async def get_account(app_id: str, account_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.detail(who, await _of(who, app_id, account_id)))

    @r.patch(ACCOUNT, response_model=Envelope[AccountDetail])
    async def change_account(  # pyright: ignore[reportUnusedFunction]
        app_id: str, account_id: str, body: AccountPatchIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """The account's name, sign-in, card details, sandbox flag, settings and secret parts; a secret part left out
        keeps its stored value."""
        return ok(await service.change(who, await _of(who, app_id, account_id), body.model_dump(exclude_unset=True)))

    @r.delete(ACCOUNT, status_code=204, response_class=Response)
    async def delete_account(app_id: str, account_id: str, who: Annotated[Caller, Depends(caller)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        """409 connection_in_use while a module points at it."""
        await service.delete(who, await _of(who, app_id, account_id))
        return Response(status_code=204)

    @r.post(f"{ACCOUNT}/sign-in", response_model=Envelope[SignInStart])
    async def start_sign_in(  # pyright: ignore[reportUnusedFunction]
        app_id: str, account_id: str, body: SignInIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Where to send the person's browser; it returns to the console's sign-in page with a code and state."""
        return ok(await service.start_sign_in(who, await _of(who, app_id, account_id), body.account))

    @r.post("/v1/sign-ins/complete", response_model=Envelope[SignInFinished])
    async def finish_sign_in(body: SignInCompleteIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The return page hands back what the system sent: the state with the code, or with the error it refused
        the sign-in with. The state alone names the account, so any window of the person who started finishes it,
        once. A refusal, there or at the token exchange, answers 422 sign_in_refused with details {message, who,
        providerCode, appId, app} and marks the account refused."""
        finished = await service.finish(
            who, body.state, code=body.code, error=body.error, description=body.error_description
        )
        return ok(SignInFinished(**finished).model_dump(by_alias=True))

    @r.post(f"{ACCOUNT}/test-credential", response_model=Envelope[SignInStart])
    async def check_credential(app_id: str, account_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """An admin's Test with my account of the app credential: starts a sign-in through the account's app (the
        team's own or Ops AI's) that keeps no token; the return page finishes it on /v1/sign-ins/complete. Only an
        admin, as only an admin sets app credentials."""
        account = await _of(who, app_id, account_id)
        return ok(await service.start_sign_in(who, account, "team", check=True))

    @r.post(f"{ACCOUNT}/test", response_model=Envelope[AccountDetail])
    async def test_account(  # pyright: ignore[reportUnusedFunction]
        app_id: str, account_id: str, body: AccountTestIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Reads the account's test address signed in with the caller's own sign-in or the team's, and stores the
        result as the account's `health`. A failed test answers 200 with the failure in `health`."""
        return ok(await service.test(who, await _of(who, app_id, account_id), body.account))

    @r.put(f"{ACCOUNT}/default", response_model=Envelope[AccountDetail])
    async def pin_default(app_id: str, account_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Makes this account the caller's default of its app: their calls that name no account use it."""
        return ok(await service.pin_default(who, await _of(who, app_id, account_id)))

    @r.post(f"{ACCOUNT}/sign-out", response_model=Envelope[AccountDetail])
    async def sign_out(app_id: str, account_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Ends the team's sign-in on the account; each person's own stays."""
        return ok(await service.sign_out(who, await _of(who, app_id, account_id)))

    @r.get("/v1/me/accounts", response_model=Envelope[list[MyAccount]])
    async def my_accounts(who: Annotated[Caller, Depends(caller)], every: bool = False) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The caller's own sign-ins on their team's accounts: Your connections in the person menu. With
        `every`, also each account of the team they can connect themselves and have not."""
        return ok(await service.mine(who, every=every))

    @r.put("/v1/me/accounts/{account_id}/credentials", response_model=Envelope[MyAccount])
    async def give_own_credentials(  # pyright: ignore[reportUnusedFunction]
        account_id: str, body: PersonCredentialsIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """The caller's own key, password or token on an account each person signs in to, replacing any they
        gave before; answers their row in Your connections, never the values."""
        return ok(await service.give_own(who, account_id, body.credentials))

    @r.post("/v1/me/accounts/{account_id}/another", response_model=Envelope[SignInStart])
    async def add_own_account(  # pyright: ignore[reportUnusedFunction]
        account_id: str, who: Annotated[Caller, Depends(caller)], body: AnotherOwnIn | None = None
    ) -> JSONResponse:
        """Add another account of the caller's own on this account's app, through the same auth config: where to
        send the browser. The body names it and says where it signs in (409 account_name_taken for a name another
        account of the app holds); with no body it is "<name>'s other account" and signs in where this account does.
        Signing in as an identity the caller already linked updates that account instead."""
        given = body.model_dump() if body is not None else None
        return ok(await service.add_own_account(who, account_id, given))

    @r.delete("/v1/me/accounts/{account_id}", status_code=204, response_class=Response)
    async def disconnect(account_id: str, who: Annotated[Caller, Depends(caller)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Disconnect: deletes the caller's own sign-in, revoking it at the system when the account names a revocation
        address, so their next call asks them to connect again."""
        await service.disconnect(who, account_id)
        return Response(status_code=204)

    @r.post("/v1/connect-links/sign-in", response_model=Envelope[SignInStart])
    async def open_connect_link(body: ConnectLinkIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Starts the sign-in a connect link asks for, for the one person it was made for."""
        return ok(await service.open_link(who, body.link))

    return r
