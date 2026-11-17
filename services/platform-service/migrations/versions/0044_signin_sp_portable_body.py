"""signin_sp_portable_body: every database's platform_signin_sp reads `tiles` the same way

0034 created `platform_signin_sp` reading the provider's `tiles` setting with `->>`; its released text reads it with
`json_extract_path_text`. The two answer alike, but a database that ran 0034 before that change still holds the first
body, so its schema differs from one the chain builds today. CREATE OR REPLACE sets the released body, which leaves
the function's owner, grants and settings as they are and changes nothing on a database that already holds it. The
downgrade sets the same released body, which is what 0034 leaves on a database built from the chain; the first body
is not restored, because no database can tell which one it held. PostgreSQL only: SQL Server's function comes from
0042 and the golden DDL, neither of which ever held the first body.

Revision ID: 0044_signin_sp_portable_body
Revises: 0043_roles_by_builtin
"""

from __future__ import annotations

from alembic import op

revision = "0044_signin_sp_portable_body"
down_revision = "0043_roles_by_builtin"
branch_labels = None
depends_on = None

# 0034's released definition, restated: a migration does not import another revision.
SIGNATURE = "platform_signin_sp(p_sp_id text)"
RETURNS = "RETURNS TABLE (tenant_id varchar, provider_id varchar, kind varchar, enabled boolean, tiles boolean)"
BODY = (
    "SELECT p.tenant_id, p.id, p.kind, p.enabled, COALESCE(json_extract_path_text(p.config, 'tiles')::boolean, true) "
    "FROM public.signin_providers p WHERE p.sp_id = p_sp_id"
)
PINNED = "SET search_path = pg_catalog, public, pg_temp"


def _released_body() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    op.execute(
        f"CREATE OR REPLACE FUNCTION {SIGNATURE} {RETURNS} AS $$ {BODY} $$ "
        f"LANGUAGE sql STABLE SECURITY DEFINER {PINNED}"
    )


def upgrade() -> None:
    _released_body()


def downgrade() -> None:
    _released_body()
