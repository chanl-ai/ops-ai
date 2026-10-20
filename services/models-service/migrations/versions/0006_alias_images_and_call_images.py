"""an alias version is cleared for page images, and each call records how many it carried (c-295)

Revision ID: models_0006
Revises: models_0005

A page image sent to a model carries everything printed on the page, so an alias receives one only when its version
says so; existing versions are not cleared. The call log counts each call's images so every image sent is on record.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0006"
down_revision = "models_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_aliases", sa.Column("images", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("model_call_log", sa.Column("images", sa.Integer, nullable=False, server_default="0"))
