"""A custom module with no connection gets one that needs no sign-in and holds its address (c-616 D3b-2a)

A custom app's address lives on its connection, which a call reads per environment; a module made from a full URL kept
its address only on itself. Each team's http, openapi and MCP module with no connection gets one: auth kind none, its
id `con_` and the module's id, the module's endpoint as the base address in test and production. A plugin's module
signs in through the team's binding, and a built-in app's module (its provisioned copy, or one under the app's older
module name) is the platform's: both are left alone. Plain SQL both ways, so the upgrade bundle renders it offline.

Revision ID: tools_0056_module_connections
Revises: tools_0055_secret_isolation
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "tools_0056_module_connections"
down_revision = "tools_0055_secret_isolation"
branch_labels = None
depends_on = None

MADE_BY = "module address"
ENVIRONMENTS = ("test", "production")
# The older module names of the built-in apps (ops_tools.modules.seed.BUILT_IN), as they were when this ran.
BUILT_IN_NAMES = ("knowledge-search", "platform-tools")

modules = sa.table(
    "tool_modules",
    sa.column("tenant_id", sa.String),
    sa.column("id", sa.String),
    sa.column("team_id", sa.String),
    sa.column("name", sa.String),
    sa.column("display_name", sa.String),
    sa.column("template_id", sa.String),
    sa.column("type", sa.String),
    sa.column("endpoint", sa.String),
    sa.column("connection_id", sa.String),
)
connections = sa.table(
    "connections",
    sa.column("tenant_id", sa.String),
    sa.column("id", sa.String),
    sa.column("team_id", sa.String),
    sa.column("name", sa.String),
    sa.column("auth_kind", sa.String),
    sa.column("status", sa.String),
    sa.column("sign_in", sa.String),
    sa.column("team_backup", sa.Boolean),
    sa.column("revision", sa.Integer),
    sa.column("created_by", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_by", sa.String),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
environments = sa.table(
    "connection_environments",
    sa.column("tenant_id", sa.String),
    sa.column("connection_id", sa.String),
    sa.column("environment", sa.String),
    sa.column("team_id", sa.String),
    sa.column("settings", sa.JSON),
    sa.column("secrets", sa.JSON),
    sa.column("updated_by", sa.String),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _made_id() -> Any:
    return sa.func.concat("con_", modules.c.id)


def _custom() -> Any:
    return sa.and_(
        modules.c.connection_id.is_(None),
        modules.c.team_id.is_not(None),
        modules.c.type.in_(("http", "openapi", "mcp")),
        modules.c.name.not_in(BUILT_IN_NAMES),
        sa.or_(
            modules.c.template_id.is_(None),
            sa.and_(sa.not_(modules.c.template_id.like("builtin:%")), sa.not_(modules.c.template_id.like("plugin:%"))),
        ),
    )


def upgrade() -> None:
    now = sa.func.current_timestamp()
    made = sa.select(
        modules.c.tenant_id, _made_id(), modules.c.team_id, modules.c.display_name, sa.literal("none"),
        sa.literal("healthy"), sa.literal("team"), sa.false(), sa.literal(1), sa.literal(MADE_BY), now,
        sa.literal(MADE_BY), now,
    ).where(_custom())  # fmt: skip
    columns = [
        "tenant_id", "id", "team_id", "name", "auth_kind", "status", "sign_in", "team_backup", "revision",
        "created_by", "created_at", "updated_by", "updated_at",
    ]  # fmt: skip
    op.execute(connections.insert().from_select(columns, made))
    # Endpoints are https addresses, so the JSON is built by concatenation, which both dialects render the same way.
    settings = sa.cast(sa.func.concat('{"baseUrl": "', modules.c.endpoint, '"}'), sa.JSON)
    for name in ENVIRONMENTS:
        rows = sa.select(
            modules.c.tenant_id, _made_id(), sa.literal(name), modules.c.team_id, settings,
            sa.cast(sa.literal("{}"), sa.JSON), sa.literal(MADE_BY), now,
        ).where(_custom(), modules.c.endpoint != "")  # fmt: skip
        env_columns = [
            "tenant_id", "connection_id", "environment", "team_id", "settings", "secrets", "updated_by", "updated_at",
        ]  # fmt: skip
        op.execute(environments.insert().from_select(env_columns, rows))
    op.execute(modules.update().where(_custom()).values(connection_id=_made_id()))


def downgrade() -> None:
    made = sa.select(connections.c.id).where(
        connections.c.tenant_id == modules.c.tenant_id,
        connections.c.id == modules.c.connection_id,
        connections.c.created_by == MADE_BY,
    )
    op.execute(modules.update().where(made.exists()).values(connection_id=None))
    of_made = sa.select(connections.c.id).where(
        connections.c.tenant_id == environments.c.tenant_id,
        connections.c.id == environments.c.connection_id,
        connections.c.created_by == MADE_BY,
    )
    op.execute(environments.delete().where(of_made.exists()))
    op.execute(connections.delete().where(connections.c.created_by == MADE_BY))
