"""The ways a connection signs in, as data: each kind's fields, which of them are secret, and whether it holds a token.

The console builds a connection's form from `GET /v1/connection-kinds`, and the service checks a connection's settings
against the same list, so a new kind is a row here plus its strategy in STRATEGIES (`auth/__init__.py`); nothing else
names kinds. A client certificate is not a kind: its fields belong to every kind (design round 2, Client certificate).
A field a setting turns on or off (the signing pair once `clientAuth` is `private_key_jwt`) says so in `requiredWhen` or
`optionalWhen`, and `Kind.requires` is the one reading of it, so the form and every check ask for the same fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ENVIRONMENTS = ("test", "production")
TEST, PRODUCTION = ENVIRONMENTS


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = False
    required: bool = False
    choices: tuple[str, ...] = ()
    default: str | None = None
    help: str = ""
    # Shown under More settings, with its default set.
    advanced: bool = False
    # Required once every setting named holds its value, or no longer required then; pairs, so the field stays hashable.
    required_when: tuple[tuple[str, str], ...] = ()
    optional_when: tuple[tuple[str, str], ...] = ()

    def required_for(self, settings: dict[str, Any]) -> bool:
        if self.required_when and all(settings.get(k) == v for k, v in self.required_when):
            return True
        if self.optional_when and all(settings.get(k) == v for k, v in self.optional_when):
            return False
        return self.required

    def view(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "advanced": self.advanced,
        }
        if self.choices:
            out["choices"] = list(self.choices)
        if self.default is not None:
            out["default"] = self.default
        if self.help:
            out["help"] = self.help
        if self.required_when:
            out["requiredWhen"] = dict(self.required_when)
        if self.optional_when:
            out["optionalWhen"] = dict(self.optional_when)
        return out


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    fields: tuple[Field, ...]
    # A person signs in once in the browser before tools can use it (the authorization code flow).
    signs_in: bool = False
    # Holds a token the gateway fetches and refreshes.
    holds_token: bool = False
    # Each person may sign in with their own account, so a call acts as the person it is for (c-558).
    per_person: bool = False

    def field(self, name: str) -> Field | None:
        return next((f for f in (*self.fields, *COMMON, *CERTIFICATE) if f.name == name), None)

    def requires(self, settings: dict[str, Any]) -> list[Field]:
        """The fields this kind needs with these plain settings (defaults applied), secret or not."""
        return [f for f in (*self.fields, *COMMON) if f.required_for(settings)]

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "fields": [f.view() for f in self.fields],
            "signsIn": self.signs_in,
            "holdsToken": self.holds_token,
            "perPerson": self.per_person,
        }


_SCOPES = Field("scopes", "Permissions to ask for", help="Separated by spaces, as the system names them.")
SIGNED = (("clientAuth", "private_key_jwt"),)
# Signing has its own pair, apart from the mTLS clientCertificate and clientKey, so the signing key is never offered in
# a TLS handshake or written out for one.
_SIGNING_CERTIFICATE = Field(
    "signingCertificate", "Signing certificate", help="PEM of the certificate registered with the system's app."
)
_SIGNING_KEY = Field("signingKey", "Signing key", secret=True, help="PEM private key of the signing certificate.")
_CLIENT_AUTH = Field(
    "clientAuth",
    "How the client is sent",
    choices=("body", "basic", "private_key_jwt"),
    default="body",
    advanced=True,
    help="In the request body, as a username and password, or as an assertion signed with the app's certificate.",
)
_SIGNED_PAIR = (
    Field(_SIGNING_CERTIFICATE.name, _SIGNING_CERTIFICATE.label, help=_SIGNING_CERTIFICATE.help, required_when=SIGNED),
    Field(_SIGNING_KEY.name, _SIGNING_KEY.label, secret=True, help=_SIGNING_KEY.help, required_when=SIGNED),
)

KINDS: tuple[Kind, ...] = (
    Kind("none", "No sign-in", ()),
    Kind(
        "api_key",
        "API key",
        (
            Field("placement", "Sent in", choices=("header", "query"), default="header", advanced=True),
            Field("name", "Header or query name", required=True, default="X-Api-Key"),
            Field("key", "Key", secret=True, required=True),
        ),
    ),
    Kind(
        "basic",
        "Username and password",
        (Field("username", "Username", required=True), Field("password", "Password", secret=True, required=True)),
    ),
    Kind(
        "bearer",
        "Bearer token",
        (
            Field("token", "Token", secret=True, required=True),
            Field("prefix", "Prefix", default="Bearer", advanced=True),
        ),
    ),
    Kind(
        "oauth2_client_credentials",
        "Client ID and secret (OAuth)",
        (
            Field("tokenUrl", "Token address", required=True),
            Field("clientId", "Client ID", required=True),
            Field("clientSecret", "Client secret", secret=True, required=True, optional_when=SIGNED),
            _SCOPES,
            Field("audience", "Audience", advanced=True),
            _CLIENT_AUTH,
            *_SIGNED_PAIR,
        ),
        holds_token=True,
    ),
    Kind(
        "oauth2_auth_code",
        "Sign in with an account",
        (
            Field("authorizeUrl", "Sign-in address", required=True),
            Field("tokenUrl", "Token address", required=True),
            Field("clientId", "Client ID", required=True),
            Field("clientSecret", "Client secret", secret=True, help="Leave empty for a public client."),
            _SCOPES,
            Field("resource", "Resource", advanced=True, help="The address the token is for, when the system asks."),
            _CLIENT_AUTH,
            *_SIGNED_PAIR,
            Field(
                "revokeUrl",
                "Revocation address",
                advanced=True,
                help="Where a sign-in is ended when a person disconnects (RFC 7009), when the system has one.",
            ),
        ),
        signs_in=True,
        holds_token=True,
        per_person=True,
    ),
    # RFC 7523's JWT grant: DocuSign's integration key and user, a Google service account's email and scopes.
    Kind(
        "oauth2_jwt_bearer",
        "Signed service account",
        (
            Field("tokenUrl", "Token address", required=True),
            Field("clientId", "Client ID", required=True, help="The issuer: an integration key or a service account."),
            Field("subject", "Acting as", help="The user the token acts for, when the system asks for one."),
            Field("audience", "Audience", advanced=True, help="The token address when empty."),
            _SCOPES,
            Field(
                "scopeIn",
                "Permissions sent",
                choices=("form", "claim"),
                default="form",
                advanced=True,
                help="In the token request, or as a claim in the signed grant (Google).",
            ),
            Field(_SIGNING_CERTIFICATE.name, _SIGNING_CERTIFICATE.label, help=_SIGNING_CERTIFICATE.help),
            Field(_SIGNING_KEY.name, _SIGNING_KEY.label, secret=True, required=True, help=_SIGNING_KEY.help),
        ),
        holds_token=True,
    ),
)

# Every environment names the system it signs in to: its credentials go to that address (scheme, host and port) only,
# whichever module uses the connection and whatever else is on the allow-list.
ADDRESS = Field(
    "baseUrl", "System address", required=True, help="https address of the system; its credentials go nowhere else."
)
# What Test connection reads (c-558): a path on the system address that answers any signed-in account, such as the
# identity provider's userinfo.
TEST_PATH = Field(
    "testPath",
    "Test address",
    advanced=True,
    help="A read on the system address that answers when the sign-in works, such as /services/oauth2/userinfo.",
)
COMMON: tuple[Field, ...] = (ADDRESS, TEST_PATH)

CERTIFICATE: tuple[Field, ...] = (
    Field("clientCertificate", "Client certificate", help="PEM, for systems that ask for one."),
    Field("clientKey", "Private key", secret=True),
    Field("trustedCa", "Trusted server certificate", help="PEM of the CA that signed the system's certificate."),
)

BY_ID = {k.id: k for k in KINDS}


def kind_of(kind_id: str) -> Kind:
    return BY_ID[kind_id]


def views() -> dict[str, Any]:
    return {
        "kinds": [k.view() for k in KINDS],
        "common": [f.view() for f in COMMON],
        "certificate": [f.view() for f in CERTIFICATE],
    }


def origin(url: str) -> tuple[str, str, int]:
    """Scheme, host and port: what a credential is bound to."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or (443 if scheme == "https" else 80)
