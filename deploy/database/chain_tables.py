"""Prints, as JSON, the tables one service's code declares as its own: the target metadata its migrations' env.py
hands Alembic, filtered by that env's include_name. Run from the service's folder with the service's environment
(schema.py does): a service may use a table another chain created (tools-service writes gateway_calls, which the
agents chain makes on a fresh database), and its runtime role needs DML on every table its code reads and writes."""

from __future__ import annotations

import contextlib
import json
from typing import Any

from alembic import context
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData


class _Captured(Exception):
    pass


def main() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    seen: dict[str, Any] = {}

    def capture(**kwargs: Any) -> None:
        seen.update(kwargs)
        raise _Captured

    def no_steps(_rev: Any, _ctx: Any) -> list[Any]:
        return []

    with EnvironmentContext(config, script, fn=no_steps, as_sql=True):
        context.configure = capture  # pyright: ignore[reportAttributeAccessIssue]
        with contextlib.suppress(_Captured):
            script.run_env()
    metadata: Any = seen.get("target_metadata")
    keep: Any = seen.get("include_name")
    found: list[MetaData] = []
    if isinstance(metadata, MetaData):
        found = [metadata]
    elif metadata is not None:
        found = [m for m in metadata if isinstance(m, MetaData)]
    tables: set[str] = set()
    for md in found:
        tables |= {str(t.name) for t in md.tables.values() if keep is None or keep(t.name, "table", {})}
    print(json.dumps(sorted(tables)))


if __name__ == "__main__":
    main()
