"""The lookups that run before the tenant is known, one function each on both databases.

Each takes an exact key (or, for the watch and the purge, nothing) and returns fixed columns of the rows it names, so
the tenant role, which reads no row with no tenant set, learns only what verifying needs. On PostgreSQL they are the
SECURITY DEFINER functions of migrations 0004 to 0035, owned by `ops_platform_lookup`. On SQL Server they are
multi-statement table-valued functions (an inline one cannot take EXECUTE AS) that run as `ops_platform_system`, a
database user without a login that nobody may impersonate, which the platform read predicates pass; it holds no table
grant, since each function and its tables share an owner. The runtime user holds SELECT on the functions and nothing
else new (migration 0042, `deploy/database/mssql.py` LOOKUP_USERS).

`lookup` is the one way a store calls them: the same statement on both databases, with the result columns typed so a
JSON list and a flag read the same from each. A change to a SQL Server body here is a new migration that makes the
function again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

SYSTEM_USER = "ops_platform_system"
# A key wider than any column it is compared with, so a longer value is never cut to match a shorter stored one.
_KEY = "VARCHAR(8000)"
_TEXT = "VARCHAR(400)"


@dataclass(frozen=True)
class Lookup:
    name: str
    params: tuple[str, ...]
    columns: tuple[tuple[str, sa.types.TypeEngine[Any]], ...]
    # The SQL Server body: one SELECT whose columns are `columns`, in order, reading each parameter as @<name>.
    mssql: str


def _cols(*names: str, **typed: sa.types.TypeEngine[Any]) -> tuple[tuple[str, sa.types.TypeEngine[Any]], ...]:
    return tuple((n, typed.get(n, sa.String())) for n in names)


USERS_BY_EMAIL = Lookup(
    "platform_users_by_email",
    ("email",),
    _cols("tenant_id", "id", "email", "name"),
    "SELECT u.tenant_id, u.id, u.email, u.name FROM dbo.users u WHERE LOWER(u.email) = LOWER(@email)"
    " AND u.status = 'active'",
)
SESSION = Lookup(
    "platform_session",
    ("session_id",),
    _cols("tenant_id", "user_id", "id"),
    "SELECT s.tenant_id, s.user_id, s.id FROM dbo.sessions s WHERE s.id = @session_id",
)
KEY = Lookup(
    "platform_key",
    ("prefix", "now"),
    _cols(
        "id",
        "tenant_id",
        "team_id",
        "secret_hash",
        "scopes",
        "created_by",
        "usable",
        scopes=sa.JSON(),
        usable=sa.Boolean(),
    ),
    "SELECT k.id, k.tenant_id, k.team_id, k.secret_hash, k.scopes, k.created_by, CAST(CASE WHEN k.revoked_at IS NULL"
    " AND k.disabled_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > @now) THEN 1 ELSE 0 END AS BIT)"
    " FROM dbo.api_keys k WHERE k.prefix = @prefix",
)
TEAM = Lookup(
    "platform_team",
    ("team_id",),
    _cols("tenant_id", "id", "status"),
    "SELECT t.tenant_id, t.id, t.status FROM dbo.teams t WHERE t.id = @team_id",
)
SIGNIN_FLOW = Lookup(
    "platform_signin_flow",
    ("state_hash",),
    _cols("id", "tenant_id"),
    "SELECT f.id, f.tenant_id FROM dbo.signin_flows f WHERE f.state_hash = @state_hash",
)
SIGNIN_HANDOFF = Lookup(
    "platform_signin_handoff",
    ("handoff_hash",),
    _cols("id", "tenant_id"),
    "SELECT f.id, f.tenant_id FROM dbo.signin_flows f WHERE f.handoff_hash = @handoff_hash",
)
SIGNIN_DOMAIN = Lookup(
    "platform_signin_domain",
    ("domain",),
    _cols(
        "tenant_id",
        "provider_id",
        "kind",
        "label",
        "enabled",
        "password_enabled",
        enabled=sa.Boolean(),
        password_enabled=sa.Boolean(),
    ),
    "SELECT d.tenant_id, d.provider_id, p.kind, p.label, p.enabled, CAST(CASE WHEN EXISTS (SELECT 1 FROM"
    " dbo.signin_providers q WHERE q.tenant_id = d.tenant_id AND q.kind = 'password' AND q.enabled = 1)"
    " THEN 1 ELSE 0 END AS BIT) FROM dbo.signin_domains d"
    " JOIN dbo.signin_providers p ON p.id = d.provider_id AND p.tenant_id = d.tenant_id"
    " WHERE d.domain = LOWER(@domain) AND d.verified_at IS NOT NULL",
)
SIGNIN_SP = Lookup(
    "platform_signin_sp",
    ("sp_id",),
    _cols("tenant_id", "provider_id", "kind", "enabled", "tiles", enabled=sa.Boolean(), tiles=sa.Boolean()),
    # PostgreSQL reads the flag with json_extract_path_text(config, 'tiles')::boolean, true when absent.
    "SELECT p.tenant_id, p.id, p.kind, p.enabled, CAST(CASE WHEN COALESCE(JSON_VALUE(p.config, '$.tiles'), 'true')"
    " <> 'false' THEN 1 ELSE 0 END AS BIT) FROM dbo.signin_providers p WHERE p.sp_id = @sp_id",
)
WATCHED_PROVIDERS = Lookup(
    "platform_signin_watch",
    (),
    _cols("tenant_id", "provider_id"),
    "SELECT p.tenant_id, p.id FROM dbo.signin_providers p JOIN dbo.tenants t ON t.id = p.tenant_id"
    " WHERE p.kind = 'saml' AND t.status = 'active'",
)
PASSWORD_RESET = Lookup(
    "platform_password_reset",
    ("token_hash",),
    _cols("id", "tenant_id"),
    "SELECT r.id, r.tenant_id FROM dbo.password_resets r WHERE r.token_hash = @token_hash",
)
INVITE = Lookup(
    "platform_invite",
    ("token_hash",),
    _cols(
        "member_id",
        "tenant_id",
        "team_id",
        "team",
        "email",
        "role",
        "status",
        "invited_at",
        "expires_at",
        "allowed_domains",
        allowed_domains=sa.JSON(),
    ),
    "SELECT m.id, m.tenant_id, m.team_id, t.name, m.email, m.role, m.status, m.created_at, m.invite_expires_at,"
    " n.allowed_domains FROM dbo.members m JOIN dbo.teams t ON t.id = m.team_id"
    " JOIN dbo.tenants n ON n.id = m.tenant_id WHERE m.invite_token_hash = @token_hash",
)
PURGE_DUE = Lookup(
    "platform_purge_due",
    ("cutoff",),
    _cols("tenant_id"),
    "SELECT t.id FROM dbo.tenants t WHERE t.status = 'closed' AND t.closed_at <= @cutoff",
)
LOOKUPS = (
    USERS_BY_EMAIL, SESSION, KEY, TEAM, SIGNIN_FLOW, SIGNIN_HANDOFF, SIGNIN_DOMAIN, SIGNIN_SP, WATCHED_PROVIDERS,
    PASSWORD_RESET, INVITE, PURGE_DUE,
)  # fmt: skip


async def lookup(c: AsyncConnection, fn: Lookup, *values: str) -> Sequence[sa.Row[*tuple[Any, ...]]]:
    """The rows `fn` returns for `values`, its parameters in order."""
    if len(values) != len(fn.params):
        raise TypeError(f"{fn.name} takes {len(fn.params)} values, given {len(values)}")
    call = getattr(sa.func, fn.name)(
        *(sa.bindparam(p, v, type_=sa.String()) for p, v in zip(fn.params, values, strict=True))
    )
    found = call.table_valued(*(sa.column(n, t) for n, t in fn.columns))
    return (await c.execute(sa.select(*found.c))).all()


def _mssql_type(t: sa.types.TypeEngine[Any]) -> str:
    return "BIT" if isinstance(t, sa.Boolean) else "NVARCHAR(max)" if isinstance(t, sa.JSON) else _TEXT


def mssql_function(fn: Lookup) -> str:
    """The CREATE FUNCTION of `fn` on SQL Server."""
    params = ", ".join(f"@{p} {_KEY}" for p in fn.params)
    returns = ", ".join(f"{n} {_mssql_type(t)}" for n, t in fn.columns)
    return (
        f"CREATE FUNCTION dbo.{fn.name} ({params})\nRETURNS @found TABLE ({returns})\n"
        f"WITH EXECUTE AS '{SYSTEM_USER}'\nAS BEGIN\n    INSERT INTO @found {fn.mssql};\n    RETURN;\nEND"
    )
