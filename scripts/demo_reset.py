"""Clears what demos and use cases left on the stack (`make demo-reset`): every workflow run, agent thread and chat,
Human Task, case and received-email record, so the console opens on the seeded agents, workflows and tools only.

Definitions, agents, tools and their modules, knowledge, files, people, memories and the audit and usage records are
kept. `make demo-reset` then brings the bank module and the demo knowledge back up to date, which `make up` does not,
and prints the open Human Tasks Maya sees: 0 when the reset worked.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_mailbox

# Parents after children. Leases are left alone: the mailbox poll lease is one, and the sweeper clears the rest.
CLEARED = (
    "engine_work",
    "engine_steps",
    "engine_runs",
    "review_approvals",
    "review_decisions",
    "timers",
    "case_events",
    "cases",
    "trigger_events",
    "ops_checkpoint_writes",
    "ops_checkpoint_fences",
    "ops_checkpoints",
    "chat_search",
    "chat_attachments",
    "thread_budgets",
    "thread_events",
    "graph_runs",
    "graph_threads",
)


async def clear(url: str) -> dict[str, int]:
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        present = {
            r["tablename"] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
        removed: dict[str, int] = {}
        async with conn.transaction():
            for table in (t for t in CLEARED if t in present):
                removed[table] = int((await conn.execute(f"DELETE FROM {table}")).split()[-1])
        return removed
    finally:
        await conn.close()


def open_tasks() -> int:
    maya = demo_mailbox.sign_in(demo_mailbox.MAYA)
    listed = demo_mailbox.data(
        demo_mailbox.httpx.get(f"{demo_mailbox.AGENTS}/reviews", params={"pageSize": 1}, headers=maya, timeout=30)
    )
    return int(listed["pagination"]["total"])


def main() -> int:
    """`demo_reset.py` clears; `demo_reset.py --check` counts what is left, after the bank and knowledge are reseeded
    (the bank's reimport opens a review and approves it)."""
    if "--check" not in sys.argv:
        url = os.environ.get("OPS_DATABASE_URL", "")
        if not url:
            print("demo-reset: OPS_DATABASE_URL is not set; run it through make", file=sys.stderr)
            return 1
        removed = asyncio.run(clear(url))
        print("cleared: " + (", ".join(f"{t} {n}" for t, n in removed.items() if n) or "nothing was there"))
        return 0
    left = open_tasks()
    print(f"open Human Tasks: {left}")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
