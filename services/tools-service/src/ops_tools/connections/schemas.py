"""The `/v1/connections` contract. Secret values go in on `secretValues` and never come out: an environment says which
secret parts are set, by whom and when."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out

from ..environments import ConnectionEnvironment as Environment

Team = str
# Whose account a call signs in with (c-558): the team's one sign-in, the person the call acts for, or the person's
# with the team's as the backup for calls with nobody behind them.
SignIn = Literal["team", "person", "person_or_team"]


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class NewConnectionIn(_In):
    name: str = Field(min_length=1, max_length=200)
    auth_kind: str = Field(min_length=1, max_length=40)
    sign_in: SignIn = "team"
    # What the console's card shows for a system connected by name (c-580); the docs link must be https.
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    docs_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    # Accepted and ignored for one release, then removed (c-509): another team holds its own connection.
    available_to: list[Team] | None = Field(default=None, deprecated=True)


class ConnectionPatchIn(_In):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)
    sign_in: SignIn | None = None
    team_backup: bool | None = None
    # What the console's card shows for a system connected by name (c-580); the docs link must be https.
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    docs_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")
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
    # On a connection each person signs in to: `self` (the default) signs in the caller's own account, `team` the
    # team's backup account, which needs connections.manage.
    account: Literal["self", "team"] = "self"


class PersonCredentialsIn(_In):
    """A person's own key, password or token on a connection each person signs in to (c-595): the kind's person
    fields, each a value of at most 2,000 characters."""

    environment: Environment
    credentials: dict[str, str] = Field(max_length=4)


class ConnectionTestIn(_In):
    environment: Environment
    # `self` tests with the caller's own sign-in on a connection each person signs in to; `team` with the team's,
    # which needs connections.manage.
    account: Literal["self", "team"] = "self"


class ConnectLinkIn(_In):
    """A connect link a call that needed someone's own sign-in handed back; only that person opens it."""

    link: str = Field(min_length=16, max_length=200)


class SignInCompleteIn(_In):
    state: str = Field(min_length=16, max_length=200)
    code: str = Field(min_length=1, max_length=2000)


class CredentialCheckIn(_In):
    """Test with my account (c-616): `environment` starts it; the `state` and `code` the sign-in page was handed back
    finish it, on the same route."""

    environment: Environment = "production"
    state: str | None = Field(default=None, min_length=16, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=2000)


class CheckedCredential(Out):
    status: Literal["ok", "failed"]
    # Who signed in, when the system's answer says; for display only.
    account: str | None = None
    message: str | None = None
    environment: Environment
    at: str
    by: str


class CredentialCheck(Out):
    health: CheckedCredential


class KindField(Out):
    name: str
    label: str
    secret: bool
    required: bool
    advanced: bool
    choices: list[str] | None = None
    default: str | None = None
    help: str | None = None
    # Required once each named setting holds its value, or no longer required then (`Kind.requires`).
    required_when: dict[str, str] | None = None
    optional_when: dict[str, str] | None = None
    # PEM text: a multi-line box and a file to read it from, never one line.
    pem: bool = False


class AuthKind(Out):
    id: str
    label: str
    fields: list[KindField]
    signs_in: bool
    holds_token: bool
    # Whether each person may sign in with their own account (c-558); a kind without it takes the team's only.
    per_person: bool
    # The fields each person gives for themselves on a connection each person signs in to (c-595); empty for a kind
    # whose person signs in at the system.
    person_fields: list[str]


class EnvironmentOption(Out):
    id: str
    label: str
    # The one environment live runs call; every other run calls a non-production one.
    production: bool
    # Whether a connection holds keys for it; the console draws a key section for each that does.
    keys: bool


class ConnectionKinds(Out):
    kinds: list[AuthKind]
    # The environments a connection is set for, in order (c-580): the console draws one section per entry, so a new
    # environment is data here, not console code.
    environments: list[EnvironmentOption]
    # Fields every environment has whatever its kind: the system's address its credentials are bound to.
    common: list[KindField]
    certificate: list[KindField]
    # The return address to register with a system's sign-in, the same for every connection (c-580); none while the
    # console's address is not set.
    redirect_uri: str | None = None


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


class ConnectionHealth(Out):
    """The last Test connection: a read of the system's test address, signed in with `account`'s sign-in."""

    status: Literal["ok", "failed"]
    environment: Environment
    account: Literal["own", "team"]
    at: str
    by: str
    latency_ms: int | None = None
    http_status: int | None = None
    code: str | None = None
    message: str | None = None


class SigningCertificate(Out):
    thumbprint: str
    subject: str
    not_after: str
    # Within 30 days of its expiry: a team admin uploads the new one before sign-ins fail.
    expires_soon: bool


class ConnectionEnvironment(Out):
    set: bool
    settings: dict[str, str]
    secrets: dict[str, SecretPart]
    signed_in: SignedIn | None = None
    # The signing certificate's view, never its key (c-583); null when the PEM held does not read.
    certificate: SigningCertificate | None = None
    # This environment's last Test connection (c-580); the connection's `health` is the deciding environment's.
    health: ConnectionHealth | None = None
    # The plugin whose platform app this environment signs in with (c-565); null on the team's own app.
    platform_app: str | None = None


class ConnectionEvent(Out):
    action: str
    environment: str | None = None
    actor: str
    at: str | None = None
    detail: dict[str, Any]


Status = Literal["draft", "healthy", "needs_reconnect", "expiring", "revoked", "error"]


class MyConnection(Out):
    """One of the caller's own sign-ins (c-558), as Your connections lists it."""

    connection_id: str
    connection: str
    # The connection's own status; the person's sign-in is held while it is listed.
    connection_status: str
    environment: Environment
    # How the person signs in: the connection kind's label, such as "API key" or "Sign in with an account" (c-595).
    method: str
    auth_kind: str
    # What the person gives for a key, password or token kind; empty for a sign-in at the system.
    person_fields: list[str]
    # False for a connection the person can connect and has not, listed only with `every` (c-595).
    connected: bool
    # Where the system says how to find the key, from the connection's card details.
    docs_url: str | None = None
    # The system refused the person's key or sign-in (c-595): when, and what it said; a new one clears it.
    refused: bool = False
    refused_at: str | None = None
    refused_reason: str | None = None
    account: str | None = None
    scopes: list[str]
    since: str | None = None
    expires_at: str | None = None


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
    sign_in: SignIn = "team"
    team_backup: bool = False
    # The deciding environment's last test: production when it is set, else test (c-580).
    health: ConnectionHealth | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None
    # An app's account (c-608): the plugin it belongs to and the name a tool or step uses for it.
    plugin_id: str | None = None
    account_name: str | None = None


class PersonSignedIn(Out):
    """One person's own sign-in on a connection: admins see everyone's, a person their own."""

    person_id: str
    environment: Environment
    account: str | None = None
    since: str | None = None
    expires_at: str | None = None
    scopes: list[str]


class ConnectionDetail(ConnectionRow):
    environments: dict[str, ConnectionEnvironment]
    # The address to register with the system's sign-in, for a kind that signs in with an account.
    redirect_uri: str | None = None
    activity: list[ConnectionEvent]
    people: list[PersonSignedIn] = Field(default_factory=list[PersonSignedIn])


class ConnectionList(ListResult[ConnectionRow]):
    """GET /v1/connections: one page, by name."""


class SignInStart(Out):
    authorize_url: str
    redirect_uri: str
    expires_at: str | None = None
    connection_id: str | None = None
