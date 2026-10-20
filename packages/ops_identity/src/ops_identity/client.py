"""The one way a service calls another service's API (c-189). Every caller builds a `ServiceClient` for its callee and
asks it for `get`, `post`, `delete` or `pages`; no service writes its own token minting, envelope reading or retry.

  kb = ServiceClient.for_settings(settings, http, service="agents", audience="kb", scopes=["knowledge:view"],
                                  tenant=current_tenant, team=current_team)
  refs = await kb.get("/v1/knowledge-bases/refs")

Each call mints a short service token naming the tenant (and team) the caller acts for, so a token never outlives
the request it was made for. An answer is the `{success, data, error}` envelope: `data` is returned, and an error
comes back as `ServiceCallError` carrying the callee's status and `error.code`, so the caller can pass a 404 or a
409 on to the person unchanged. A read that fails in transport (a refused or reset connection, a timeout) is tried
once more; a write never is, because the callee may have acted before the connection broke.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from ops_policy import Ed25519Signer
from ops_service_kit.errors import ApiError, ServiceUnavailable
from ops_service_kit.settings import Settings

from .resolve import mint_service_token
from .service_keys import service_signer


class ServiceCallError(ApiError):
    """The callee answered with an error: its status and code, kept so the caller can pass them on."""

    def __init__(
        self, status: int, message: str, *, code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code=code, details=details)
        self.status = status


class ServiceUnreachable(ServiceUnavailable):
    """The callee did not answer: refused, reset or timed out."""


def _none() -> str | None:
    return None


@dataclass
class ServiceClient:
    http: httpx.AsyncClient
    signer: Ed25519Signer
    # Who calls (the token's `sub`, service:<name>) and whom (its `aud`).
    service: str
    audience: str
    # The `area:action` scopes the token claims on the callee's routes; the callee caps them (Settings.service_scopes).
    scopes: list[str] = field(default_factory=list[str])
    # The tenant and team the caller acts for, read when each token is minted (a request's or run's).
    tenant: Callable[[], str | None] = _none
    team: Callable[[], str | None] = _none
    timeout: float = 10.0

    @classmethod
    def for_settings(
        cls,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        service: str,
        audience: str,
        scopes: list[str] | None = None,
        tenant: Callable[[], str | None] = _none,
        team: Callable[[], str | None] = _none,
        timeout: float = 10.0,
    ) -> ServiceClient:
        return cls(http, service_signer(settings), service, audience, list(scopes or []), tenant, team, timeout)

    def headers(
        self, *, team: str | None = None, tenant: str | None = None, token_header: str = "Authorization"
    ) -> dict[str, str]:
        """The service token header for one call; `team` and `tenant` override the caller's current ones, for a caller
        that names them per call rather than in context. `token_header` carries it beside a person's own credentials
        when the call passes those through (a review opened for a person, vouched for by this service)."""
        token = mint_service_token(
            self.signer,
            service=self.service,
            audience=self.audience,
            tenant_id=tenant if tenant is not None else self.tenant(),
            scopes=self.scopes or None,
            team_id=team if team is not None else self.team(),
        )
        return {token_header: f"Bearer {token}"}

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        team: str | None = None,
        tenant: str | None = None,
        token_header: str = "Authorization",
        timeout: float | None = None,
    ) -> Any:
        """The callee's `data`, or ServiceCallError / ServiceUnreachable."""
        tries = 2 if method.upper() == "GET" else 1
        for attempt in range(tries):
            try:
                r = await self.http.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers={**self.headers(team=team, tenant=tenant, token_header=token_header), **(headers or {})},
                    timeout=timeout or self.timeout,
                )
            except httpx.TransportError as e:
                if attempt + 1 < tries:
                    continue
                raise ServiceUnreachable(f"{self.audience} did not answer: {type(e).__name__}") from e
            return _data(self.audience, r)
        raise AssertionError("unreachable")  # pragma: no cover

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        return await self.request("POST", path, json=json, **kw)

    async def delete(self, path: str, **kw: Any) -> Any:
        return await self.request("DELETE", path, **kw)

    async def pages(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        cursor_field: str = "cursor",
        next_field: str = "nextLink",
        items_field: str = "items",
        **kw: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Each page of a cursor list, the first without a cursor, then each `next_field` until a page has none."""
        cursor: str | None = None
        while True:
            payload = {**(body or {}), **({cursor_field: cursor} if cursor else {})}
            page = cast(dict[str, Any], await self.request(method, path, json=payload, **kw))
            yield page
            following = page.get(next_field)
            if not following or not page.get(items_field, True):
                return
            cursor = str(following)


def _data(audience: str, r: httpx.Response) -> Any:
    try:
        body: Any = r.json() if r.content else None
    except ValueError:
        # A success whose body is not JSON (a proxy's page) is not an empty answer: a caller reading "no value" as
        # its default would act on a page it never got.
        if r.is_success:
            raise ServiceCallError(
                r.status_code, f"{audience} answered {r.status_code} with a body that is not JSON", code="bad_response"
            ) from None
        body = None
    envelope: dict[str, Any] = cast(dict[str, Any], body) if isinstance(body, dict) else {}
    if r.is_success:
        return envelope.get("data", body)
    error: dict[str, Any] = cast(dict[str, Any], envelope.get("error") or {})
    raise ServiceCallError(
        r.status_code,
        # An error that is not the envelope (a proxy's page) keeps the start of its body, so the reason survives.
        str(error.get("message") or f"{audience} answered {r.status_code}: {r.text[:200]}".rstrip(": ")),
        code=str(error["code"]) if error.get("code") else None,
        details=cast(dict[str, Any], error.get("details")) if isinstance(error.get("details"), dict) else None,
    )
