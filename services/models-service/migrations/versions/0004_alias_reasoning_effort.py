"""an alias version carries the reasoning effort its calls run at (chat latency, 2026-10-18)

Revision ID: models_0004

A reasoning model at its default effort spent 1,000 to 4,500 tokens thinking before the first word of a chat
answer (10 to 24 s on shared). The alias version names the effort; a request that sets its own keeps it. Existing
versions get null, which sends nothing and leaves the provider's default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0004"
down_revision = "models_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_aliases", sa.Column("reasoning_effort", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("model_aliases", "reasoning_effort")
