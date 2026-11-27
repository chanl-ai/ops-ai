"""Migration 0113 copies each agent's skill pins out of its versions, by failure mode: the down path dropped pins that
the way back up could not bring back."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]


def test_skill_pins_dropped_by_the_down_path_come_back_from_the_newest_version(emptied_database: str) -> None:
    """agent_skill_pins copies the newest version's spec.skillPins: down past 0113 and up again, every row is back."""
    cfg = Config(str(ROOT / "alembic.ini"))
    at, tenant = now_iso(), new_id("ten")
    old = '{"skillPins": [{"skillId": "skl_gone", "version": 1}]}'
    new = '{"skillPins": [{"skillId": "skl_a", "version": 3}, {"skillId": "skl_b", "version": 1}, "bad"]}'
    version = (
        "INSERT INTO registry_agent_versions (tenant_id, agent_id, version, spec, digest, note, changes, saved_at, "
        "saved_by) VALUES (:t, 'agt_pins', :v, CAST(:s AS json), :d, '', CAST('[]' AS json), :at, 'p')"
    )
    pins = "SELECT agent_id, skill_id, version, team_id FROM agent_skill_pins ORDER BY skill_id"
    asyncio.run(
        _sql(
            emptied_database,
            (
                "INSERT INTO registry_agents (tenant_id, id, slug, team_id, version, paused, created_at, updated_at) "
                "VALUES (:t, 'agt_pins', 'pins', 'team_a', 2, false, :at, :at)",
                {"t": tenant, "at": at},
            ),
            (version, {"t": tenant, "v": 1, "d": "d1", "s": old, "at": at}),
            (version, {"t": tenant, "v": 2, "d": "d2", "s": new, "at": at}),
            (
                "INSERT INTO agent_skill_pins (tenant_id, team_id, agent_id, skill_id, version) VALUES "
                "(:t, 'team_a', 'agt_pins', 'skl_a', 3), (:t, 'team_a', 'agt_pins', 'skl_b', 1)",
                {"t": tenant},
            ),
        )
    )
    (before,) = asyncio.run(_sql(emptied_database, (pins, {})))
    command.downgrade(cfg, "0112_definitions_list_indexes")
    command.upgrade(cfg, "head")
    (after,) = asyncio.run(_sql(emptied_database, (pins, {})))
    assert after == before == [("agt_pins", "skl_a", 3, "team_a"), ("agt_pins", "skl_b", 1, "team_a")]
    asyncio.run(_sql(emptied_database, ("DELETE FROM registry_agents WHERE id = 'agt_pins'", {})))
