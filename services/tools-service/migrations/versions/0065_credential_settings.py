"""app_credentials.settings: the settings of the app registration a credential is, beside its client id and secret

An app credential held only a client id, permissions and a secret, so what else the registration fixes (a Microsoft
tenant, an Okta domain, a custom app's sign-in and token addresses, its signing certificate) was kept on each account
and had to be typed again on every one. The credential now holds them, and every account signing in with it reads
them from there. Null for a credential that holds none.

Revision ID: tools_0065_credential_settings
Revises: tools_0064_team_credentials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0065_credential_settings"
down_revision = "tools_0064_team_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("app_credentials") as b:
        b.add_column(sa.Column("settings", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("app_credentials") as b:
        b.drop_column("settings")
