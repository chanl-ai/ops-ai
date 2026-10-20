"""platform-service's two apps. The public one serves sign-in, sessions and the key set; the internal one serves
introspection behind the service token and is bound to a port the public host never exposes (I8, I13)."""

# No `from __future__ import annotations`: routes declare dependencies on functions local to each factory, and
# FastAPI resolves string annotations against module globals, where those names do not exist.

from typing import Annotated, Any, Literal
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, Header, Path, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute

from ops_access import ACTIONS, ANY_TEAM, AREAS, SECURITY_TEAM_ACTIONS
from ops_identity import ServiceAuth, service_verifiers
from ops_policy import STEP_UP_TTL_S, Ed25519Signer
from ops_service_kit.errors import Forbidden, Unauthorized, ValidationFailed
from ops_service_kit.http import (
    Envelope,
    ListResult,
    OptionsPage,
    error_responses,
    install_error_handlers,
    ok,
    options_page,
    options_window,
)
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from ops_signin import PasswordHasher

from ..access_check import AccessCheck
from ..api_keys import ApiKeys
from ..audit_log import AuditReader
from ..auth import Auth, Issued, Keys, principal_from_claims
from ..passwords import Passwords, email_key_from
from ..policies import Policies
from ..roles import Roles
from ..signin_options import SignInOptions
from ..signin_settings import SignInSettings
from ..sso import Sso
from ..store.audit import AuditLog
from ..store.holders import HolderStore
from ..store.identity import IdentityStore
from ..store.keys import KeyStore
from ..store.members import Actor, TeamStore
from ..store.policies import PolicyStore
from ..store.roles import RoleStore
from ..store.signin import SignInStore
from ..store.teams import TeamAdminStore
from ..store.workspace import WorkspaceStore
from ..team_admin import TeamAdmin
from ..teams import Members
from .schemas import (
    DOMAIN,
    AcceptIn,
    AccessCheckIn,
    AccessCheckOut,
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    ApiKeySummary,
    AuditKind,
    AuditPage,
    BulkOut,
    DeleteIn,
    ForgotIn,
    Health,
    HoldersOut,
    Introspect,
    InviteBulkOut,
    InviteIn,
    InvitePreview,
    Jwks,
    Me,
    MemberOut,
    OptionsIn,
    OptionsOut,
    PermissionsOut,
    PersonName,
    PolicyIn,
    PolicyOut,
    Principal,
    ProviderIn,
    ProviderOut,
    Refresh,
    ResetIn,
    RoleDetail,
    RoleIn,
    RoleOut,
    SessionOut,
    SignIn,
    SsoCompleteIn,
    SsoStarted,
    SsoStartIn,
    StepUpIn,
    StepUpOut,
    StepUpSsoStartIn,
    TeamIn,
    TeamName,
    TeamOut,
    TeamRenameIn,
    WhyOut,
    WorkspaceNameOut,
    WorkspaceRenameIn,
    WorkspaceTeamOut,
    WorkspaceTeamsIn,
    WorkspaceTeamsOut,
)

ERRORS = error_responses()
KEY_ID = r"^key_[A-Za-z0-9_-]{1,60}$"
ISO_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"
INVITE_TOKEN = r"^inv_[A-Za-z0-9_-]{8,64}$"
RECORD_ID = r"^[A-Za-z0-9_-]{1,64}$"


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
    step_up_ttl_s: int = STEP_UP_TTL_S,
    security_team: str = "team_security",
    signin: SignInOptions | None = None,
    services: ServiceAuth | None = None,
) -> FastAPI:
    """`signin` unset takes its values from settings, with no mail sender and no public or console URL. `services`
    verifies the service tokens the few routes open to services accept (a policy read); unset, settings' keys."""
    sign = signin or SignInOptions.from_settings(Settings())
    signin_store = SignInStore(store.db, security_team=security_team)
    passwords = Passwords(
        identity=store,
        store=signin_store,
        hasher=PasswordHasher(iterations=sign.password_iterations),
        demo_password=demo_password,
        min_length=sign.password_min_length,
        mail=sign.mail,
        console_url=sign.console_url,
        reset_ttl_s=sign.reset_ttl_s,
        email_key=email_key_from(signer.private_text()),
        limits=sign.limits,
    )
    auth = Auth(
        store,
        signer,
        passwords,
        audiences,
        token_ttl_s=token_ttl_s,
        step_up_ttl_s=step_up_ttl_s,
        workspace=WorkspaceStore(store.db, fallback_security_team=security_team),
    )
    sso = Sso(
        auth=auth,
        identity=store,
        store=signin_store,
        http=httpx.AsyncClient(timeout=15, transport=sign.transport),
        public_url=sign.public_url,
        console_url=sign.console_url,
        secrets=sign.secrets,
        flow_ttl_s=sign.flow_ttl_s,
        sp_key=sign.saml_sp_key,
        sp_certificate=sign.saml_sp_certificate,
    )
    app = FastAPI(title="Ops AI platform service", version="0.1.0", generate_unique_id_function=operation_id)
    install_error_handlers(app)
    if cors_origins:
        # The console runs on another origin. Bearer tokens, not cookies, so no credentials mode.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
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

    @app.post("/v1/auth/step-up", tags=["platform"], response_model=Envelope[StepUpOut], responses=ERRORS)
    async def step_up(body: StepUpIn, token: Annotated[str, Depends(_bearer)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The signed-in person re-enters their password and gets a five-minute step-up token for money decisions."""
        issued = await auth.step_up(token, body.password, request_id=new_id("req"))
        return ok({"token": issued.token, "expiresAt": issued.expires_at})

    @app.post("/v1/auth/sign-out", tags=["platform"], status_code=204, responses=ERRORS)
    async def sign_out(token: Annotated[str, Depends(_bearer)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        await auth.sign_out(token, request_id=new_id("req"))
        return Response(status_code=204)

    @app.post("/v1/auth/options", tags=["platform"], response_model=Envelope[OptionsOut], responses=ERRORS)
    async def sign_in_options(body: OptionsIn) -> Any:  # pyright: ignore[reportUnusedFunction]
        """How an email signs in: a password, the workspace's SSO provider, or both. It reads the email's domain only,
        so it says nothing about whether an account exists."""
        return ok(await sso.options(body.email))

    @app.post("/v1/auth/sso/start", tags=["platform"], response_model=Envelope[SsoStarted], responses=ERRORS)
    async def sso_start(body: SsoStartIn) -> Any:  # pyright: ignore[reportUnusedFunction]
        """Where to send the browser to sign in at the email domain's provider, and the flow key that browser keeps
        to finish."""
        started = await sso.start(body.email, next_path=body.next)
        return ok({"redirectUrl": started.redirect_url, "flowKey": started.flow_key})

    @app.get("/v1/auth/oidc/callback", tags=["platform"], status_code=303, responses=ERRORS)
    async def oidc_callback(  # pyright: ignore[reportUnusedFunction]
        state: Annotated[str, Query(max_length=200)] = "",
        code: Annotated[str, Query(max_length=2000)] = "",
    ) -> RedirectResponse:
        """The provider sends the browser back here; it goes on to the console with a one-time code or an error."""
        return RedirectResponse(await sso.oidc_answer(state=state, code=code), status_code=303)

    @app.get(
        "/v1/auth/saml/metadata",
        tags=["platform"],
        response_class=Response,
        responses={
            200: {"content": {"application/samlmetadata+xml": {"schema": {"type": "string"}}}},
            **ERRORS,
        },
    )
    async def saml_metadata() -> Response:  # pyright: ignore[reportUnusedFunction]
        """The SAML service provider metadata a bank's identity provider imports: entity id, consumer URL and the
        certificate for signed requests and encrypted assertions (c-197). Public: it holds nothing secret."""
        return Response(sso.sp_metadata(), media_type="application/samlmetadata+xml")

    @app.post("/v1/auth/saml/acs", tags=["platform"], status_code=303, responses=ERRORS)
    async def saml_acs(request: Request) -> RedirectResponse:  # pyright: ignore[reportUnusedFunction]
        """The SAML POST binding: a form with SAMLResponse and RelayState, posted by the provider's page."""
        raw = await request.body()
        if len(raw) > 512 * 1024:
            raise ValidationFailed("The SAML response is too large.", code="saml_too_large")
        form = {k: v[0] for k, v in parse_qs(raw.decode(errors="replace")).items()}
        target = await sso.saml_answer(
            relay_state=form.get("RelayState", ""), saml_response=form.get("SAMLResponse", "")
        )
        return RedirectResponse(target, status_code=303)

    @app.post("/v1/auth/sso/complete", tags=["platform"], response_model=Envelope[SessionOut], responses=ERRORS)
    async def sso_complete(body: SsoCompleteIn) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The one-time code from the callback and the starting browser's flow key, for a session."""
        return ok(_issued(await sso.complete(code=body.code, flow_key=body.flow_key, request_id=new_id("req"))))

    @app.post("/v1/auth/step-up/sso/start", tags=["platform"], response_model=Envelope[SsoStarted], responses=ERRORS)
    async def step_up_sso_start(  # pyright: ignore[reportUnusedFunction]
        body: StepUpSsoStartIn, token: Annotated[str, Depends(_bearer)]
    ) -> Any:
        """An SSO session's step-up: back to its own provider, which must ask for credentials again."""
        started = await sso.step_up_start(token, next_path=body.next)
        return ok({"redirectUrl": started.redirect_url, "flowKey": started.flow_key})

    @app.post("/v1/auth/step-up/sso/complete", tags=["platform"], response_model=Envelope[StepUpOut], responses=ERRORS)
    async def step_up_sso_complete(  # pyright: ignore[reportUnusedFunction]
        body: SsoCompleteIn, token: Annotated[str, Depends(_bearer)]
    ) -> Any:
        issued = await sso.step_up_complete(token, code=body.code, flow_key=body.flow_key, request_id=new_id("req"))
        return ok({"token": issued.token, "expiresAt": issued.expires_at})

    @app.post("/v1/auth/password/forgot", tags=["platform"], status_code=204, responses=ERRORS)
    async def forgot_password(body: ForgotIn) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Mails a reset link when the email can sign in by password; the answer is the same either way."""
        await passwords.forgot(body.email, request_id=new_id("req"))
        return Response(status_code=204)

    @app.post("/v1/auth/password/reset", tags=["platform"], status_code=204, responses=ERRORS)
    async def reset_password(body: ResetIn) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Sets the new password from a reset link, once, and ends every session the person had."""
        await passwords.reset(body.token, body.password, request_id=new_id("req"))
        return Response(status_code=204)

    team_store = TeamStore(store.db, security_team=security_team)
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

    policy_store = PolicyStore(store.db)

    async def everywhere(tenant: str, user: str) -> bool:
        return await RoleStore(store.db).workspace_admin(tenant, user, now=now_iso())

    @app.get("/v1/me", tags=["platform"], response_model=Envelope[Me], responses=ERRORS)
    async def me(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        tenant, user = str(claims["tenant_id"]), str(claims["sub"])
        found = await store.user(tenant, user)
        if found is None:
            raise Unauthorized("Sign in again.")
        teams = await team_store.teams_of(tenant, user, everywhere=await everywhere(tenant, user))
        return ok(
            {
                "user": {"id": found.id, "email": found.email, "name": found.name},
                "tenantId": tenant,
                "tenantName": await store.tenant_name(tenant) or tenant,
                "teams": [{"id": t["id"], "name": t["name"], "role": t["role"]} for t in teams],
                "policies": await policy_store.values(tenant),
                "securityTeamId": await team_store.security_team_of(tenant),
            }
        )

    @app.get("/v1/teams", tags=["platform"], response_model=Envelope[list[TeamOut]], responses=ERRORS)
    async def list_teams(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The teams the caller may switch to: their own, and every active team for a workspace admin (c-208)."""
        tenant, user = str(claims["tenant_id"]), str(claims["sub"])
        return ok(await team_store.teams_of(tenant, user, everywhere=await everywhere(tenant, user)))

    @app.get(
        "/v1/settings/members", tags=["platform"], response_model=Envelope[ListResult[MemberOut]], responses=ERRORS
    )
    async def list_members(  # pyright: ignore[reportUnusedFunction]
        actor: Annotated[Actor, Depends(acting)],
        role: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
    ) -> Any:
        # Every built-in role but Chat user reads the team's people; a chat-only member does not (c-188).
        await people.require_admin(actor, "access", "view")
        everyone = await team_store.members(actor.tenant_id, actor.team_id, roles=[], statuses=[])
        rows = [m for m in everyone if (not role or m["role"] in role) and (not status or m["status"] in status)]
        joined = [str(m["userId"]) for m in rows if m.get("userId")]
        wide = await RoleStore(store.db).workspace_roles(actor.tenant_id, joined, now=now_iso())
        rows = [m | {"workspaceRoles": wide.get(str(m.get("userId")), [])} for m in rows]
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

    @app.get("/v1/settings/members/options", tags=["platform"], response_model=Envelope[OptionsPage], responses=ERRORS)
    async def member_options(  # pyright: ignore[reportUnusedFunction]
        actor: Annotated[Actor, Depends(acting)],
        search: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        ids: Annotated[list[str] | None, Query()] = None,
    ) -> Any:
        # A person deciding a task picks who it goes to; anyone who may decide reviews in the team may list its people.
        await people.require_admin(actor, "reviews", "decide")
        offset, window = options_window(cursor, limit)
        rows = await team_store.people_options(
            actor.tenant_id, actor.team_id, search=search, ids=ids or [], offset=offset, limit=window
        )
        return ok(options_page(rows, offset, limit))

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

    roles = Roles(RoleStore(store.db))

    @app.get("/v1/roles", tags=["platform"], response_model=Envelope[list[RoleOut]], responses=ERRORS)
    async def list_roles(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """Every role in the tenant, built-in first, with how many permissions it grants and how many hold it."""
        return ok(await roles.list(str(claims["tenant_id"])))

    @app.get("/v1/roles/{role_id}", tags=["platform"], response_model=Envelope[RoleDetail], responses=ERRORS)
    async def read_role(  # pyright: ignore[reportUnusedFunction]
        role_id: Annotated[str, Path(pattern=RECORD_ID)], claims: Annotated[dict[str, Any], Depends(claims_of)]
    ) -> Any:
        """One role and its grid: every area and action in the catalogue, with the scope it grants or null."""
        return ok(await roles.get(str(claims["tenant_id"]), role_id))

    holder_store = HolderStore(store.db)

    @app.get("/v1/access/holders", tags=["platform"], response_model=Envelope[HoldersOut], responses=ERRORS)
    async def access_holders(  # pyright: ignore[reportUnusedFunction]
        area: Annotated[str, Query(max_length=32)],
        action: Annotated[str, Query(max_length=16)],
        actor: Annotated[Actor, Depends(acting)],
        claims: Annotated[dict[str, Any], Depends(claims_of)],
        team: Annotated[str | None, Query(max_length=64)] = None,
    ) -> Any:
        """Which roles grant `area.action` in a team (the Security team for its actions), and who holds them there:
        what a "View only" notice names (c-186). The team is `team`, the record's, when the page shows another team's
        record, else the one the request acts in; a member of that team, or a workspace admin, may ask."""
        if area not in AREAS or action not in ACTIONS:
            raise ValidationFailed(f"{area}.{action} is not in the catalogue.", code="unknown_cell")
        named: list[Any] = claims.get("team_ids") or []
        outside = team is not None and team not in [str(t) for t in named]
        if outside and not await everywhere(actor.tenant_id, actor.user_id):
            raise Forbidden("You are not a member of that team.", code="team_forbidden")
        security = await team_store.security_team_of(actor.tenant_id)
        team = security if (area, action) in SECURITY_TEAM_ACTIONS else team or actor.team_id
        return ok({"teamId": team, **await holder_store.holders(actor.tenant_id, team, area, action)})

    @app.get("/v1/me/permissions", tags=["platform"], response_model=Envelope[PermissionsOut], responses=ERRORS)
    async def my_permissions(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """What the caller may do in each of their teams, and the roles that grant each action."""
        return ok(await roles.of_me(str(claims["tenant_id"]), str(claims["sub"])))

    checker = AccessCheck(RoleStore(store.db), team_store, store, policy_store, people, holder_store)

    @app.get("/v1/me/why", tags=["platform"], response_model=Envelope[WhyOut], responses=ERRORS)
    async def why_not(  # pyright: ignore[reportUnusedFunction]
        area: Annotated[str, Query(max_length=32)],
        action: Annotated[str, Query(max_length=16)],
        actor: Annotated[Actor, Depends(acting)],
    ) -> Any:
        """Whether the caller may take `area.action` in the team they act in, and if not why, which roles grant it
        and who in the team can give roles (c-150): the reason a locked button gives."""
        if area not in AREAS or action not in ACTIONS:
            raise ValidationFailed(f"{area}.{action} is not in the catalogue.", code="unknown_cell")
        return ok(await checker.why(actor, area, action))

    @app.post("/v1/access/check", tags=["platform"], response_model=Envelope[AccessCheckOut], responses=ERRORS)
    async def check_access(  # pyright: ignore[reportUnusedFunction]
        body: AccessCheckIn, actor: Annotated[Actor, Depends(acting)]
    ) -> Any:
        """Whether a person may take `area.action` in the team the request acts in (c-150), by the same `can()` the
        services run with the workspace's policies: allowed with the granting roles, or refused with the reason. The
        caller needs access.view there; each check is audited as access.check."""
        if body.area not in AREAS or body.action not in ACTIONS:
            raise ValidationFailed(f"{body.area}.{body.action} is not in the catalogue.", code="unknown_cell")
        return ok(
            await checker.check(
                actor, body.person_id, body.area, body.action, owner=body.owner, requested_by=body.requested_by
            )
        )

    @app.get(
        "/v1/people/{person_id}/permissions",
        tags=["platform"],
        response_model=Envelope[PermissionsOut],
        responses=ERRORS,
    )
    async def person_permissions(  # pyright: ignore[reportUnusedFunction]
        person_id: Annotated[str, Path(pattern=RECORD_ID)], claims: Annotated[dict[str, Any], Depends(claims_of)]
    ) -> Any:
        """What a person may do in the teams they share with the caller, with their name and address; 404 when they
        share none."""
        tenant = str(claims["tenant_id"])
        view = await roles.of_person(tenant, str(claims["sub"]), person_id)
        who = await store.user(tenant, person_id)
        return ok(view | ({"name": who.name, "email": who.email} if who else {}))

    signin_settings = SignInSettings(
        signin_store, people, sign.secrets, sign.dns, sp_key_set=sign.saml_sp_key is not None
    )

    @app.get(
        "/v1/settings/sign-in/providers",
        tags=["platform"],
        response_model=Envelope[list[ProviderOut]],
        responses=ERRORS,
    )
    async def list_signin_providers(actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The workspace's sign-in providers; Security team admins only."""
        return ok(await signin_settings.list(actor))

    @app.put(
        "/v1/settings/sign-in/providers/{provider_id}",
        tags=["platform"],
        response_model=Envelope[ProviderOut],
        responses=ERRORS,
    )
    async def save_signin_provider(  # pyright: ignore[reportUnusedFunction]
        provider_id: Annotated[str, Path(pattern=RECORD_ID)],
        body: ProviderIn,
        actor: Annotated[Actor, Depends(acting)],
    ) -> Any:
        """Creates or replaces a provider by id, with its domains and first sign-in team; Security team admins only."""
        return ok(await signin_settings.save(actor, provider_id, body.model_dump(by_alias=True)))

    @app.get(
        "/v1/settings/sign-in/secret-names", tags=["platform"], response_model=Envelope[list[str]], responses=ERRORS
    )
    async def list_signin_secret_names(actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The names an OIDC provider may give as `clientSecretRef` (`OPS_SIGNIN_SECRETS`), never the values."""
        return ok(await signin_settings.secret_names(actor))

    @app.post(
        "/v1/settings/sign-in/domains/{domain}/verify",
        tags=["platform"],
        response_model=Envelope[ProviderOut],
        responses=ERRORS,
    )
    async def verify_signin_domain(  # pyright: ignore[reportUnusedFunction]
        domain: Annotated[str, Path(max_length=253, pattern=DOMAIN)], actor: Annotated[Actor, Depends(acting)]
    ) -> Any:
        """Checks the domain's TXT record and, when it holds the claim's value, lets the domain route sign-in; returns
        its provider. 422 `domain_unverified` with what DNS held, 409 `domain_taken` when another workspace has it."""
        return ok(await signin_settings.verify_domain(actor, domain.lower()))

    policies = Policies(policy_store, people)

    @app.get("/v1/policies", tags=["platform"], response_model=Envelope[list[PolicyOut]], responses=ERRORS)
    async def list_policies(actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """Every policy with its value and open default; any member of the workspace reads them."""
        return ok(await policies.list(actor))

    settings = Settings()
    readers = services or ServiceAuth(
        audience="platform", verifiers=service_verifiers(settings, "platform"), scopes=settings.service_scopes
    )

    @app.get("/v1/policies/{key}", tags=["platform"], response_model=Envelope[PolicyOut], responses=ERRORS)
    async def get_policy(  # pyright: ignore[reportUnusedFunction]
        key: Annotated[str, Path(max_length=64)],
        token: Annotated[str, Depends(_bearer)],
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Any:
        """One policy of the workspace. Any member reads it; a service token needs the
        `settings:view` scope and reads its own tenant's value, as a background job with no person does (c-206's
        memory sweep). 400 `policy_value` for a key the catalogue does not hold."""
        if readers.signs(token):
            svc = readers.resolve(token)
            if "settings:view" not in svc.scopes:
                raise Forbidden("This service token does not hold the settings:view scope.", code="scope_required")
            rows = await policies.for_tenant(svc.tenant_id)
        else:
            rows = await policies.list(await acting(await claims_of(token), x_team_id))
        row = next((r for r in rows if r["key"] == key), None)
        if row is None:
            raise ValidationFailed(f"{key} is not a policy", code="policy_value")
        return ok(row)

    @app.get("/v1/team-names", tags=["platform"], response_model=Envelope[list[TeamName]], responses=ERRORS)
    async def team_names(  # pyright: ignore[reportUnusedFunction]
        token: Annotated[str, Depends(_bearer)],
    ) -> Any:
        """Every team's display name in the workspace (c-224), so a page showing another team's record names its team.
        Any member reads them; a service token needs the `settings:view` scope and reads its own tenant's."""
        if readers.signs(token):
            svc = readers.resolve(token)
            if "settings:view" not in svc.scopes:
                raise Forbidden("This service token does not hold the settings:view scope.", code="scope_required")
            tenant = svc.tenant_id
        else:
            tenant = str((await claims_of(token))["tenant_id"])
        return ok(await team_store.names(tenant))

    @app.get("/v1/people-names", tags=["platform"], response_model=Envelope[list[PersonName]], responses=ERRORS)
    async def people_names(  # pyright: ignore[reportUnusedFunction]
        token: Annotated[str, Depends(_bearer)],
    ) -> Any:
        """Every person's display name in the workspace by email (c-201), so a list naming who did something shows a
        name rather than an address. Any member reads them; a service token needs the `settings:view` scope."""
        if readers.signs(token):
            svc = readers.resolve(token)
            if "settings:view" not in svc.scopes:
                raise Forbidden("This service token does not hold the settings:view scope.", code="scope_required")
            tenant = svc.tenant_id
        else:
            tenant = str((await claims_of(token))["tenant_id"])
        return ok(await team_store.people_names(tenant))

    @app.put("/v1/policies/{key}", tags=["platform"], response_model=Envelope[PolicyOut], responses=ERRORS)
    async def set_policy(  # pyright: ignore[reportUnusedFunction]
        key: Annotated[str, Path(max_length=64)], body: PolicyIn, actor: Annotated[Actor, Depends(acting)]
    ) -> Any:
        """Sets one policy for the workspace, audited, and moves the permission version so tokens refresh; who holds
        settings.manage in the acting team. 400 `policy_value` for a key or value the catalogue does not take."""
        return ok(await policies.set(actor, key, body.value))

    @app.delete("/v1/settings/sign-in/providers/{provider_id}", tags=["platform"], status_code=204, responses=ERRORS)
    async def delete_signin_provider(  # pyright: ignore[reportUnusedFunction]
        provider_id: Annotated[str, Path(pattern=RECORD_ID)], actor: Annotated[Actor, Depends(acting)]
    ) -> Response:
        await signin_settings.delete(actor, provider_id)
        return Response(status_code=204)

    team_admin = TeamAdmin(
        TeamAdminStore(store.db, security_team=security_team),
        people,
        WorkspaceStore(store.db, fallback_security_team=security_team),
    )

    async def on_workspace(claims: Annotated[dict[str, Any], Depends(claims_of)]) -> Actor:
        """A workspace route acts on the workspace, not one team: no X-Team-Id, rights read in every team (`*`)."""
        return Actor(str(claims["tenant_id"]), "*", str(claims["sub"]), new_id("req"))

    @app.get(
        "/v1/settings/teams",
        tags=["platform"],
        response_model=Envelope[ListResult[WorkspaceTeamOut]],
        responses=ERRORS,
    )
    async def list_workspace_teams(  # pyright: ignore[reportUnusedFunction]
        actor: Annotated[Actor, Depends(on_workspace)],
        status: Annotated[list[Literal["active", "archived"]] | None, Query()] = None,
        search: Annotated[str, Query(max_length=80)] = "",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 50,
    ) -> Any:
        """Every team of the workspace with its member and admin counts; workspace admins (`access.view` in every
        team) only."""
        return ok(
            await team_admin.every(actor, statuses=list(status or []), search=search, page=page, page_size=page_size)
        )

    @app.post(
        "/v1/settings/teams",
        tags=["platform"],
        status_code=201,
        response_model=Envelope[WorkspaceTeamOut],
        responses=ERRORS,
    )
    async def create_team(body: TeamIn, actor: Annotated[Actor, Depends(on_workspace)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """A new team with its first admin; workspace admins (`access.manage` in every team) only. A name the
        workspace already uses, in any case, is 409, so a retried create never makes a second team."""
        return ok(await team_admin.create(actor, body.name, body.admin), status=201)

    @app.get(
        "/v1/settings/workspace-teams",
        tags=["platform"],
        response_model=Envelope[WorkspaceTeamsOut],
        responses=ERRORS,
    )
    async def read_workspace_teams(token: Annotated[str, Depends(_bearer)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        """The workspace's security team and the team new people join when nothing else names one (c-202). A workspace
        admin reads them; a service token needs the `settings:view` scope and reads its own tenant's (c-230)."""
        if readers.signs(token):
            svc = readers.resolve(token)
            if "settings:view" not in svc.scopes:
                raise Forbidden("This service token does not hold the settings:view scope.", code="scope_required")
            return ok(await team_admin.workspace_teams_of(svc.tenant_id))
        return ok(await team_admin.workspace_teams(await on_workspace(await claims_of(token))))

    @app.put(
        "/v1/settings/workspace-teams",
        tags=["platform"],
        response_model=Envelope[WorkspaceTeamsOut],
        responses=ERRORS,
    )
    async def set_workspace_teams(  # pyright: ignore[reportUnusedFunction]
        body: WorkspaceTeamsIn, actor: Annotated[Actor, Depends(on_workspace)]
    ) -> Any:
        """Workspace admins only. Moving the security team moves Security admin with it, at once."""
        return ok(await team_admin.set_workspace_teams(actor, body.security_team, body.default_team))

    @app.patch(
        "/v1/settings/workspace",
        tags=["platform"],
        response_model=Envelope[WorkspaceNameOut],
        responses=ERRORS,
    )
    async def rename_workspace(  # pyright: ignore[reportUnusedFunction]
        body: WorkspaceRenameIn, actor: Annotated[Actor, Depends(on_workspace)]
    ) -> Any:
        """Names the workspace (the console's header and switcher read it from `/v1/me`); workspace admins only."""
        return ok(await team_admin.rename_workspace(actor, body.name))

    @app.patch(
        "/v1/settings/teams/{team_id}",
        tags=["platform"],
        response_model=Envelope[WorkspaceTeamOut],
        responses=ERRORS,
    )
    async def rename_team(  # pyright: ignore[reportUnusedFunction]
        team_id: Annotated[str, Path(pattern=RECORD_ID)],
        body: TeamRenameIn,
        actor: Annotated[Actor, Depends(on_workspace)],
    ) -> Any:
        return ok(await team_admin.rename(actor, team_id, body.name))

    @app.post(
        "/v1/settings/teams/{team_id}/archive",
        tags=["platform"],
        response_model=Envelope[WorkspaceTeamOut],
        responses=ERRORS,
    )
    async def archive_team(  # pyright: ignore[reportUnusedFunction]
        team_id: Annotated[str, Path(pattern=RECORD_ID)], actor: Annotated[Actor, Depends(on_workspace)]
    ) -> Any:
        """The team leaves its members' next tokens and takes no new members; what it owns stays its own."""
        return ok(await team_admin.set_status(actor, team_id, archived=True))

    @app.post(
        "/v1/settings/teams/{team_id}/restore",
        tags=["platform"],
        response_model=Envelope[WorkspaceTeamOut],
        responses=ERRORS,
    )
    async def restore_team(  # pyright: ignore[reportUnusedFunction]
        team_id: Annotated[str, Path(pattern=RECORD_ID)], actor: Annotated[Actor, Depends(on_workspace)]
    ) -> Any:
        return ok(await team_admin.set_status(actor, team_id, archived=False))

    keys = ApiKeys(KeyStore(store.db), people)

    @app.get("/v1/api-keys", tags=["platform"], response_model=Envelope[list[ApiKeyOut]], responses=ERRORS)
    async def list_api_keys(actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await keys.list(actor))

    @app.post(
        "/v1/api-keys", tags=["platform"], status_code=201, response_model=Envelope[ApiKeyCreated], responses=ERRORS
    )
    async def create_api_key(body: ApiKeyIn, actor: Annotated[Actor, Depends(acting)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        target = body.target.model_dump() if body.target else None
        return ok(await keys.create(actor, body.name, list(body.scopes), body.expires_in_days, target), status=201)

    @app.get("/v1/api-key-summaries", tags=["platform"], response_model=Envelope[list[ApiKeySummary]], responses=ERRORS)
    async def api_key_summaries(  # pyright: ignore[reportUnusedFunction]
        token: Annotated[str, Depends(_bearer)],
    ) -> Any:
        """Every team's keys in the workspace with what each serves (c-246): for agents-service's list of API channels
        (a service token with the `settings:view` scope), or for a person who manages access across the workspace
        (`can('access', 'manage')` in every team), as an admin may do everything."""
        if not readers.signs(token):
            claims = (await auth.session_of(token))[1]
            actor = Actor(str(claims["tenant_id"]), ANY_TEAM, str(claims["sub"]), new_id("req"))
            await people.require_admin(actor, "access", "manage")
            return ok(await keys.summaries(actor.tenant_id))
        svc = readers.resolve(token)
        if "settings:view" not in svc.scopes:
            raise Forbidden("This service token does not hold the settings:view scope.", code="scope_required")
        return ok(await keys.summaries(svc.tenant_id))

    @app.post("/v1/api-keys/{key_id}/revoke", tags=["platform"], response_model=Envelope[ApiKeyOut], responses=ERRORS)
    async def revoke_api_key(  # pyright: ignore[reportUnusedFunction]
        key_id: Annotated[str, Path(pattern=KEY_ID)], actor: Annotated[Actor, Depends(acting)]
    ) -> Any:
        return ok(await keys.revoke(actor, key_id))

    reader = AuditReader(AuditLog(store.db), team_store, people)

    @app.get("/v1/audit", tags=["platform"], response_model=Envelope[AuditPage], responses=ERRORS)
    async def read_audit(  # pyright: ignore[reportUnusedFunction]
        *,
        actor: Annotated[Actor, Depends(acting)],
        action: Annotated[str | None, Query(max_length=80)] = None,
        kind: Annotated[AuditKind | None, Query()] = None,
        view: Annotated[Literal["all", "publishes", "access", "deletions"], Query()] = "all",
        actor_id: Annotated[str | None, Query(alias="actor", max_length=320)] = None,
        target_kind: Annotated[str | None, Query(alias="targetKind", max_length=40)] = None,
        since: Annotated[str | None, Query(alias="from", pattern=ISO_TIME)] = None,
        until: Annotated[str | None, Query(alias="to", pattern=ISO_TIME)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 50,
    ) -> Any:
        filters = {"action": action, "kind": kind, "view": view, "actor": actor_id, "target_kind": target_kind}
        filters |= {"from": since, "to": until}
        return ok(await reader.page(actor, filters, page, page_size))

    @app.get("/v1/invites/{token}", tags=["platform"], response_model=Envelope[InvitePreview], responses=ERRORS)
    async def read_invite(token: Annotated[str, Path(pattern=INVITE_TOKEN)]) -> Any:  # pyright: ignore[reportUnusedFunction]
        return ok(await people.preview(token))

    @app.post("/v1/invites/{token}/accept", tags=["platform"], response_model=Envelope[SessionOut], responses=ERRORS)
    async def accept_invite(  # pyright: ignore[reportUnusedFunction]
        token: Annotated[str, Path(pattern=INVITE_TOKEN)],
        body: AcceptIn,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Any:
        """A new person accepts with the link alone; a person who already has an account sends their own session."""
        request_id = new_id("req")
        caller = str((await auth.session_of(_bearer(authorization)))[1]["sub"]) if authorization else None
        encoded = await passwords.hash(body.password) if body.password is not None and caller is None else None
        invite, user_id = await people.accept(token, body.name, caller=caller, request_id=request_id)
        user = await store.user(invite.tenant_id, user_id)
        if user is None:
            raise Unauthorized("Sign in again.")
        # The link alone proves the invite was received; a password set with it is how the person signs in after.
        method = "invite"
        if encoded is not None and await signin_store.password_allowed(user.tenant_id):
            await signin_store.set_password(user.tenant_id, user.id, encoded, at=now_iso())
            method = "password"
        return ok(_issued(await auth.start_session(user, request_id=request_id, method=method)))

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
