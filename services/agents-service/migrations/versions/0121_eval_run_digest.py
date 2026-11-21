"""Each kept eval run records the digest of the content it ran on, and its trigger is indexed

Revision ID: 0121_eval_run_digest
Revises: 0120_skill_step_tools

A draft is rewritten in place under one version number, so a run of "version 1" says nothing about the version 1 a
publish asks for once the draft was saved again. eval_runs gains `digest`, the version's content digest when the run
started (store/agent_registry.py digest_of), and the publish gate counts a run only while it equals the version's own
digest. The run row holds no JSON object a digest could live in (`results` is the list of case results, read whole),
so it is a column. Nullable: runs kept before carry none and count as not run, so their versions need one new run.

An agent's runs list filters and counts by `trigger` (manual, cli), so the column gets `ix_eval_runs_trigger` behind
the tenant and team columns. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0121_eval_run_digest"
down_revision = "0120_skill_step_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("eval_runs") as b:
        b.add_column(sa.Column("digest", sa.String(64)))
    op.create_index("ix_eval_runs_trigger", "eval_runs", ["tenant_id", "team_id", "trigger"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_trigger", table_name="eval_runs")
    with op.batch_alter_table("eval_runs") as b:
        b.drop_column("digest")
