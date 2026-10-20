"""layouts cached per file digest, and measured tokens on extractions (c-247)

`documents_layouts` keeps one layout per tenant, content digest, layout engine version and OCR choice, so every step
reads one parse of the bytes. Extractions record the document type read with and the model's input and output tokens,
so a test estimate prices what reading a type spends.

Revision ID: documents_0002
Revises: documents_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0002"
down_revision = "documents_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents_layouts",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("file_digest", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("ocr", sa.Boolean(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "file_digest", "engine", "ocr"),
    )
    op.add_column("extractions", sa.Column("type_id", sa.String(length=64), nullable=True))
    op.add_column("extractions", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("extractions", sa.Column("output_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass
