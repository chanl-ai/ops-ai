"""platform-service's two apps. The public one serves sign-in, sessions and the key set; the internal one serves
introspection behind the service token and is bound to a port the public host never exposes (I8, I13)."""

# No `from __future__ import annotations`: routes declare dependencies on functions local to each factory, and
# FastAPI resolves string annotations against module globals, where those names do not exist.

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from ops_identity import ServiceAuth
from ops_policy import Ed25519Signer
from ops_service_kit.errors import Forbidden, Unauthorized, ValidationFailed
from ops_service_kit.http import Envelope, ListResult, error_responses, install_error_handlers, ok
from ops_service_kit.ids import new_id

from ..api_keys import ApiKeys
from ..audit_log import AuditReader
from ..auth import Auth, Issued, Keys, principal_from_claims
from ..store.audit import AuditLog
from ..store.identity import IdentityStore
from ..store.keys import KeyStore
from ..store.members import Actor, TeamStore
from ..teams import Members
from .schemas import (
    AcceptIn,
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    AuditEntryOut,
    BulkOut,
    DeleteIn,
    Health,
    Introspect,
    InviteBulkOut,
    InviteIn,
    InvitePreview,
    Jwks,
    Me,
    MemberOut,
    Principal,
    Refresh,
    RoleIn,
    SessionOut,
    SignIn,
    TeamOut,
)

ERRORS = error_responses()
KEY_ID = r"^key_[A-Za-z0-9_-]{1,60}$"
ISO_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
INVITE_TOKEN = r"^inv_[A-Za-z0-9_-]{8,64}$"


def operation_id(route: APIRoute) -> str:
    return f"{route.tags[0]}_{route.name}".lower() if route.tags else route.name


def _bearer(authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Sign in first.")
    return token


def _issued(i: Issued) -> dict[str, Any]:
    return {"token": i.token, "refreshToken": i.refresh_token, "expiresAt": i.expires_at, "principal": i.principal}


def create_public_app(
    store: IdentityStore,
    signer: Ed25519Signer,
    *,
    demo_password: str | None,
    audiences: list[str],
    cors_origins: list[str] | None = None,
    token_ttl_s: int = 900,
) -> FastAPI:
    auth = Auth(store, signer, demo_password, audiences, token_ttl_s=token_ttl_s)
    app = FastAPI(title="Ops AI platform service", version="0.1.0", generate_unique_id_function=operation_id)
    install_error_handlers(app)
    if cors_origins:
        # The console runs on another origin. Bearer tokens, not cookies, so no credentials mode.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Team-Id"],
            max_age=600,
        )
    jwks = {"keys": [signer.public_jwk()]}

    @app.get("/v1/health", tags=["health"], response_model=Health)
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/.well-known/jwks.json", tags=["platform"], response_model=Jwks)
    async def jwks_document(response: Response) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        response.headers["Cache-Control"] = "public, max-age=300"
        return jwks

    @app.post("/v1/auth/sign-in", tags=["platform"], response_model=Envelope[SessionOut], responses=ERRORS)
    async def sign_in(body: SignIn) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(_issued(await auth.sign_in(body.email, body.password, request_id=new_id("req"))))

    @app.get("/v1/auth/session", tags=["platform"], response_model=Envelope[Principal], responses=ERRORS)
    async def session(token: Annotated[str, Depends(_bearer)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        _, claims = await auth.session_of(token)
        return ok(principal_from_claims(claims))

    @app.post("/v1/auth/refresh", tags=["platform"], response_model=Envelope[SessionOut], responses=ERRORS)
    async def refresh(body: Refresh) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(_issued(await auth.refresh(body.refresh_token, request_id=new_id("req"))))

    @app.post("/v1/auth/sign-out", tags=["platform"], status_code=204, responses=ERRORS)
    async def sign_out(token: Annotated[str, Depends(_bearer)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        await auth.sign_out(token, request_id=new_id("req"))
        return Response(status_code=204)

    team_store = TeamStore(store.db)
    people = Members(team_store)

    async def claims_of(token: Annotated[str, Depends(_bearer)]) -> dict[str, Any]:
        return (await auth.session_of(token))[1]

    async def acting(
        claims: Annotated[dict[str, Any], Depends(claims_of)],
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Actor:
        """The one team this request acts in (I1): chosen by X-Team-Id among the token's teams, never named in a
        body; with no header, the token's only team."""
        named: list[Any] = claims.get("team_ids") or []
        teams = [str(t) for t in named]
        if x_team_id is None:
            if len(teams) != 1:
                raise ValidationFailed("Choose a team with the X-Team-Id header.", code="team_required")
            x_team_id = teams[0]
        elif x_team_id not in teams:
            raise Forbidden("You are not a member of that team.", code="team_forbidden")
        return Actor(str(claims["tenant_id"]), x_team_id, str(claims["sub"]), new_id("req"))

    @app.get("/v1/me", tags=["platform"], response_model=Envelope[Me], responses=ERRORS)
    async def me(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        tenant, user = str(claims["tenant_id"]), str(claims["sub"])
        found = await store.user(tenant, user)
        if found is None:
            raise Unauthorized("Sign in again.")
        teams = await team_store.teams_of(tenant, user)
        return ok(
            {
                "user": {"id": found.id, "email": found.email, "name": found.name},
                "tenantId": tenant,
                "teams": [{"id": t["id"], "name": t["name"], "role": t["role"]} for t in teams],
            }
        )

    @app.get("/v1/teams", tags=["platform"], response_model=Envelope[list[TeamOut]], responses=ERRORS)
    async def list_teams(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await team_store.teams_of(str(claims["tenant_id"]), str(claims["sub"])))

    @app.get(
        "/v1/settings/members", tags=["platform"], response_model=Envelope[ListResult[MemberOut]], responses=ERRORS
    )
    async def list_members(  # pyright: ignore[reportUnusedFunction]
        actor: Annotated[Actor, Depends(acting)],
        role: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
    ) -> Any:
        everyone = await team_store.members(actor.tenant_id, actor.team_id, roles=[], statuses=[])
        rows = [m for m in everyone if (not role or m["role"] in role) and (not status or m["status"] in status)]
        facets = {
            key: {v: sum(1 for m in everyone if m[key] == v) for v in sorted({m[key] for m in everyone})}
            for key in ("role", "status")
        }
        pagination = {
            "page": 1,
            "pageSize": len(rows),
            "total": len(rows),
            "totalPages": 1,
            "hasNext": False,
            "hasPrev": False,
        }
        return ok({"data": rows, "pagination": pagination, "facets": facets})

    @app.post(
        "/v1/settings/members/invite", tags=["platform"], response_model=Envelope[InviteBulkOut], responses=ERRORS
    )
    async def invite_members(body: InviteIn, actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await people.invite(actor, body.emails, body.role))

    @app.post("/v1/settings/members/role", tags=["platform"], response_model=Envelope[BulkOut], responses=ERRORS)
    async def change_roles(body: RoleIn, actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await people.set_role(actor, body.ids, body.role))

    @app.post("/v1/settings/members/delete", tags=["platform"], response_model=Envelope[BulkOut], responses=ERRORS)
    async def remove_members(body: DeleteIn, actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await people.remove(actor, body.ids))

    keys = ApiKeys(KeyStore(store.db), people)

    @app.get("/v1/api-keys", tags=["platform"], response_model=Envelope[list[ApiKeyOut]], responses=ERRORS)
    async def list_api_keys(actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await keys.list(actor))

    @app.post(
        "/v1/api-keys", tags=["platform"], status_code=201, response_model=Envelope[ApiKeyCreated], responses=ERRORS
    )
    async def create_api_key(body: ApiKeyIn, actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await keys.create(actor, body.name, list(body.scopes), body.expires_in_days), status=201)

    @app.post("/v1/api-keys/{key_id}/revoke", tags=["platform"], response_model=Envelope[ApiKeyOut], responses=ERRORS)
    async def revoke_api_key(  # pyright: ignore[reportUnusedFunction]
        key_id: Annotated[str, Path(pattern=KEY_ID)], actor: Annotated[Actor, Depends(acting)]
    ) -> Any:
        return ok(await keys.revoke(actor, key_id))

    reader = AuditReader(AuditLog(store.db), team_store, people)

    @app.get("/v1/audit", tags=["platform"], response_model=Envelope[ListResult[AuditEntryOut]], responses=ERRORS)
    async def read_audit(  # pyright: ignore[reportUnusedFunction]
        *,
        actor: Annotated[Actor, Depends(acting)],
        action: Annotated[str | None, Query(max_length=80)] = None,
        actor_id: Annotated[str | None, Query(alias="actor", max_length=320)] = None,
        target_kind: Annotated[str | None, Query(alias="targetKind", max_length=40)] = None,
        since: Annotated[str | None, Query(alias="from", pattern=ISO_TIME)] = None,
        until: Annotated[str | None, Query(alias="to", pattern=ISO_TIME)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 50,
    ) -> Any:
        filters = {"action": action, "actor": actor_id, "target_kind": target_kind, "from": since, "to": until}
        return ok(await reader.page(actor, filters, page, page_size))

    @app.get("/v1/invites/{token}", tags=["platform"], response_model=Envelope[InvitePreview], responses=ERRORS)
    async def read_invite(token: Annotated[str, Path(pattern=INVITE_TOKEN)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await people.preview(token))

    @app.post("/v1/invites/{token}/accept", tags=["platform"], response_model=Envelope[SessionOut], responses=ERRORS)
    async def accept_invite(  # pyright: ignore[reportUnusedFunction]
        token: Annotated[str, Path(pattern=INVITE_TOKEN)], body: AcceptIn
    ) -> Any:
        request_id = new_id("req")
        invite, user_id = await people.accept(token, body.name, request_id=request_id)
        user = await store.user(invite.tenant_id, user_id)
        if user is None:
            raise Unauthorized("Sign in again.")
        return ok(_issued(await auth.start_session(user, request_id=request_id)))

    return app


def create_internal_app(store: IdentityStore, *, services: ServiceAuth) -> FastAPI:
    """`services` trusts the calling services' keys; it is built without a tenant scope, because introspection is
    how a caller learns the tenant (I13)."""
    keys = Keys(store)
    app = FastAPI(title="Ops AI platform service (internal)", version="0.1.0", generate_unique_id_function=operation_id)
    install_error_handlers(app)

    @app.post(
        "/v1/auth/introspect",
        tags=["platform"],
        dependencies=[Depends(services.principal)],
        response_model=Envelope[Principal],
        responses=ERRORS,
    )
    async def introspect(body: Introspect) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await keys.introspect(body.api_key))

    return app
