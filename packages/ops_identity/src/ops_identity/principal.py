"""What every service knows about its caller once `ops_identity` has resolved the request (spec section 4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    # API keys: read, write. Service tokens: `area:action` scopes (ops_access).
    scopes: list[str]
    auth_method: Literal["dev", "session", "api_key", "service"]
    # Team id (or `*` for every team) to the role ids the person holds there, from the token's `access` claim; empty for
    # a token issued before roles were data, which ops_access maps from `roles`.
    access: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    # The tenant's permission version when the token was issued; ops_access caches role grids under it.
    permission_version: int | None = None
    # The tenant's access policies when the token was issued (c-186), key to value; a key missing here has its open
    # default (ops_access.POLICIES), so a token from before policies existed holds nothing back.
    policies: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The workspace's security team when the token was issued (c-202), which holds the Security team's actions; None
    # for a token without it, which ops_access answers from the deployment's setting.
    security_team: str | None = None
    # An API key's own id, and the one agent or workflow it may start (`{kind, id, version}`), from introspection only
    # (c-246); None for a person, a service, or a key with no target.
    key_id: str | None = None
    key_target: dict[str, Any] | None = None

    @property
    def role(self) -> str | None:
        """The caller's role in the current team."""
        return self.roles.get(self.team_id) if self.team_id else None
