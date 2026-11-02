"""plugin_binding_versions: each team's binding records the plugin version it runs (c-609)

A plugin's tools were written once per account and never followed an upgrade, and nothing said which version a team
ran. The binding now keeps the version the team took, the digest of its tool declarations and the declarations, which
each call is built from until the team takes a newer one. Null until a team takes a version.

Revision ID: tools_0049_binding_versions
Revises: tools_0048_body_encoding
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0049_binding_versions"
down_revision = "tools_0048_body_encoding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugin_bindings", sa.Column("version", sa.String(40)))
    op.add_column("plugin_bindings", sa.Column("digest", sa.String(64)))
    op.add_column("plugin_bindings", sa.Column("declarations", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("plugin_bindings") as b:
        b.drop_column("declarations")
        b.drop_column("digest")
        b.drop_column("version")
