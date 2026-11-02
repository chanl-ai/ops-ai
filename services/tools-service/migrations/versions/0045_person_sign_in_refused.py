"""person_sign_in_refused: a person's own key or sign-in the system refused is kept and marked (c-595)

A person's key the system answered 401 to was sent again on every call, and a person's sign-in whose refresh the system
refused was deleted, so Your connections could not say it had expired. connection_tokens now records when the system
refused the row and what it said; the person's next call asks for a new key or sign-in, and a new one clears both.

Revision ID: tools_0045_person_refused
Revises: tools_0044_sign_in_isolation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0045_person_refused"
down_revision = "tools_0044_sign_in_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connection_tokens", sa.Column("refused_at", sa.DateTime(timezone=True)))
    op.add_column("connection_tokens", sa.Column("refused_reason", sa.String(300)))


def downgrade() -> None:
    op.drop_column("connection_tokens", "refused_reason")
    op.drop_column("connection_tokens", "refused_at")
