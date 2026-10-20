"""name on registry_widgets: the newest version's name, so the Widgets list searches and pages in the query

Revision ID: 0036_widget_name
Revises: 0035_widget_deployments

The name lived only in each version's content JSON, so a page of widgets could be cut only after loading every row
(c-107). Filled from each widget's newest version.
"""

from __future__ import annotations

import json
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

revision = "0036_widget_name"
down_revision = "0035_widget_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registry_widgets") as b:
        b.add_column(sa.Column("name", sa.String(200), nullable=False, server_default=""))
    rows = op.get_bind().execute(
        sa.text(
            "SELECT w.id, v.content FROM registry_widgets w JOIN registry_widget_versions v"
            " ON v.widget_id = w.id AND v.version = w.version"
        )
    )
    for widget_id, content in rows.all():
        parsed = cast(dict[str, Any], content if isinstance(content, dict) else json.loads(str(content)))
        name = str(parsed.get("name", ""))
        op.execute(sa.text("UPDATE registry_widgets SET name = :n WHERE id = :i").bindparams(n=name, i=widget_id))


def downgrade() -> None:
    with op.batch_alter_table("registry_widgets") as b:
        b.drop_column("name")
