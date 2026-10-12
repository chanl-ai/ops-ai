"""drop the chat tables: chat is a facade over agent wrapper threads and the event log

Revision ID: 0017_drop_chat_tables
Revises: 0016_agent_registry

Conversations held in these tables are discarded, not copied: they have no graph checkpoint to resume from, and a
pending approval in them could not be decided. A downgrade recreates the tables empty.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op

revision = "0017_drop_chat_tables"
down_revision = "0016_agent_registry"
branch_labels = None
depends_on = None

# Children first: messages, tool calls, widgets and interrupts reference threads and each other.
CHAT_TABLES = ("interrupts", "tool_calls", "widgets", "messages", "threads")


def upgrade() -> None:
    for table in CHAT_TABLES:
        op.drop_table(table)


def downgrade() -> None:
    # The tables exactly as 0001 created them; no later migration changed them.
    path = Path(__file__).with_name("0001_chat_chat_tables.py")
    spec = importlib.util.spec_from_file_location("chat_tables_0001", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
