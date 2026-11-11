"""The service events an app's accounts are reported with (on the outbox). tools-service never opens a
Human Task itself: agents-service's event workflow for the event does, in the account's team.

A team account the system refused, or whose sign-in ended with nothing to renew it, is reported once per breakage: its
key names the account, the state and what the account was when it broke, so every call while it
stays broken finds the event already written, and an account fixed and broken again is reported again. A person who
connects their own account reports it under the key a refusal for them named (auth._not_linked), and a team account
signed in again reports it under the key its needs-reconnecting refusal named, so a run paused for either goes on."""

from __future__ import annotations

from datetime import datetime
from typing import Any

NEEDS_RECONNECT = "app_account.needs_reconnect"
# A person connected their own account of an app, by a sign-in or by giving their key: a run paused for it goes on.
CONNECTED = "app_account.connected"


def needs_reconnect_event(
    conn: dict[str, Any], *, state: str, reason: str, since: datetime | None, at: datetime
) -> dict[str, Any]:
    """The admins' notice for the team account of `conn`; `since` is when the token that broke was issued or ended
    (none when the account never held one)."""
    connection_id = str(conn["id"])
    broke = since.isoformat() if since is not None else "-"
    return {
        "tenant_id": str(conn["tenant_id"]),
        "team_id": str(conn["team_id"]),
        "name": NEEDS_RECONNECT,
        "key": f"{connection_id}:{state}:{conn['revision']}:{broke}",
        "payload": {
            "connectionId": connection_id,
            "app": str(conn["name"]),
            "appId": conn.get("app_id"),
            "sandbox": bool(conn.get("sandbox")),
            "state": state,
            "reason": reason,
            "at": at.isoformat(),
        },
    }


# The person part of the key a run waiting for a team account's new sign-in waits on.
TEAM = "team"


def connected_key(connection_id: str, person: str) -> str:
    """What a run waiting for `person`'s own account of the app waits on, and what their connecting reports; for the
    team's own sign-in (`person` empty), what a run waiting for an admin to sign the team account in again waits on."""
    return f"{connection_id}:{person or TEAM}"


def connected_event(conn: dict[str, Any], person: str) -> dict[str, Any]:
    """`person` connected their own account of `conn`; names only, never what they gave."""
    connection_id = str(conn["id"])
    return {
        "tenant_id": str(conn["tenant_id"]),
        "team_id": str(conn["team_id"]),
        "name": CONNECTED,
        "key": connected_key(connection_id, person),
        "payload": {"connectionId": connection_id, "app": str(conn["name"])},
    }
