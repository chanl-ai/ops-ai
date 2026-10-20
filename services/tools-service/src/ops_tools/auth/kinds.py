"""The ways a connection signs in, as data: each kind's fields, which of them are secret, and whether it holds a token.

The console builds a connection's form from `GET /v1/connection-kinds`, and the service checks a connection's settings
against the same list, so a new kind is a row here plus its strategy in `strategies.py`; nothing else names kinds.
A client certificate is not a kind: its fields belong to every kind (design round 2, Client certificate).
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

    def field(self, name: str) -> Field | None:
        return next((f for f in (*self.fields, *COMMON, *CERTIFICATE) if f.name == name), None)

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "fields": [f.view() for f in self.fields],
            "signsIn": self.signs_in,
            "holdsToken": self.holds_token,
        }


_SCOPES = Field("scopes", "Permissions to ask for", help="Separated by spaces, as the system names them.")

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
            Field("clientSecret", "Client secret", secret=True, required=True),
            _SCOPES,
            Field("audience", "Audience", advanced=True),
            Field(
                "clientAuth",
                "How the client is sent",
                choices=("body", "basic"),
                default="body",
                advanced=True,
                help="In the request body, or as a username and password.",
            ),
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
            Field("clientAuth", "How the client is sent", choices=("body", "basic"), default="body", advanced=True),
        ),
        signs_in=True,
        holds_token=True,
    ),
)

# Every environment names the system it signs in to: its credentials go to that address (scheme, host and port) only,
# whichever module uses the connection and whatever else is on the allow-list.
ADDRESS = Field(
    "baseUrl", "System address", required=True, help="https address of the system; its credentials go nowhere else."
)
COMMON: tuple[Field, ...] = (ADDRESS,)

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
