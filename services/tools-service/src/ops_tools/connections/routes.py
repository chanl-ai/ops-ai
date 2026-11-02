"""`/v1/connections` and `/v1/connection-kinds` (c-330): the console's Connections pages and the SDK read these."""

# No `from __future__ import annotations`: the routes' `caller` dependency is a local of connections_router, and FastAPI
# resolves string annotations against module globals, where it does not exist.

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from ops_service_kit.http import Envelope, error_responses, ok

from ..callers import caller_in
from ..environments import ConnectionEnvironment as Environment
from ..modules.directory import Directory
from ..modules.service import Caller
from .schemas import (
    ConnectionDetail,
    ConnectionKinds,
    ConnectionList,
    ConnectionPatchIn,
    ConnectionTestIn,
    ConnectLinkIn,
    CredentialCheck,
    CredentialCheckIn,
    EnvironmentIn,
    McpConnectionIn,
    MyConnection,
    NewConnectionIn,
    PersonCredentialsIn,
    SignInCompleteIn,
    SignInIn,
    SignInStart,
)
from .service import ConnectionService


def connections_router(service: ConnectionService, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(tags=["connections"], responses=error_responses())

    @r.get("/v1/connection-kinds", response_model=Envelope[ConnectionKinds])
    async def kinds(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Each way a connection signs in, with its fields; the console builds the form from it."""
        return ok(service.kinds())

    @r.get("/v1/connections", response_model=Envelope[ConnectionList])
    async def list_connections(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
        search: str = "",
    ) -> JSONResponse:
        return ok(await service.list(who, page=page, page_size=page_size, search=search))

    @r.post("/v1/connections", response_model=Envelope[ConnectionDetail], status_code=201)
    async def create_connection(body: NewConnectionIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.create(who, body.model_dump()), 201)

    @r.get("/v1/me/connections", response_model=Envelope[list[MyConnection]])
    async def my_connections(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)], every: bool = False
    ) -> JSONResponse:
        """The caller's own sign-ins on their team's connections (c-558): Your connections in the person menu. With
        `every`, also each connection of the team they can connect themselves and have not (c-595)."""
        return ok(await service.mine(who, every=every))

    @r.put("/v1/me/connections/{connection_id}/credentials", response_model=Envelope[MyConnection])
    async def give_own_credentials(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: PersonCredentialsIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """The caller's own key, password or token on a connection each person signs in to (c-595), replacing any they
        gave before; answers their row in Your connections, never the values."""
        return ok(await service.give_own(who, connection_id, body.environment, body.credentials))

    @r.delete("/v1/me/connections/{connection_id}", status_code=204, response_class=Response)
    async def disconnect(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, environment: Environment, who: Annotated[Caller, Depends(caller)]
    ) -> Response:
        """Disconnect: deletes the caller's own sign-in in `environment`, revoking it at the system when the
        connection names a revocation address, so their next call asks them to connect again."""
        await service.disconnect(who, connection_id, environment)
        return Response(status_code=204)

    # Before the routes under /v1/connections/{connection_id}, which would take "connect-links" as an id.
    @r.post("/v1/connections/connect-links/sign-in", response_model=Envelope[SignInStart])
    async def open_connect_link(body: ConnectLinkIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Starts the sign-in a connect link asks for, for the one person it was made for (c-558)."""
        return ok(await service.open_link(who, body.link))

    @r.post("/v1/connections/mcp", response_model=Envelope[ConnectionDetail], status_code=201)
    async def connect_mcp(body: McpConnectionIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """An MCP server's connection, its sign-in found from the server's 401 and metadata (c-331)."""
        return ok(await service.connect_mcp(who, body.model_dump()), 201)

    @r.get("/v1/connections/{connection_id}", response_model=Envelope[ConnectionDetail])
    async def get_connection(connection_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.detail(who, connection_id))

    @r.patch("/v1/connections/{connection_id}", response_model=Envelope[ConnectionDetail])
    async def change_connection(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: ConnectionPatchIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.change(who, connection_id, body.model_dump(exclude_unset=True)))

    @r.put("/v1/connections/{connection_id}/environments/{environment}", response_model=Envelope[ConnectionDetail])
    async def set_environment(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, environment: str, body: EnvironmentIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """One environment's settings and secret parts; a secret part left out keeps its stored value."""
        return ok(await service.set_environment(who, connection_id, environment, body.model_dump()))

    @r.delete("/v1/connections/{connection_id}", status_code=204, response_class=Response)
    async def delete_connection(connection_id: str, who: Annotated[Caller, Depends(caller)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        """409 connection_in_use while a module points at it."""
        await service.delete(who, connection_id)
        return Response(status_code=204)

    @r.post("/v1/connections/{connection_id}/sign-in", response_model=Envelope[SignInStart])
    async def start_sign_in(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: SignInIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Where to send the person's browser; it returns to the console's sign-in page with a code and state."""
        return ok(await service.start_sign_in(who, connection_id, body.environment, body.account))

    @r.post("/v1/connections/{connection_id}/sign-in/complete", response_model=Envelope[ConnectionDetail])
    async def complete_sign_in(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: SignInCompleteIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """The console hands back the code and state; only the person who started may finish, once."""
        return ok(await service.complete_sign_in(who, connection_id, body.state, body.code))

    @r.post("/v1/connections/{connection_id}/test-credential", response_model=Envelope[SignInStart | CredentialCheck])
    async def check_credential(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: CredentialCheckIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """An admin's Test with my account of the app credential: signs in through the environment's app (the team's
        own or Ops AI's) and answers whether it worked and as whom, keeping no token. Only an admin, as only an admin
        sets app credentials."""
        if body.state is not None and body.code is not None:
            return ok(await service.check_credential(who, connection_id, body.state, body.code))
        return ok(await service.start_sign_in(who, connection_id, body.environment, "team", check=True))

    @r.post("/v1/connections/{connection_id}/test", response_model=Envelope[ConnectionDetail])
    async def test_connection(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: ConnectionTestIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Reads the environment's test address signed in with the caller's own account or the team's, and stores the
        result as the connection's `health` (c-558). A failed test answers 200 with the failure in `health`."""
        return ok(await service.test(who, connection_id, body.environment, body.account))

    @r.put("/v1/connections/{connection_id}/default", response_model=Envelope[ConnectionDetail])
    async def pin_default(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Makes this account the caller's default of its app (c-608): their calls that name no account use it."""
        return ok(await service.pin_default(who, connection_id))

    @r.post("/v1/connections/{connection_id}/sign-out", response_model=Envelope[ConnectionDetail])
    async def sign_out(  # pyright: ignore[reportUnusedFunction]
        connection_id: str, body: SignInIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.sign_out(who, connection_id, body.environment))

    return r
