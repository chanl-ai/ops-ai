"""tools_0074 keeps every write that was set to wait waiting, by failure mode: a stored requires_approval=true write
runs unasked once the gateway stops reading that flag; a write with an answer of its own loses it; a read, an unset
write or a write stored false is made to wait."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

BEFORE = "tools_0073_tool_approval_mode"
AFTER = "tools_0074_stored_waits_answers"
T = "t_apr"


async def test_tools_0074_turns_stored_waits_into_reviewer_answers() -> None:
    async with scratch_database("tools_stored_approvals") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            at = datetime.now(UTC)
            async with engine.begin() as c:
                await c.execute(
                    sa.text(
                        "insert into tool_modules (tenant_id, id, team_id, name, display_name, system, description, "
                        "status, owner_team, owner_contacts, auth, timeout_ms, data_classification, reachable, drift, "
                        "version, pending, revision, created_at, updated_at) values (:t, 'm1', 'team_a', 'm', 'm', "
                        "'s', 'd', 'live', 'o', cast('[]' as json), cast('{}' as json), 1000, 'internal', true, "
                        "false, '1', cast('{}' as json), 1, :at, :at)"
                    ),
                    {"t": T, "at": at},
                )
                # name, access, requires_approval, approval_mode
                rows = [
                    ("waits", "write", True, None),
                    ("own_answer", "write", True, "none"),
                    ("not_set", "write", None, None),
                    ("runs", "write", False, None),
                    ("read", "read", True, None),
                ]
                for pos, (name, access, stored, mode) in enumerate(rows):
                    await c.execute(
                        sa.text(
                            "insert into module_operations (tenant_id, id, module_id, position, name, tool_id, "
                            "description, access, enabled, input, masked_output, rate_limit_per_min, "
                            "requires_approval, approval_mode) values (:t, :n, 'm1', :p, :n, :n, 'd', :a, true, "
                            "cast('[]' as json), cast('[]' as json), 60, :r, :m)"
                        ),
                        {"t": T, "n": name, "p": pos, "a": access, "r": stored, "m": mode},
                    )
            _alembic(target, "upgrade", AFTER)
            async with engine.connect() as c:
                got: dict[str, Any] = {
                    r["name"]: r["approval_mode"]
                    for r in (await c.execute(sa.text("select name, approval_mode from module_operations"))).mappings()
                }
            assert got == {
                "waits": "reviewer",
                "own_answer": "none",
                "not_set": None,
                "runs": None,
                "read": None,
            }, got
        finally:
            await engine.dispose()
