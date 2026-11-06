"""config_setting_modes: an auth config's sign-in values are a default or fixed, and Ops AI's app holds them per team

An auth config's `asked: config` value (Salesforce's sign-in address) was always the one every account used. A config
may now offer it as a default that Connect pre-selects and a person may change, or fix it. Each setting's mode is kept
beside the values; a value with no mode is fixed, as before. Ops AI's own app had nowhere to keep a team's values, so
the team's binding of the plugin holds them.

Revision ID: tools_0070_config_setting_modes
Revises: tools_0069_token_person_name
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0070_config_setting_modes"
down_revision = "tools_0069_token_person_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_credentials", sa.Column("setting_modes", sa.JSON))
    op.add_column("plugin_bindings", sa.Column("config_settings", sa.JSON))
    op.add_column("plugin_bindings", sa.Column("setting_modes", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("plugin_bindings") as b:
        b.drop_column("setting_modes")
        b.drop_column("config_settings")
    with op.batch_alter_table("app_credentials") as b:
        b.drop_column("setting_modes")
