"""A module's address lives on its connection only; tool_modules.endpoint and type go (c-616 D3c)

Calls already read a custom app's address from its connection per environment. Each connected module's endpoint is
copied to its connection first: into every environment row that names no base address, and, for a connection with no
environment yet (the demo's integrations), into a test row holding only that address. A connection whose modules name
two different addresses could not hold both, so the upgrade stops on one and names it. A module's type is read from its
tools now. The downgrade puts both columns back: the endpoint from the connection (production first), the type from the
tools. SQL per dialect, rendered offline for the upgrade bundle.

Revision ID: tools_0058_module_address
Revises: tools_0057_connection_isolation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0058_module_address"
down_revision = "tools_0057_connection_isolation"
branch_labels = None
depends_on = None

FILLED_BY = "module address on connection"

# Connected modules with an address, one row per connection and address.
ADDRESSED = """
    SELECT DISTINCT m.tenant_id, m.connection_id, m.team_id, m.endpoint FROM tool_modules m
    WHERE m.connection_id IS NOT NULL AND m.endpoint <> ''
"""
REFUSED = "tools_0058: a connection is used by modules with different addresses; give each its own connection"
TWO_ADDRESSES = """
    SELECT connection_id FROM tool_modules WHERE connection_id IS NOT NULL AND endpoint <> ''
    GROUP BY tenant_id, connection_id HAVING COUNT(DISTINCT endpoint) > 1
"""
NO_ENVIRONMENT = """
    NOT EXISTS (SELECT 1 FROM connection_environments e
                WHERE e.tenant_id = a.tenant_id AND e.connection_id = a.connection_id)
"""


def _postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _postgres():
        op.execute(f"DO $$ BEGIN IF EXISTS ({TWO_ADDRESSES}) THEN RAISE EXCEPTION '{REFUSED}'; END IF; END $$")
        # The address is added to the object's text: merging JSON objects needs jsonb, which SQL Server has no form
        # of (scripts/check_portable_store.py).
        op.execute(f"""
            UPDATE connection_environments e
            SET settings = CAST(CONCAT(
                LEFT(RTRIM(CAST(e.settings AS text)), LENGTH(RTRIM(CAST(e.settings AS text))) - 1),
                CASE WHEN REPLACE(CAST(e.settings AS text), ' ', '') = '{{}}' THEN '' ELSE ', ' END,
                '"baseUrl": ', CAST(to_json(a.endpoint) AS text), '}}'
            ) AS json)
            FROM ({ADDRESSED}) a
            WHERE e.tenant_id = a.tenant_id AND e.connection_id = a.connection_id
              AND COALESCE(json_extract_path_text(e.settings, 'baseUrl'), '') = ''
        """)
        now = "CURRENT_TIMESTAMP"
        settings = "CAST(CONCAT('{\"baseUrl\": \"', a.endpoint, '\"}') AS json)"
        empty = "CAST('{}' AS json)"
    else:
        op.execute(f"IF EXISTS ({TWO_ADDRESSES}) BEGIN; THROW 50000, '{REFUSED}', 1; END")
        op.execute(f"""
            UPDATE e SET settings = JSON_MODIFY(e.settings, '$.baseUrl', a.endpoint)
            FROM connection_environments e JOIN ({ADDRESSED}) a
              ON e.tenant_id = a.tenant_id AND e.connection_id = a.connection_id
            WHERE COALESCE(JSON_VALUE(e.settings, '$.baseUrl'), '') = ''
        """)
        now = "SYSDATETIMEOFFSET()"
        settings = "CONCAT('{\"baseUrl\": \"', a.endpoint, '\"}')"
        empty = "'{}'"
    # Endpoints are https addresses, so concatenation builds the JSON the same way in both dialects.
    op.execute(f"""
        INSERT INTO connection_environments
            (tenant_id, connection_id, environment, team_id, settings, secrets, updated_by, updated_at)
        SELECT a.tenant_id, a.connection_id, 'test', a.team_id, {settings}, {empty}, '{FILLED_BY}', {now}
        FROM ({ADDRESSED}) a WHERE {NO_ENVIRONMENT}
    """)
    with op.batch_alter_table("tool_modules") as b:
        b.drop_column("endpoint")
        b.drop_column("type")


def downgrade() -> None:
    with op.batch_alter_table("tool_modules") as b:
        b.add_column(sa.Column("endpoint", sa.Text))
        b.add_column(sa.Column("type", sa.String(16)))
    base = "json_extract_path_text(e.settings, 'baseUrl')" if _postgres() else "JSON_VALUE(e.settings, '$.baseUrl')"

    def of(env: str) -> str:
        return f"""(SELECT {base} FROM connection_environments e WHERE e.tenant_id = tool_modules.tenant_id
                    AND e.connection_id = tool_modules.connection_id AND e.environment = '{env}')"""

    op.execute(f"UPDATE tool_modules SET endpoint = COALESCE({of('production')}, {of('test')}, '')")
    ops = (
        "SELECT 1 FROM module_operations o WHERE o.tenant_id = tool_modules.tenant_id AND o.module_id = tool_modules.id"
    )
    op.execute(f"""
        UPDATE tool_modules SET type = CASE
            WHEN EXISTS ({ops} AND o.executor = 'mcp') THEN 'mcp'
            WHEN EXISTS ({ops} AND o.executor IN ('code', 'local')) AND NOT EXISTS ({ops} AND o.executor = 'http')
                THEN 'code'
            ELSE 'http' END
    """)
    op.execute(f"DELETE FROM connection_environments WHERE updated_by = '{FILLED_BY}'")
    with op.batch_alter_table("tool_modules") as b:
        b.alter_column("endpoint", existing_type=sa.Text, nullable=False)
        b.alter_column("type", existing_type=sa.String(16), nullable=False)
