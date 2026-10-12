"""Request and response models for platform-service. Requests refuse unknown fields (I5), and none names a tenant or
team (I1): both come from the identity."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from ops_service_kit.http import Out


class In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SignIn(In):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(max_length=200)


class Refresh(In):
    refresh_token: str = Field(min_length=10, max_length=200)


class Introspect(In):
    api_key: str = Field(min_length=1, max_length=200)


class Principal(Out):
    kind: Literal["person", "api_key", "service"]
    sub: str
    email: str
    name: str
    tenant_id: str
    team_id: str | None
    team_ids: list[str]
    roles: dict[str, str]
    scopes: list[str]
    auth_method: str


class SessionOut(Out):
    token: str
    refresh_token: str
    expires_at: str
    principal: Principal


class Jwk(BaseModel):
    """A public key as RFC 7517 names its fields, so they stay snake-free and unaliased."""

    model_config = ConfigDict(extra="forbid")
    kty: str
    crv: str
    x: str
    kid: str
    alg: str
    use: str


class Jwks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[Jwk]


class Health(Out):
    status: str


ROLE = r"^(admin|builder|approver|viewer)$"
MEMBER_ID = r"^mem_[A-Za-z0-9_-]{1,60}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MeUser(Out):
    id: str
    email: str
    name: str


class MeTeam(Out):
    id: str
    name: str
    role: str


class Me(Out):
    user: MeUser
    tenant_id: str
    teams: list[MeTeam]


class TeamOut(Out):
    id: str
    name: str
    owner_groups: list[str]
    scope: str
    role: str
    member_count: int


class MemberOut(Out):
    id: str
    name: str
    email: str
    role: str
    team_id: str
    team: str
    status: Literal["active", "invited"]
    invited_at: str | None = None


class InviteIn(In):
    emails: list[Annotated[str, StringConstraints(pattern=EMAIL, max_length=320)]] = Field(min_length=1, max_length=50)
    role: str = Field(pattern=ROLE)


class RoleIn(In):
    ids: list[Annotated[str, StringConstraints(pattern=MEMBER_ID)]] = Field(min_length=1, max_length=100)
    role: str = Field(pattern=ROLE)


class DeleteIn(In):
    ids: list[Annotated[str, StringConstraints(pattern=MEMBER_ID)]] = Field(min_length=1, max_length=100)


class Skip(Out):
    id: str
    reason: str


class BulkOut(Out):
    updated: list[str]
    skipped: list[Skip]


class InviteLink(Out):
    member_id: str
    email: str
    token: str


class InviteBulkOut(BulkOut):
    invites: list[InviteLink]


class InvitePreview(Out):
    token: str
    email: str
    team_id: str
    team: str
    role: str
    invited_at: str
    expires_at: str
    state: Literal["pending", "expired", "accepted"]


class AcceptIn(In):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyOut(Out):
    id: str
    name: str
    prefix: str
    scopes: list[Literal["read", "write"]]
    created_by: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    team: str
    status: Literal["active", "revoked", "disabled"]


class ApiKeyIn(In):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[Literal["read", "write"]] = Field(min_length=1, max_length=2)
    expires_in_days: int | None = Field(default=None, ge=1, le=730)


class ApiKeyCreated(Out):
    key: ApiKeyOut
    secret: str


class AuditEntryOut(Out):
    id: str
    team_id: str | None
    actor: str
    action: str
    target_kind: str
    target_id: str
    request_id: str
    at: str
    detail: dict[str, Any]
