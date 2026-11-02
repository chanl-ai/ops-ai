"""environment_app_and_plugin_settings: the app an environment signs in with, and a plugin's settings per environment,
as columns of the connection's environment (c-580)

The platform's app was a `platformApp` key inside an environment's settings JSON, so a save that rewrote the settings
from the fields a person sees (Edit keys) dropped it and the sign-in lost its client secret. A plugin's per-environment
settings (a sandbox's sign-in address, the instance a token named) were a second copy on the team's binding beside the
connection's addresses. Both move onto the environment's row, the existing values with them, as plain SQL so the
revision renders offline for a SQL Server bundle.

Revision ID: tools_0046_env_app_settings
Revises: tools_0045_person_refused
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0046_env_app_settings"
down_revision = "tools_0045_person_refused"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connection_environments", sa.Column("platform_app", sa.String(120)))
    op.add_column("connection_environments", sa.Column("plugin_settings", sa.JSON()))
    if op.get_context().dialect.name == "mssql":
        op.execute(
            "UPDATE connection_environments SET platform_app = JSON_VALUE(settings, '$.platformApp'), "
            "settings = JSON_MODIFY(settings, '$.platformApp', NULL) "
            "WHERE JSON_VALUE(settings, '$.platformApp') IS NOT NULL"
        )
        op.execute(
            "UPDATE ce SET plugin_settings = JSON_QUERY(b.settings, CONCAT('$.environments.', ce.environment)) "
            "FROM connection_environments ce JOIN plugin_bindings b "
            "ON b.tenant_id = ce.tenant_id AND b.connection_id = ce.connection_id "
            "WHERE JSON_QUERY(b.settings, CONCAT('$.environments.', ce.environment)) IS NOT NULL"
        )
        op.execute(
            "UPDATE plugin_bindings SET settings = JSON_MODIFY(settings, '$.environments', NULL) "
            "WHERE JSON_QUERY(settings, '$.environments') IS NOT NULL"
        )
        return
    op.execute(
        "UPDATE connection_environments SET platform_app = json_extract_path_text(settings, 'platformApp'), "
        "settings = (settings::jsonb - 'platformApp')::json "
        "WHERE json_extract_path_text(settings, 'platformApp') IS NOT NULL"
    )
    op.execute(
        "UPDATE connection_environments ce SET plugin_settings = b.settings->'environments'->ce.environment "
        "FROM plugin_bindings b WHERE b.tenant_id = ce.tenant_id AND b.connection_id = ce.connection_id "
        "AND b.settings->'environments'->ce.environment IS NOT NULL"
    )
    op.execute(
        "UPDATE plugin_bindings SET settings = (settings::jsonb - 'environments')::json "
        "WHERE settings->'environments' IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("connection_environments", "plugin_settings")
    op.drop_column("connection_environments", "platform_app")
