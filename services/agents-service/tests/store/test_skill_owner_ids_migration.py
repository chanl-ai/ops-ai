"""Migration 20261124_0257 makes each skill's owner team the id of the team that holds it, by failure mode: a row
holding a team name, or another team's id, in any tenant, keeps it, so the list shows text that names no team or a team
that decides nothing; a row already right is changed; the table is left without its forced row policy."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0120_model_call_reservations"
SKILL = (
    "INSERT INTO registry_skills (tenant_id, id, slug, owner_team, team_id, origin, version, created_at, updated_at, "
    "updated_by) VALUES (:t, :s, :s, :owner, :team, 'blank', 1, :at, :at, 'a@x')"
)
FORCED = "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'registry_skills'"


def test_every_skill_takes_the_team_that_holds_it_in_every_tenant(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    one, other, at = new_id("ten"), new_id("ten"), now_iso()
    named, elsewhere, right = new_id("sk"), new_id("sk"), new_id("sk")
    asyncio.run(
        _sql(
            emptied_database,
            (SKILL, {"t": one, "s": named, "owner": "Card operations", "team": "team_cards", "at": at}),
            (SKILL, {"t": other, "s": elsewhere, "owner": "team_legal", "team": "team_cards", "at": at}),
            (SKILL, {"t": other, "s": right, "owner": "team_legal", "team": "team_legal", "at": at}),
        )
    )
    command.upgrade(cfg, "head")
    query = "SELECT id, owner_team FROM registry_skills WHERE id IN (:a, :b, :c) ORDER BY id"
    ids = {"a": named, "b": elsewhere, "c": right}
    (rows,) = asyncio.run(_sql(emptied_database, (query, ids)))
    assert dict(rows) == {named: "team_cards", elsewhere: "team_cards", right: "team_legal"}, rows
    (forced,) = asyncio.run(_sql(emptied_database, (FORCED, {})))
    assert forced == [(True,)]
    asyncio.run(_sql(emptied_database, ("DELETE FROM registry_skills WHERE id IN (:a, :b, :c)", ids)))
