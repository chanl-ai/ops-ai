"""One version of an alias serves at a time, held by the filtered unique index ux_model_aliases_current, on each
database, by failure mode: a new version leaves the old one current too, so which serves is left to a query's order;
a second current row of one alias is accepted (the index is missing, or unfiltered and refuses the retired ones)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.seed import SCRIPTED
from ops_models.store import Aliases
from ops_models.store.aliases import AliasFields
from ops_models.store.tables import model_aliases
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListParams

from .conftest import Models

FIELDS: AliasFields = {
    "provider_id": SCRIPTED,
    "model_id": "scripted-chat",
    "cleared_sensitivity": "internal",
    "input_per_million": Decimal("1"),
    "output_per_million": Decimal("2"),
}


async def test_two_versions_leave_one_current_and_a_second_current_is_refused(
    models: Models, database_url: str
) -> None:
    aliases = Aliases(models.engine)
    name = f"alias-{uuid4().hex[:8]}"
    assert await aliases.create(name, "chat", FIELDS)
    assert await aliases.add_version(name, FIELDS) == 2
    versions = await aliases.version_page(name, ListParams())
    assert versions is not None
    assert [(v.version, v.status) for v in versions.data] == [(1, "retired"), (2, "current")]

    row = {**FIELDS, "name": name, "version": 3, "kind": "chat", "status": "current", "created_at": now_iso()}
    engine = create_async_engine(database_url)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as c:
                await c.execute(sa.insert(model_aliases).values(**row))
        # A third retired version is no conflict: the index covers current rows only.
        async with engine.begin() as c:
            await c.execute(sa.insert(model_aliases).values(**{**row, "status": "retired"}))
    finally:
        await engine.dispose()
    assert (await aliases.current(name)) is not None
