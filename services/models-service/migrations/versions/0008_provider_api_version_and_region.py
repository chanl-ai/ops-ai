"""a provider connection names its api-version and region, and records the region its provider answered from

Revision ID: models_0008
Revises: models_0007

Azure OpenAI connections carry the API version their path is built with and the region the resource runs in; the region
the provider last answered from (`x-ms-region`) is kept beside it so a mismatch is visible. All three are empty for the
other connection types, so existing rows need no value.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0008"
down_revision = "models_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_connections", sa.Column("api_version", sa.String(32)))
    op.add_column("provider_connections", sa.Column("region", sa.String(64)))
    op.add_column("provider_connections", sa.Column("observed_region", sa.String(64)))
