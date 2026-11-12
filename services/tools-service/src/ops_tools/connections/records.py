"""What a module shows of its connection, and the seed's integration list as connection records.

The dev seed's integrations (`seed/tool_modules.json` `connections`) load as connection rows with the same ids, so a
seeded module keeps its `connectionId`. They carry no settings, so they add nothing to a call: the module's own
headers apply as before until someone sets the connection up.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from ..environments import LIVE

Row = dict[str, Any]

# A consent this close to its end shows as expiring.
EXPIRING = timedelta(days=30)

# The seed's integration methods, as the auth kinds they would sign in with.
SEED_KINDS = {
    "api_key": "api_key",
    "service_principal": "oauth2_client_credentials",
    "oauth_consent": "oauth2_auth_code",
    "mtls": "none",
}

# The names a module stored before connections, read for one release: a module now says what its connection says, so
# `either` is person_or_team and its auth kind is the connection's kind. `mtls` was never a kind: a client certificate
# belongs to any kind (auth/kinds.py), so it reads as kind none with a certificate.
OLD_SIGN_IN = {"either": "person_or_team"}
OLD_AUTH_KIND = {
    "oauth_client_credentials": "oauth2_client_credentials",
    "oauth_authorization_code": "oauth2_auth_code",
}


def status_of(conn: dict[str, Any], now: datetime) -> str:
    base = str(conn["status"])
    if base in ("draft", "revoked", "error"):
        return base
    expires: datetime | None = conn.get("expires_at")
    left = expires - now if expires else None
    if base == "needs_reconnect" or (left is not None and left < timedelta(0)):
        return "needs_reconnect"
    return "expiring" if left is not None and left < EXPIRING else "healthy"


# An app's account as people see it. Saving keys or choosing an app credential proves nothing about the
# account, so an app reads Connected only once the team account holds a token or Test connection last passed.
CONNECTED, NOT_SIGNED_IN, EXPIRED, REFUSED, REVOKED = "connected", "not_signed_in", "expired", "refused", "revoked"


def account_for(chosen: Row | None, accounts: Sequence[Row], run: str) -> Row | None:
    """The account a call made in `run` signs in with: a test run uses the app's sandbox account when it has one, else
    `chosen` (the account a live call would use: one a step named, the person's default, or the app's default); a live
    run uses `chosen`. Every choice of a call's account between sandbox and live is made here. A live run on a sandbox
    account is refused where it signs in (Authenticator.prepare), and the gateway holds a test run's write on a live
    account for a person (gateway_calls)."""
    if run != LIVE:
        sandbox = next((a for a in accounts if a.get("sandbox")), None)
        if sandbox is not None:
            return sandbox
    return chosen


def connection_base(conn: Row) -> str:
    """The app's base address a new tool's path hangs off; empty when the account names none."""
    return str(cast(Row, conn.get("settings") or {}).get("baseUrl") or "")


def account_state(conn: dict[str, Any], team_token: dict[str, Any] | None, now: datetime) -> str:
    """The team account's state from its token, never from the saved settings: refused
    once the system refused it (the row's refused_at, or the connection marked by the gateway), expired once its
    token ended with no refresh token to renew it. With no token, a passing Test connection is what shows a key or
    password works."""
    stored = str(conn.get("status") or "draft")
    if stored == REVOKED:
        return REVOKED
    if conn.get("auth_kind") == "none" and stored != "needs_reconnect":
        # An app that needs no sign-in has no token and no key to test, so nothing else could ever show it connected.
        return CONNECTED
    if team_token is not None:
        expires: datetime | None = team_token.get("expires_at")
        if team_token.get("refused_at") is not None or stored == "needs_reconnect":
            return REFUSED
        if expires is not None and expires < now and not team_token.get("refresh_ct"):
            return EXPIRED
        return CONNECTED
    health = cast(Row, conn.get("health") or {})
    if stored == "needs_reconnect":
        return REFUSED
    return CONNECTED if health.get("status") == "ok" and health.get("account") != "own" else NOT_SIGNED_IN


def person_state(token: dict[str, Any], now: datetime) -> str:
    """A person's own sign-in's state from their token row: refused once the system refused it, expired once it ended
    with no way to renew, else connected."""
    if token.get("refused_at") is not None:
        return REFUSED
    expires: datetime | None = token.get("expires_at")
    if expires is not None and expires < now and not token.get("renews"):
        return EXPIRED
    return CONNECTED


def choice_needed(mine: Sequence[Row]) -> bool:
    """Whether a call naming no account must ask the person which to use: two or more live sign-ins of their own to the
    app's accounts and none pinned as their default. Taking the newest would act in an org the person did not pick."""
    live = [t for t in mine if t.get("refused_at") is None]
    return len(live) > 1 and not any(t.get("pinned") for t in live)


def default_sign_in(mine: Sequence[Row]) -> Row | None:
    """A person's default among their own sign-ins to one app's accounts, given newest first with sandbox accounts
    left out: the one they pinned, else the newest the system has not refused. Calls naming no account use it."""
    live = [t for t in mine if t.get("refused_at") is None]
    return next((t for t in live if t.get("pinned")), None) or (live[0] if live else None)


def team_test(conn: dict[str, Any], team_token: dict[str, Any] | None) -> dict[str, Any] | None:
    """The team account's last test: kept on its token row after a sign-in, else (a key or password, which has no
    token) the account's last test made as the team."""
    if team_token is not None and team_token.get("test"):
        return cast(dict[str, Any], team_token["test"])
    health = cast(Row, conn.get("health") or {})
    if health.get("account") != "team" or health.get("status") not in ("ok", "failed"):
        return None
    return {"status": health["status"], "message": health.get("message"), "at": health.get("at")}


def state_reason(conn: dict[str, Any], team_token: dict[str, Any] | None, state: str) -> str | None:
    """Why the team account is refused or expired: the system's words, or the day its sign-in ended."""
    if state == REFUSED:
        return str((team_token or {}).get("refused_reason") or conn.get("status_detail") or "") or None
    if state == EXPIRED and team_token is not None and (ended := team_token.get("expires_at")) is not None:
        return f"The sign-in ended on {ended.day} {ended:%b %Y}."
    return None


def shown_status(conn: dict[str, Any], state: str, now: datetime) -> str:
    """The status word today's screens read, from the state: Connected keeps healthy or expiring, a refused or expired
    account needs reconnecting, and an account never signed in stays a draft (or the error its last test found)."""
    if state == CONNECTED:
        status = status_of(conn, now)
        return status if status in ("healthy", "expiring") else "healthy"
    if state in (REFUSED, EXPIRED):
        return "needs_reconnect"
    if state == REVOKED:
        return REVOKED
    return "error" if conn.get("status") == "error" else "draft"


def ref_of(conn: dict[str, Any], now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": conn["id"],
        "name": conn["name"],
        "kind": conn["auth_kind"],
        "status": status_of(conn, now),
        # Where a module's paths go: the account's base address is their only one.
        "baseUrl": connection_base(conn) or None,
    }
    if conn.get("expires_at"):
        out["expiresAt"] = conn["expires_at"].isoformat()
    return out


def module_auth(conn: dict[str, Any] | None) -> dict[str, str]:
    return {"kind": str(conn["auth_kind"]) if conn else "none"}


def auth_of(stored: dict[str, Any]) -> dict[str, Any]:
    """A module's auth as the API shows it, in the connections' kind names whichever names it was stored with."""
    out = {k: v for k, v in stored.items() if v is not None}
    kind = str(out.get("kind") or "none")
    if kind == "mtls":
        return {**out, "kind": "none", "certificate": True}
    return {**out, "kind": OLD_AUTH_KIND.get(kind, kind)}


def sign_in_of(stored: object) -> str:
    """A module's sign-in in the connections' names, `person_or_team` when it was never set."""
    value = str(stored or "person_or_team")
    return OLD_SIGN_IN.get(value, value)


def seed_rows(seed: dict[str, Any], tenant_id: str, team_id: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": tenant_id,
            "id": c["id"],
            "team_id": team_id,
            "name": c["name"],
            "auth_kind": SEED_KINDS.get(c["authMethod"], "none"),
            "status": c["base"],
            "status_detail": None,
            "expires_at": now + timedelta(days=c["expiresIn"]) if c.get("expiresIn") is not None else None,
            "catalog_id": c.get("catalogId"),
            "app_id": c["id"],
            "settings": {},
            "secrets": {},
            "revision": 1,
            "created_by": "seed",
            "created_at": now,
            "updated_by": "seed",
            "updated_at": now,
        }
        for c in seed.get("connections", [])
    ]
