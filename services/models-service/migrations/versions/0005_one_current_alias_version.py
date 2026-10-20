"""one version of an alias is current (shared, 2026-10-18)

Revision ID: models_0005
Revises: models_0004

Adding a version left the earlier ones current, so shared's chat alias had seven current versions and which served
was decided by the query's order. Every alias keeps its highest current version; the rest are retired, and a unique
partial index keeps it to one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0005"
down_revision = "models_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE model_aliases AS a SET status = 'retired'
        WHERE a.status = 'current' AND a.version < (
            SELECT max(b.version) FROM model_aliases b WHERE b.name = a.name AND b.status = 'current'
        )
        """
    )
    op.create_index(
        "ux_model_aliases_current",
        "model_aliases",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
    )


def downgrade() -> None:
    op.drop_index("ux_model_aliases_current", table_name="model_aliases")
