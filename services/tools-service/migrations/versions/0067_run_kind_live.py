"""gateway_calls.environment: a live run's calls read "live", not "production"

A call is made in a test run or a live one. The call log named a live run "production", the module environment live
runs call, so the word for a run differed between the call log, the API and the console. Rows of live runs are
renamed; test runs and calls that used no account are as they were.

Revision ID: tools_0067_run_kind_live
Revises: tools_0066_secret_ends
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0067_run_kind_live"
down_revision = "tools_0066_secret_ends"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE gateway_calls SET environment = 'live' WHERE environment = 'production'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE gateway_calls SET environment = 'production' WHERE environment = 'live'"))
