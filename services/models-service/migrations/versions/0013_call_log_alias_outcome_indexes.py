"""call_log_alias_outcome_indexes: the call log's alias and outcome indexes on every database

The call list is searched and filtered on alias and outcome. models_0012 creates both indexes, but a database that
ran models_0012 before they were added to it has neither; this revision creates each one that is missing and leaves a
database that has them unchanged. The downgrade drops each one that is there. Plain SQL, so it renders offline.

Revision ID: models_0013
Revises: models_0012
"""

from __future__ import annotations

from alembic import op

revision = "models_0013"
down_revision = "models_0012"
branch_labels = None
depends_on = None

TABLE = "model_call_log"
INDEXES = {"ix_model_call_log_alias": "alias", "ix_model_call_log_outcome": "outcome"}


def create_if_missing(name: str, column: str) -> None:
    """SQLAlchemy renders `if_not_exists` as plain CREATE INDEX on SQL Server, so the guard is written out there."""
    if op.get_context().dialect.name == "mssql":
        op.execute(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{name}' AND object_id = OBJECT_ID('{TABLE}')) "
            f"CREATE INDEX {name} ON {TABLE} ({column})"
        )
    else:
        op.create_index(name, TABLE, [column], if_not_exists=True)


def upgrade() -> None:
    for name, column in INDEXES.items():
        create_if_missing(name, column)


def downgrade() -> None:
    for name in INDEXES:
        op.drop_index(name, table_name=TABLE, if_exists=True)
