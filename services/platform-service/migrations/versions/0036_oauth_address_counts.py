"""assistant registrations and sign-in starts are counted per caller address in the database

Open registration and the sign-in start come before anyone signs in, so their limits are per caller address. Held in
a process, the counts were lost on a restart and kept apart on each replica; one row per kind and address, with the
start of its one-minute window, counts them for the whole install, as `signin_email_failures` counts wrong passwords.
No tenant column and no row-level security: nobody is known yet.

Revision ID: 0036_oauth_address_counts
Revises: 0035_mcp_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_oauth_address_counts"
down_revision = "0035_mcp_sign_in"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "oauth_address_counts",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("address", sa.String(64), primary_key=True),
        sa.Column("hits", sa.Integer, nullable=False),
        sa.Column("window_start", sa.String(40), nullable=False),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_address_counts TO {TENANT}")


def downgrade() -> None:
    op.drop_table("oauth_address_counts")
