"""How a row leaves a store: as the model it is, validated, never as a dict (`MD4`).

  async with self.tx() as conn:
      return await rows(conn, sa.select(*RUN_COLUMNS).where(team_visible(runs)), RunOut)

A column the statement selects and the model does not name is an error, as is a field the model needs and the
statement does not select, so the statement and the model cannot drift apart without a test failing.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncConnection

# A select of any number of columns.
Select = sa.Select[*tuple[Any, ...]]
# A statement one row comes back from: a select, or a write with `.returning(...)`.
Returning = Select | sa.Insert | sa.Update | sa.Delete


class UnnamedColumns(ValueError):
    """The statement selects columns the row model does not name."""


@cache
def _adapter[M: BaseModel](model: type[M]) -> TypeAdapter[list[M]]:
    return TypeAdapter(list[model])


@cache
def _names(model: type[BaseModel]) -> frozenset[str]:
    """The keys a row may carry for `model`: each field's name and its alias."""
    return frozenset(n for name, f in model.model_fields.items() for n in (name, f.alias) if n)


def _check(keys: list[str], model: type[BaseModel]) -> None:
    extra = sorted(set(keys) - _names(model))
    if extra:
        raise UnnamedColumns(f"{model.__name__} does not name the selected columns {', '.join(extra)}")


async def rows[M: BaseModel](conn: AsyncConnection, stmt: Select, model: type[M]) -> list[M]:
    """The only way a row leaves a store: the mapping validated through TypeAdapter(list[model]). A column the model
    does not name is an error, so the statement and the model cannot drift apart."""
    result = await conn.execute(stmt)
    _check(list(result.keys()), model)
    return _adapter(model).validate_python([dict(r) for r in result.mappings()])


async def one[M: BaseModel](conn: AsyncConnection, stmt: Returning, model: type[M]) -> M | None:
    """The one row `stmt` selects (or a write returns) as `model`, or None when there is none. More than one raises
    `sqlalchemy.exc.MultipleResultsFound`: a statement meant to find one row that finds two is a bug."""
    result = await conn.execute(stmt)
    _check(list(result.keys()), model)
    row = result.mappings().one_or_none()
    return None if row is None else model.model_validate(dict(row))
