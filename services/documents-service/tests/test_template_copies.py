"""Where a team's document type copies came from (migration documents_0014), by failure mode: a team reads or
writes another team's copies, so it could find another team's type as its own copy; a second install of the same
template version makes a second live copy; and a copy whose type was deleted still counts, so the template can never be
installed again. On the PostgreSQL test database migrated to head, as ops_documents_tenant."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.metadata import ROLE
from ops_documents.store.template_copies import TemplateCopies, template_copies
from ops_store import isolation
from ops_store.conformance import isolation_suite

SOURCE = "plugin:test.templates"


async def test_the_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, (template_copies,), role=ROLE) == []


async def test_one_live_copy_per_version_and_a_removed_one_lets_a_new_copy_in(engine: AsyncEngine, tenant: str) -> None:
    store = TemplateCopies(engine)

    async def add(record_id: str, version: int = 1) -> tuple[dict[str, object], bool]:
        return await store.add(
            team="team_ops",
            kind="document_type",
            record_id=record_id,
            source=SOURCE,
            template_id="case-letter",
            version=version,
            by="j@x",
        )

    with isolation.scope(tenant, "team_ops"):
        first, made = await add("dt_1")
        again, made_again = await add("dt_2")
        assert made and not made_again and again["id"] == first["id"] and again["record_id"] == "dt_1"
        await store.removed(str(first["id"]))
        assert await store.live(SOURCE, "case-letter") is None
        fresh, made_fresh = await add("dt_3")
        assert made_fresh and fresh["record_id"] == "dt_3"
        # Another version of the same template finds the copy the team holds: one copy follows one template.
        held, made_v2 = await add("dt_4", version=2)
        assert not made_v2 and held["record_id"] == "dt_3"
        # A detached copy stops counting, so a fresh one can be made, and keeps its row for the type's page.
        await store.detach(str(fresh["id"]), by="j@x")
        _, made_after = await add("dt_5", version=2)
        assert made_after
        assert sorted(str(c["record_id"]) for c in await store.of_team()) == ["dt_5"]
        assert (await store.of_record("dt_3") or {}).get("detached_by") == "j@x"
    with isolation.scope(tenant, "team_platform"):
        assert await store.live(SOURCE, "case-letter") is None and await store.of_team() == []
