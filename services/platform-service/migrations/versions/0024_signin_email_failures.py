"""wrong passwords are counted per email, known or not, so sign-in answers every address the same

Sign-in names no tenant, so an address that matches nobody had no row to count against: it answered 401 forever
while a known address locked with 429 after five, which told an attacker which emails have accounts (c-196). One row
per email address, kept as a SHA-256 of the lowercased address, counts every wrong password at sign-in; the
per-person count in 0019 stays for step-up. No tenant column and no row-level security: the address is all sign-in
has, and the hash keeps the address itself out of the table.

Revision ID: 0024_signin_email_failures
Revises: 0023_documents_cells
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_signin_email_failures"
down_revision = "0023_documents_cells"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "signin_email_failures",
        sa.Column("email_hash", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("first_failed_at", sa.String(40), nullable=False),
        sa.Column("locked_until", sa.String(40)),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON signin_email_failures TO {TENANT}")


def downgrade() -> None:
    op.drop_table("signin_email_failures")
