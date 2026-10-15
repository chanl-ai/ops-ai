"""access is read or write only: a CHECK on module_operations.access

Revision ID: tools_0012_access_rw
Revises: tools_0011_approval_policy

No row is rewritten. Moving the chain head makes `make up` rebuild a database built before Read and Write only (its
money_movement rows go with it, and the dev seed refills it); `KEEP_DATA=1` migrates in place and fails here on such a
row, loudly, rather than keep one the code refuses to read.
"""

from __future__ import annotations

from alembic import op

revision = "tools_0012_access_rw"
down_revision = "tools_0011_approval_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint("ck_module_operations_access", "module_operations", "access IN ('read', 'write')")


def downgrade() -> None:
    # Kept so the chain's revert-and-reapply test (tests/test_registry_store.py) still runs end to end.
    op.drop_constraint("ck_module_operations_access", "module_operations", type_="check")
