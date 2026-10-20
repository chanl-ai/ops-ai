"""What a module shows of its connection, and the seed's integration list as connection records (c-330).

The dev seed's integrations (`seed/tool_modules.json` `connections`) load as connection rows with the same ids, so a
seeded module keeps its `connectionId`. They carry no environment, so they add nothing to a call: the module's own
headers apply as before until someone sets the connection up.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# A consent this close to its end shows as expiring.
EXPIRING = timedelta(days=30)

# The seed's integration methods, as the auth kinds they would sign in with.
SEED_KINDS = {
    "api_key": "api_key",
    "service_principal": "oauth2_client_credentials",
    "oauth_consent": "oauth2_auth_code",
    "mtls": "none",
}

# A module's `auth.kind` (the console's ModuleAuth) for each connection kind.
MODULE_AUTH = {
    "none": "none",
    "api_key": "api_key",
    "basic": "basic",
    "bearer": "bearer",
    "oauth2_client_credentials": "oauth_client_credentials",
    "oauth2_auth_code": "oauth_authorization_code",
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


def ref_of(conn: dict[str, Any], now: datetime) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": conn["id"],
        "name": conn["name"],
        "kind": conn["auth_kind"],
        "status": status_of(conn, now),
    }
    if conn.get("expires_at"):
        out["expiresAt"] = conn["expires_at"].isoformat()
    return out


def module_auth(conn: dict[str, Any] | None) -> dict[str, str]:
    return {"kind": MODULE_AUTH.get(str(conn["auth_kind"]), "none") if conn else "none"}


def seed_rows(seed: dict[str, Any], tenant_id: str, team_id: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": tenant_id,
            "id": c["id"],
            "team_id": team_id,
            "name": c["name"],
            "auth_kind": SEED_KINDS.get(c["authMethod"], "none"),
            "available_to": None,
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
