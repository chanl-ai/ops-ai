"""Single sign-on through a workspace's OIDC or SAML provider: discovery by email domain, the round trip, the people it
signs in, and step-up at the same provider.

The email's domain picks the workspace and its provider; nothing else in the request names either. `start` keeps the
round trip's secrets in a flow row and gives the browser a flow key. The provider sends the person back to
platform-service (the OIDC callback or the SAML consumer URL), which checks the answer through `ops_signin`, finds or
makes the person, and sends the browser to the console's `/sso/callback` with a one-time handoff code. `complete`
turns that code into a session only alongside the flow key of the browser that started, so a code that leaks into a
log or another browser opens nothing. A step-up runs the same round trip with the provider told to ask for credentials
again, for the session's own provider, and must come back as the session's own person.

Every failure in the round trip lands on the console with `error=sign_in_refused`; what failed goes to the log only.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr

from ops_service_kit.errors import NotFound, ServiceUnavailable, Unauthorized, ValidationFailed
from ops_service_kit.logging import get_logger
from ops_signin import (
    OidcClient,
    OidcConfig,
    SamlConfig,
    SamlServiceProvider,
    SignInRefused,
    VerifiedIdentity,
)
from ops_signin.saml import sp_metadata

from .auth import SSO_METHODS, Auth, Issued, StepUpIssued
from .store.identity import IdentityStore
from .store.signin import Flow, Provider, SignInStore

log = get_logger(__name__)

SIGN_IN = "sign_in"
STEP_UP = "step_up"
OIDC_CALLBACK = "/v1/auth/oidc/callback"
SAML_ACS = "/v1/auth/saml/acs"
SAML_SP = "/v1/auth/saml"


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _unix(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _groups_source(config: dict[str, Any]) -> str | None:
    """The claim or attribute a provider's group mapping reads; None when it maps no groups."""
    groups: dict[str, Any] = config.get("groups") or {}
    return str(groups.get("source") or "groups") if groups.get("map") else None


def _refused() -> Unauthorized:
    return Unauthorized("Sign in again.")


@dataclass(frozen=True)
class Started:
    redirect_url: str
    flow_key: str


@dataclass
class Sso:
    auth: Auth
    identity: IdentityStore
    store: SignInStore
    http: httpx.AsyncClient
    public_url: str | None
    console_url: str | None
    secrets: dict[str, SecretStr]
    flow_ttl_s: int
    # The SAML service provider's key and certificate (c-197); None when the installation has none.
    sp_key: SecretStr | None = None
    sp_certificate: str | None = None
    _metadata: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])

    # ── Discovery ──

    async def options(self, email: str) -> dict[str, Any]:
        """What the email's domain signs in with. It reads the domain only, never whether an account exists, so the
        answer is the same for every address on a domain."""
        hit = await self.store.domain(email.rpartition("@")[2])
        if hit is None:
            return {"password": True, "sso": None}
        sso = {"kind": hit.kind, "label": hit.label} if hit.enabled and hit.kind in SSO_METHODS else None
        return {"password": await self.store.password_allowed(hit.tenant_id), "sso": sso}

    # ── The round trip ──

    def _urls(self) -> tuple[str, str]:
        if not self.public_url or not self.console_url:
            raise ServiceUnavailable("Single sign-on is not set up on this installation.", code="sso_not_configured")
        return self.public_url.rstrip("/"), self.console_url.rstrip("/")

    def _oidc(self, p: Provider) -> OidcClient:
        c = p.config
        ref = c.get("clientSecretRef")
        secret = self.secrets.get(str(ref)) if ref else None
        if ref and secret is None:
            raise ServiceUnavailable("The sign-in provider's secret is not set.", code="sso_not_configured")
        config = OidcConfig(
            issuer=str(c["issuer"]),
            client_id=str(c["clientId"]),
            client_secret=secret.get_secret_value() if secret else None,
            scopes=tuple(c.get("scopes") or ("openid", "email", "profile")),
            groups_claim=_groups_source(c),
        )
        return OidcClient(config, self.http, self._metadata)

    def sp_metadata(self) -> bytes:
        """The service provider's SAML metadata for a bank's identity provider."""
        public, _ = self._urls()
        return sp_metadata(
            entity_id=f"{public}{SAML_SP}",
            acs_url=f"{public}{SAML_ACS}",
            certificate=self.sp_certificate,
            sign_requests=self.sp_key is not None,
        )

    def _saml(self, p: Provider) -> SamlServiceProvider:
        public, _ = self._urls()
        c = p.config
        needs_key = bool(c.get("signRequests") or c.get("requireEncryption"))
        if needs_key and self.sp_key is None:
            raise ServiceUnavailable("The service provider key is not set.", code="sso_not_configured")
        return SamlServiceProvider(
            SamlConfig(
                idp_entity_id=str(c["idpEntityId"]),
                idp_sso_url=str(c["ssoUrl"]),
                idp_certificate=str(c["certificate"]),
                sp_entity_id=f"{public}{SAML_SP}",
                acs_url=f"{public}{SAML_ACS}",
                email_attribute=c.get("emailAttribute"),
                name_attribute=c.get("nameAttribute"),
                groups_attribute=_groups_source(c),
                sp_key=self.sp_key.get_secret_value() if self.sp_key else None,
                sign_requests=bool(c.get("signRequests")),
                require_encryption=bool(c.get("requireEncryption")),
            )
        )

    async def _begin(
        self,
        p: Provider,
        *,
        purpose: str,
        login_hint: str | None,
        next_path: str | None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> Started:
        public, _ = self._urls()
        now = datetime.now(UTC)
        flow_key = secrets.token_urlsafe(32)
        force = purpose == STEP_UP

        async def keep(
            state: str, *, verifier: str | None = None, nonce: str | None = None, request: str | None = None
        ) -> None:
            await self.store.open_flow(
                tenant_id=p.tenant_id,
                provider_id=p.id,
                purpose=purpose,
                state_hash=_hash(state),
                browser_hash=_hash(flow_key),
                at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.flow_ttl_s)),
                verifier=verifier,
                nonce=nonce,
                request_id=request,
                next_path=next_path,
                session_id=session_id,
                user_id=user_id,
            )

        try:
            if p.kind == "oidc":
                start = await self._oidc(p).begin(
                    redirect_uri=f"{public}{OIDC_CALLBACK}", login_hint=login_hint, force=force
                )
                await keep(start.state, verifier=start.verifier, nonce=start.nonce)
                return Started(start.url, flow_key)
            if p.kind == "saml":
                state = secrets.token_urlsafe(32)
                saml = self._saml(p).begin(relay_state=state, force=force, now=now)
                await keep(state, request=saml.request_id)
                return Started(saml.url, flow_key)
        except SignInRefused as e:
            log.warning("signin_provider_unavailable", provider=p.id, reason=e.reason)
            raise ServiceUnavailable("Your company's sign-in did not answer. Try again.", code="sso_unavailable") from e
        raise ValidationFailed("This workspace does not sign in through a company provider.", code="sso_not_enabled")

    async def start(self, email: str, *, next_path: str | None) -> Started:
        hit = await self.store.domain(email.rpartition("@")[2])
        p = await self.store.provider(hit.tenant_id, hit.provider_id) if hit else None
        if p is None or not p.enabled or p.kind not in SSO_METHODS:
            raise ValidationFailed("This email does not sign in through a company provider.", code="sso_not_enabled")
        return await self._begin(p, purpose=SIGN_IN, login_hint=email, next_path=next_path)

    async def oidc_answer(self, *, state: str, code: str) -> str:
        """The console URL the browser goes to after the provider's OIDC answer."""
        flow = await self.store.flow_by_state(_hash(state)) if state else None
        try:
            p = await self._live(flow, "oidc")
            if flow is None or not flow.verifier or not flow.nonce:
                raise SignInRefused("flow has no PKCE verifier or nonce")
            public, _ = self._urls()
            who = await self._oidc(p).complete(
                code=code,
                verifier=flow.verifier,
                nonce=flow.nonce,
                redirect_uri=f"{public}{OIDC_CALLBACK}",
                fresh_since=_unix(flow.created_at) if flow.purpose == STEP_UP else None,
            )
            return await self._answer(flow, p, who)
        except SignInRefused as e:
            log.info("signin_refused", kind="oidc", flow=flow.id if flow else None, reason=e.reason)
            return self._failed(flow)

    async def saml_answer(self, *, relay_state: str, saml_response: str) -> str:
        """The console URL the browser goes to after the provider's SAML answer."""
        flow = await self.store.flow_by_state(_hash(relay_state)) if relay_state else None
        try:
            p = await self._live(flow, "saml")
            if flow is None or not flow.request_id:
                raise SignInRefused("flow has no SAML request id")
            who = self._saml(p).complete(
                saml_response=saml_response,
                request_id=flow.request_id,
                fresh_since=_unix(flow.created_at) if flow.purpose == STEP_UP else None,
            )
            return await self._answer(flow, p, who)
        except SignInRefused as e:
            log.info("signin_refused", kind="saml", flow=flow.id if flow else None, reason=e.reason)
            return self._failed(flow)

    async def _live(self, flow: Flow | None, kind: str) -> Provider:
        """The flow's provider, when the flow exists, has not expired and was started for a provider of this kind."""
        if flow is None or flow.expires_at <= _iso(datetime.now(UTC)):
            raise SignInRefused("unknown or expired flow")
        p = await self.store.provider(flow.tenant_id, flow.provider_id)
        if p is None or not p.enabled or p.kind != kind:
            raise SignInRefused(f"flow is not for a live {kind} provider")
        return p

    async def _answer(self, flow: Flow, p: Provider, who: VerifiedIdentity) -> str:
        now = _iso(datetime.now(UTC))
        if flow.purpose == STEP_UP:
            user_id = await self.store.linked(p.tenant_id, p.id, who.subject)
            if user_id is None or user_id != flow.user_id:
                raise SignInRefused("step-up answered by another person")
        else:
            person = await self.store.resolve(
                p, subject=who.subject, email=who.email, name=who.name, at=now, request_id=flow.id, groups=who.groups
            )
            if person is None:
                raise SignInRefused("no person may sign in as this answer")
            user_id = person.user_id
        handoff = secrets.token_urlsafe(32)
        if not await self.store.answer(flow, user_id=user_id, handoff_hash=_hash(handoff), at=now):
            raise SignInRefused("flow already answered")
        return self._console(flow, {"code": handoff})

    def _console(self, flow: Flow | None, params: dict[str, str]) -> str:
        _, console = self._urls()
        if flow is not None and flow.purpose == STEP_UP:
            params = {**params, "stepUp": "1"}
        if flow is not None and flow.next_path:
            params = {**params, "next": flow.next_path}
        return f"{console}/sso/callback?{urlencode(params)}"

    def _failed(self, flow: Flow | None) -> str:
        return self._console(flow, {"error": "sign_in_refused"})

    async def _taken(self, code: str, flow_key: str, purpose: str) -> Flow:
        flow = await self.store.flow_by_handoff(_hash(code))
        if flow is None or flow.purpose != purpose or flow.user_id is None:
            raise _refused()
        if not await self.store.take(flow, browser_hash=_hash(flow_key), at=_iso(datetime.now(UTC))):
            raise _refused()
        return flow

    async def complete(self, *, code: str, flow_key: str, request_id: str) -> Issued:
        flow = await self._taken(code, flow_key, SIGN_IN)
        user = await self.identity.user(flow.tenant_id, flow.user_id or "")
        p = await self.store.provider(flow.tenant_id, flow.provider_id)
        if user is None or p is None:
            raise _refused()
        return await self.auth.start_session(user, request_id=request_id, method=p.kind, provider_id=p.id)

    # ── Step-up at the session's provider ──

    async def step_up_start(self, token: str, *, next_path: str | None) -> Started:
        ref, _ = await self.auth.session_of(token)
        method = await self.identity.method(ref)
        if method is None or method.auth_method not in SSO_METHODS or method.provider_id is None:
            raise Unauthorized("Confirm it is you with your password.", code="wrong_method")
        p = await self.store.provider(ref.tenant_id, method.provider_id)
        user = await self.identity.user(ref.tenant_id, ref.user_id)
        if p is None or not p.enabled or user is None:
            raise NotFound("sign-in provider")
        return await self._begin(
            p, purpose=STEP_UP, login_hint=user.email, next_path=next_path, session_id=ref.id, user_id=user.id
        )

    async def step_up_complete(self, token: str, *, code: str, flow_key: str, request_id: str) -> StepUpIssued:
        ref, _ = await self.auth.session_of(token)
        flow = await self._taken(code, flow_key, STEP_UP)
        if flow.session_id != ref.id or flow.user_id != ref.user_id:
            raise _refused()
        user = await self.identity.user(ref.tenant_id, ref.user_id)
        p = await self.store.provider(ref.tenant_id, flow.provider_id)
        if user is None or p is None:
            raise _refused()
        return await self.auth.mint_step_up(ref, user, method=p.kind, request_id=request_id)
