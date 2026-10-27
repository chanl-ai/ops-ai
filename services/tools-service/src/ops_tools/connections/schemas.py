"""The `/v1/connections` contract. Secret values go in on `secretValues` and never come out: an environment says which
secret parts are set, by whom and when."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out

Environment = Literal["test", "production"]
Team = str


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class NewConnectionIn(_In):
    name: str = Field(min_length=1, max_length=200)
    auth_kind: str = Field(min_length=1, max_length=40)
    # Accepted and ignored for one release, then removed (c-509): another team holds its own connection.
    available_to: list[Team] | None = Field(default=None, deprecated=True)


class ConnectionPatchIn(_In):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)
    # Accepted and ignored for one release, then removed (c-509).
    available_to: list[Team] | None = Field(default=None, deprecated=True)


class EnvironmentIn(_In):
    revision: int = Field(ge=1)
    # The kind's plain settings and the client certificate's (GET /v1/connection-kinds lists them).
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    # Secret parts by field name; one left out keeps its stored value.
    secret_values: dict[str, str] = Field(default_factory=dict[str, str])


class McpConnectionIn(_In):
    """An MCP server by its address; its sign-in is found from the server (c-331)."""

    server_url: str = Field(min_length=8, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    environment: Environment = "test"
    # The bank's registered client, when the server's sign-in needs one ("Use the bank's registered client").
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=4000)


class SignInIn(_In):
    environment: Environment


class SignInCompleteIn(_In):
    state: str = Field(min_length=16, max_length=200)
    code: str = Field(min_length=1, max_length=2000)


class KindField(Out):
    name: str
    label: str
    secret: bool
    required: bool
    advanced: bool
    choices: list[str] | None = None
    default: str | None = None
    help: str | None = None


class AuthKind(Out):
    id: str
    label: str
    fields: list[KindField]
    signs_in: bool
    holds_token: bool


class ConnectionKinds(Out):
    kinds: list[AuthKind]
    # Fields every environment has whatever its kind: the system's address its credentials are bound to.
    common: list[KindField]
    certificate: list[KindField]


class ModuleUse(Out):
    id: str
    name: str


class SecretPart(Out):
    set: bool
    set_by: str | None = None
    set_at: str | None = None


class SignedIn(Out):
    account: str | None = None
    since: str | None = None
    expires_at: str | None = None
    scopes: list[str]


class ConnectionEnvironment(Out):
    set: bool
    settings: dict[str, str]
    secrets: dict[str, SecretPart]
    signed_in: SignedIn | None = None


class ConnectionEvent(Out):
    action: str
    environment: str | None = None
    actor: str
    at: str | None = None
    detail: dict[str, Any]


Status = Literal["draft", "healthy", "needs_reconnect", "expiring", "revoked", "error"]


class ConnectionRow(Out):
    id: str
    name: str
    auth_kind: str
    kind_label: str
    status: Status
    status_detail: str | None = None
    team_id: str
    available_to: list[str]
    used_by: list[ModuleUse]
    environments_set: list[str]
    revision: int
    updated_at: str | None = None
    # Whether the caller holds connections.manage: the console offers New connection, Set and Sign in only then.
    may_manage: bool


class ConnectionDetail(ConnectionRow):
    environments: dict[str, ConnectionEnvironment]
    # The address to register with the system's sign-in, for a kind that signs in with an account.
    redirect_uri: str | None = None
    activity: list[ConnectionEvent]


class ConnectionList(ListResult[ConnectionRow]):
    """GET /v1/connections: one page, by name."""


class SignInStart(Out):
    authorize_url: str
    redirect_uri: str
    expires_at: str | None = None
