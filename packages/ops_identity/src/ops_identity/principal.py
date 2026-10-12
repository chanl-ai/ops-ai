"""What every service knows about its caller once `ops_identity` has resolved the request (spec section 4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["person", "api_key", "service"]
    sub: str
    email: str
    name: str
    # From the token or key, never from a header, body or path (I1).
    tenant_id: str
    # The one team this request acts in; None for a service call, which acts for the tenant.
    team_id: str | None
    team_ids: list[str]
    # Team id to role, from membership when the token was issued.
    roles: dict[str, str]
    # API keys only: read, write.
    scopes: list[str]
    auth_method: Literal["dev", "session", "api_key", "service"]

    @property
    def role(self) -> str | None:
        """The caller's role in the current team."""
        return self.roles.get(self.team_id) if self.team_id else None
