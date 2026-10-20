"""Dev seed of v2 workflows: `engine_workflows.json` beside the agents seed (the demo's seed/ holds the customer
summary workflow c-062 uses; test fixtures hold none). Each definition is checked against the type registry and
stored live for the dev tenant; one already stored under its digest is left as it is. An item's `teamId` names the
team that owns it (a workflow an Email received trigger binds must have one, as the levy intake does); without one it
is stored under no team, so every team sees it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_engine import default_registry
from ops_engine.definition import parse, validate
from ops_engine.store import DefinitionStore
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger

from ..store.engine import DatabaseError, EngineTransactions
from ..store.tenancy import LOCAL_TENANT, tenant_scope
from .deps import Runtime

log = get_logger("ops_agents.api.engine_seed")


def seed_path(seed_dir: Path, agents_seed_file: Path | None) -> Path:
    return (agents_seed_file.parent if agents_seed_file else seed_dir) / "engine_workflows.json"


async def load_seed(rt: Runtime, path: Path) -> None:
    if not path.is_file():
        return
    store = DefinitionStore(EngineTransactions(rt.db))
    raw: list[dict[str, Any]] = json.loads(path.read_text())
    for item in raw:
        team = cast(str | None, item.get("teamId"))
        d = parse({k: v for k, v in item.items() if k != "teamId"})
        if checks := validate(d, default_registry()):
            raise ValueError(f"Seed workflow {d.id} does not pass its checks: {checks}")
        with tenant_scope(LOCAL_TENANT):
            try:
                version, created = await store.publish(
                    d.id,
                    name=d.name or d.id,
                    definition=d.wire(),
                    digest=d.digest(),
                    now=now_iso(),
                    by="seed",
                    team=team,
                )
                # A shipped seed is live, as a v1 seed is published by "seed"; a restart never takes back a version a
                # person approved since, so an unchanged seed goes live only when nothing serves the workflow.
                if created or await store.current(d.id) is None:
                    await store.go_live(d.id, version)
            except DatabaseError as e:  # a database not yet migrated to the runner's tables seeds v1 alone
                log.warning("engine_seed_skipped", workflow=d.id, error=type(e).__name__)
                return
