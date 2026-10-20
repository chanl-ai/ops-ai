"""Opens a tool module's review as an ordinary publish request in agents-service's Reviews (c-163).

One call carries two proofs: the person's own credentials, passed through, name who asked and the team they act in,
and this service's token in `X-Service-Authorization` vouches for the version and its changes. agents-service decides
who reviews it and, once decided, tells tools-service through `POST /v1/tool-modules/{id}/review-decisions`."""

from __future__ import annotations

from typing import Any, Protocol

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ApiError, ServiceUnavailable

from .policy import FORWARDED
from .review_diff import review_diff


class ReviewOpener(Protocol):
    async def open(
        self,
        credentials: dict[str, str],
        *,
        tenant_id: str,
        team_id: str,
        module: dict[str, Any],
        version: str,
        changes: list[dict[str, Any]],
        note: str,
        security: bool = True,
    ) -> str: ...


class Reviews:
    def __init__(self, agents: ServiceClient) -> None:
        """`agents` calls agents-service as this service; its token rides in `X-Service-Authorization` beside the
        person's own credentials."""
        self.agents = agents

    async def open(
        self,
        credentials: dict[str, str],
        *,
        tenant_id: str,
        team_id: str,
        module: dict[str, Any],
        version: str,
        changes: list[dict[str, Any]],
        note: str,
        security: bool = True,
    ) -> str:
        """The new request's id. `security` sends it to the Security team; otherwise the module's team decides it.
        Raises when agents-service refuses or cannot be reached: no version waits for a review that was never
        opened."""
        headers = {k: v for k, v in credentials.items() if k in FORWARDED} | {"X-Team-Id": team_id}
        body = {
            "kind": "tool_module",
            "subjectId": module["id"],
            "moduleName": module["display_name"],
            "moduleVersion": version,
            "changes": changes,
            # What the version adds, removes and changes since the published one, fixed at the moment it is asked for.
            "diff": review_diff(module),
            "security": security,
            "note": note,
        }
        try:
            data = await self.agents.post(
                "/v1/publish-requests",
                body,
                headers=headers,
                tenant=tenant_id,
                token_header="X-Service-Authorization",
            )
        except ServiceUnreachable as e:
            raise ServiceUnavailable(
                "Reviews could not be reached, so the review was not opened; try again shortly.",
                code="reviews_unavailable",
            ) from e
        except ServiceCallError as e:
            refused = ApiError(str(e) or "Reviews refused the review.", code=e.code or "reviews_refused")
            refused.status = e.status
            raise refused from e
        return str(data["id"])
