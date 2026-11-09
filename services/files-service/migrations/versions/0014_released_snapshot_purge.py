"""The retention process finds released knowledge snapshots past their date in every tenant

A knowledge snapshot's 30 days count from when its source lets it go; once they pass, the files_retention process
deletes it unless a legal hold keeps it. That process lists the due files across tenants as ops_files_system, granted
that read here, then deletes each as its own tenant and team. Runs on PostgreSQL and SQL Server (on SQL Server the
system user is not bound by row security, so nothing is granted).

Revision ID: files_0014
Revises: files_0013
"""

from __future__ import annotations

from alembic import op

revision = "files_0014"
down_revision = "files_0013"
branch_labels = None
depends_on = None

SYSTEM_ROLE = "ops_files_system"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT ON files TO {SYSTEM_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT ON files FROM {SYSTEM_ROLE}")
