"""What a module shows of its connection, and the seed's integration list as connection records.

The dev seed's integrations (`seed/tool_modules.json` `connections`) load as connection rows with the same ids, so a
seeded module keeps its `connectionId`. They carry no environment, so they add nothing to a call: the module's own
headers apply as before until someone sets the connection up.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

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


def deciding_environment(conn: dict[str, Any]) -> str:
    """The environment whose sign-in stands for the connection: production once it is set, else test."""
    return "production" if "production" in (conn.get("environments") or {}) else "test"


def connection_base(conn: dict[str, Any]) -> str:
    """The app's base address a new tool's path hangs off: the deciding environment's, else any environment's; empty
    when none names one. A call reads its own environment's (Authenticator.addressed)."""
    envs: dict[str, dict[str, Any]] = conn.get("environments") or {}
    ordered = [envs.get(deciding_environment(conn)) or {}, *envs.values()]
    found = (str(s["baseUrl"]) for e in ordered if (s := cast(dict[str, Any], e.get("settings") or {})).get("baseUrl"))
    return next(found, "")


def account_state(conn: dict[str, Any], team_token: dict[str, Any] | None, now: datetime) -> str:
    """The team account's state from its token in the deciding environment, never from the saved settings: refused
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
    envs = cast(dict[str, dict[str, Any]], conn.get("environments") or {})
    env = envs.get(deciding_environment(conn)) or {}
    health = cast(dict[str, Any], env.get("health") or {})
    if stored == "needs_reconnect":
        return REFUSED
    return CONNECTED if health.get("status") == "ok" and health.get("account") != "own" else NOT_SIGNED_IN


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
    envs: dict[str, dict[str, Any]] = conn.get("environments") or {}
    out: dict[str, Any] = {
        "id": conn["id"],
        "name": conn["name"],
        "kind": conn["auth_kind"],
        "status": status_of(conn, now),
        # Where a module's paths go in each environment: the connection's base address is their only one.
        "baseUrls": {
            env: str(base)
            for env, row in envs.items()
            if (base := cast(dict[str, Any], row.get("settings") or {}).get("baseUrl"))
        },
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
            "revision": 1,
            "created_by": "seed",
            "created_at": now,
            "updated_by": "seed",
            "updated_at": now,
        }
        for c in seed.get("connections", [])
    ]
