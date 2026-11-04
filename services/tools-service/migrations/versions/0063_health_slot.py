"""An account's stored health without the environment it was tested in

Health moved onto the account from its Production slot with that slot's name inside it ("environment": "production").
An account has no environment, so the app page's model refuses the key and the page answers 500. The key is dropped;
nothing reads it.

Revision ID: tools_0063_health_slot
Revises: tools_0062_accounts
"""

from __future__ import annotations

from alembic import op

revision = "tools_0063_health_slot"
down_revision = "tools_0062_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        # Once FORCE is on, row-level security would hide rows from the migrating role.
        op.execute("SET LOCAL row_security = off")
        op.execute(
            "UPDATE connections SET health = (health::jsonb - 'environment')::json "
            "WHERE health IS NOT NULL AND health::jsonb ? 'environment'"
        )
    else:
        op.execute(
            "UPDATE connections SET health = JSON_MODIFY(health, '$.environment', NULL) "
            "WHERE health IS NOT NULL AND JSON_VALUE(health, '$.environment') IS NOT NULL"
        )


def downgrade() -> None:
    # Before this revision every stored health named the Production slot it came from.
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
        op.execute(
            'UPDATE connections SET health = (health::jsonb || \'{"environment": "production"}\')::json '
            "WHERE health IS NOT NULL AND NOT health::jsonb ? 'environment'"
        )
    else:
        op.execute(
            "UPDATE connections SET health = JSON_MODIFY(health, '$.environment', 'production') "
            "WHERE health IS NOT NULL AND JSON_VALUE(health, '$.environment') IS NULL"
        )
