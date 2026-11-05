"""The accounts contract under `/v1/apps` and `/v1/me/accounts`. Secret values go in on `secretValues` or
`credentials` and never come out: an account says which secret parts are set, by whom and when."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ops_service_kit.http import Out

# Whose account a call signs in with: the team's one sign-in, the person the call acts for, or the person's
# with the team's as the backup for calls with nobody behind them.
SignIn = Literal["team", "person", "person_or_team"]


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# A credential value: a key, a password or token, or a PEM certificate or private key, the longest of them.
CREDENTIAL_MAX = 16_000


class NewAppIn(_In):
    """A custom app a builder adds, as its first account: by name with a sign-in kind, or an MCP server by its address,
    whose sign-in is found from the server."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    auth_kind: str | None = Field(default=None, min_length=1, max_length=40)
    sign_in: SignIn = "team"
    # What the console's card shows for a system connected by name; the docs link must be https.
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    docs_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    # An MCP server's address; its sign-in is found from the server's 401 and metadata.
    server_url: str | None = Field(default=None, min_length=8, max_length=2000)
    # The server's registered client, when its sign-in needs one ("Use the bank's registered client").
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=4000)
    sandbox: bool = False

    @model_validator(mode="after")
    def _named_or_addressed(self) -> NewAppIn:
        if self.server_url is None and (self.name is None or self.auth_kind is None):
            raise ValueError("Name the app and its sign-in kind, or give an MCP server's address.")
        return self


class AccountIn(_In):
    """Another account of an app the team has: a sandbox, or a second org of the same system. On a plugin's
    app it takes the first account's contract (the kind, whose account calls use, the OAuth app and the credentials);
    on a custom app it signs in with the app's kind, with the kind's fields given in `credentials`."""

    name: str = Field(min_length=1, max_length=200)
    sandbox: bool = False
    # A plugin's settings this account keeps its own, such as a sandbox's sign-in address.
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The team's app credential (GET /v1/app-credentials) the account signs in with; left out, Ops AI's app.
    credential_id: str | None = Field(default=None, min_length=1, max_length=64)
    sign_in: str | None = None
    kind: str | None = Field(default=None, max_length=50)
    # The kind's own fields and the client certificate's (auth/kinds.py), secret parts included. A secret part is
    # sealed and never answered back.
    credentials: dict[str, Annotated[str, Field(max_length=CREDENTIAL_MAX)]] = Field(
        default_factory=dict[str, str], max_length=20
    )


class AccountPatchIn(_In):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=200)
    sign_in: SignIn | None = None
    team_backup: bool | None = None
    # The account a test run of the app uses; a live run never signs in with it.
    sandbox: bool | None = None
    # What the console's card shows for a system connected by name; the docs link must be https.
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    docs_url: str | None = Field(default=None, max_length=500, pattern=r"^https://\S+$")
    # The team's app credential the account signs in with instead of the one it has; null puts it on Ops AI's app.
    # Its accounts sign in again.
    credential_id: str | None = Field(default=None, min_length=1, max_length=64)
    # The kind's plain settings and the client certificate's (GET /v1/connection-kinds lists them).
    settings: dict[str, Any] | None = None
    # Secret parts by field name; one left out keeps its stored value.
    secret_values: dict[str, str] = Field(default_factory=dict[str, str])


class SignInIn(_In):
    # On an account each person signs in to: `self` (the default) signs in the caller's own account, `team` the
    # team's backup account, which needs connections.manage.
    account: Literal["self", "team"] = "self"


class PersonCredentialsIn(_In):
    """A person's own key, password or token on an account each person signs in to: the kind's person
    fields, each a value of at most 2,000 characters."""

    credentials: dict[str, str] = Field(max_length=4)


class AccountTestIn(_In):
    # `self` tests with the caller's own sign-in on an account each person signs in to; `team` with the team's,
    # which needs connections.manage.
    account: Literal["self", "team"] = "self"


class ConnectLinkIn(_In):
    """A connect link a call that needed someone's own sign-in handed back; only that person opens it."""

    link: str = Field(min_length=16, max_length=200)


class SignInCompleteIn(_In):
    """What the sign-in page was handed back: the `code` of a sign-in the system allowed, or the `error` and
    `errorDescription` of one it refused, with the `state` either way."""

    state: str = Field(min_length=16, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=2000)
    error: str | None = Field(default=None, min_length=1, max_length=200)
    error_description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _code_or_error(self) -> SignInCompleteIn:
        if (self.code is None) == (self.error is None):
            raise ValueError("Hand back the sign-in's code, or the error it was refused with.")
        return self


class CheckedCredential(Out):
    status: Literal["ok", "failed"]
    # Who signed in, when the system's answer says; for display only.
    account: str | None = None
    message: str | None = None
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
    # Whether each person may sign in with their own account; a kind without it takes the team's only.
    per_person: bool
    # The fields each person gives for themselves on a connection each person signs in to; empty for a kind
    # whose person signs in at the system.
    person_fields: list[str]


class ConnectionKinds(Out):
    kinds: list[AuthKind]
    # Fields every account has whatever its kind: the system's address its credentials are bound to.
    common: list[KindField]
    certificate: list[KindField]
    # The return address to register with a system's sign-in, the same for every connection; none while the
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


class AccountEvent(Out):
    action: str
    actor: str
    at: str | None = None
    detail: dict[str, Any]


Status = Literal["draft", "healthy", "needs_reconnect", "expiring", "revoked", "error"]


class AccountTest(Out):
    """An account's last test: it runs right after a sign-in, and a failure warns without disconnecting it."""

    status: Literal["ok", "failed"]
    message: str | None = None
    at: str


class MyAccount(Out):
    """One of the caller's own sign-ins, as Your connections lists it."""

    connection_id: str
    # The account's app, under which its sign-in is started.
    app_id: str
    # The app's name and logo, as the Apps grid shows them; `connection` names the account.
    app: str
    logo: str | None = None
    connection: str
    # The connection's own status; the person's sign-in is held while it is listed.
    connection_status: str
    # A sandbox account, which only test runs use.
    sandbox: bool
    # How the person signs in: the connection kind's label, such as "API key" or "Sign in with an account".
    method: str
    auth_kind: str
    # What the person gives for a key, password or token kind; empty for a sign-in at the system.
    person_fields: list[str]
    # False for a connection the person can connect and has not, listed only with `every`.
    connected: bool
    # Where the system says how to find the key, from the connection's card details.
    docs_url: str | None = None
    # The system refused the person's key or sign-in: when, and what it said; a new one clears it.
    # The person's own sign-in's last test.
    test: AccountTest | None = None
    refused: bool = False
    refused_at: str | None = None
    refused_reason: str | None = None
    account: str | None = None
    scopes: list[str]
    since: str | None = None
    expires_at: str | None = None


class AccountRow(Out):
    id: str
    # The app it belongs to: `plugin:<id>` for a plugin's, the custom app's first account's id for a custom app's.
    app_id: str
    name: str
    auth_kind: str
    kind_label: str
    # The account a test run of the app uses; a live run never signs in with it.
    sandbox: bool
    status: Status
    status_detail: str | None = None
    team_id: str
    used_by: list[ModuleUse]
    revision: int
    updated_at: str | None = None
    # Whether the caller holds connections.manage: the console offers Connect, Set and Sign in only then.
    may_manage: bool
    sign_in: SignIn = "team"
    team_backup: bool = False
    # The account's last test.
    health: ConnectionHealth | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None
    # The name a tool or step uses for the account.
    account_name: str | None = None


class PersonSignedIn(Out):
    """One person's own sign-in on an account: admins see everyone's, a person their own."""

    person_id: str
    account: str | None = None
    since: str | None = None
    expires_at: str | None = None
    scopes: list[str]


class AccountDetail(AccountRow):
    settings: dict[str, str]
    secrets: dict[str, SecretPart]
    # The team's own sign-in on the account.
    signed_in: SignedIn | None = None
    # The signing certificate's view, never its key; null when the PEM held does not read.
    certificate: SigningCertificate | None = None
    # The plugin whose platform app the account signs in with; null on the team's own app.
    platform_app: str | None = None
    # The team's app credential it signs in with; null on Ops AI's app or a kind with no OAuth client.
    credential_id: str | None = None
    # An app from a plugin: its settings here as a call reads them, and for a secret one only whether it is set.
    plugin_settings: dict[str, Any] | None = None
    plugin_secrets: dict[str, bool] | None = None
    # The address to register with the system's sign-in, for a kind that signs in with an account.
    redirect_uri: str | None = None
    activity: list[AccountEvent]
    people: list[PersonSignedIn] = Field(default_factory=list[PersonSignedIn])


class SignInStart(Out):
    authorize_url: str
    redirect_uri: str
    expires_at: str | None = None
    connection_id: str | None = None
    # The account's app: the return page finishes the sign-in under it.
    app_id: str | None = None


class SignInFinished(Out):
    """A finished sign-in, as the return page tells the window that started it: the account and its app, and either
    the account signed in or, for Test with my account (`check`), the check's outcome."""

    app_id: str
    account_id: str
    check: bool
    account: AccountDetail | None = None
    health: CheckedCredential | None = None
