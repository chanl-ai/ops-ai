"""document types, versions, samples and test runs (c-236): moved to documents-service (c-256)

These tables were created here before documents-service had its own chain; documents_0001 creates them now. The
revision stays so a database already past it keeps its history, and creates nothing, so the two chains never claim
the same table names whichever runs first on a database (pre-launch: nothing is kept).

Revision ID: files_0005
Revises: files_0004
"""

from __future__ import annotations

revision = "files_0005"
down_revision = "files_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
