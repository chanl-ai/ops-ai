"""One provider subject per person, and the flow columns that link a person from their session or invite

A first sign-in linked a new provider subject to whichever person had the email, so one person could collect several
subjects at the same provider, each a way into their account. `uq_signin_identities_person` allows one subject per
person per provider. Where a person already holds more than one, the oldest link is kept (earliest `created_at`, then
the lowest id) and the later ones are deleted: a subject attached by email after the person's own is the one this
rule exists to remove. The person whose later subject goes signs in with the kept one, or links again from their
session after an admin removes the kept one.

`signin_flows.subject` keeps a link flow's provider subject until the session that started it completes the link;
`signin_flows.invite_hash` names the invite a sign-in started from. The downgrade drops all three.

Revision ID: 20261123_2330_identity_per_user
Revises: 20261122_2022_list_sort_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261123_2330_identity_per_user"
down_revision = "20261122_2022_list_sort_indexes"
branch_labels = None
depends_on = None

# Every link with an older link for the same person at the same provider; the same statement on both dialects.
LATER_LINKS = (
    "DELETE FROM signin_identities WHERE id IN ("
    " SELECT s.id FROM signin_identities s WHERE EXISTS ("
    "  SELECT 1 FROM signin_identities o"
    "  WHERE o.tenant_id = s.tenant_id AND o.provider_id = s.provider_id AND o.user_id = s.user_id"
    "  AND (o.created_at < s.created_at OR (o.created_at = s.created_at AND o.id < s.id))))"
)


def upgrade() -> None:
    op.execute(LATER_LINKS)
    op.create_unique_constraint(
        "uq_signin_identities_person", "signin_identities", ["tenant_id", "provider_id", "user_id"]
    )
    op.add_column("signin_flows", sa.Column("subject", sa.String(255), nullable=True))
    op.add_column("signin_flows", sa.Column("invite_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("signin_flows", "invite_hash")
    op.drop_column("signin_flows", "subject")
    op.drop_constraint("uq_signin_identities_person", "signin_identities", type_="unique")
