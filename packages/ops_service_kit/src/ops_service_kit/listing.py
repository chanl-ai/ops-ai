"""One way to ask for a list: the query every list route takes.

  @router.get("", response_model=Envelope[ListResult[RunOut]])
  async def list_runs(p: CurrentPrincipal, _: Tx, q: ListQuery, rt: Rt) -> JSONResponse:
      return ok(await runs.list(rt, q))

`page`, `pageSize`, `search`, `sortBy`, `sortOrder` and `ids` are the same on every list; every other query key is a
filter, given once per value (`?status=open&status=held`), and the store names the columns it filters on
(`ops_store.listing.list_page`). A page size above the install's maximum (`OPS_PAGE_SIZE_MAX`) is answered at the
maximum, so no caller loads a whole table by asking for it. Both sizes are read from `Settings` once, when
`install_error_handlers` builds the app, never per request.
"""

from __future__ import annotations

from functools import cache
from typing import Annotated, Literal

from fastapi import Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

from .settings import Settings

# The keys every list shares; any other query key is a filter.
SHARED = frozenset({"page", "pageSize", "search", "sortBy", "sortOrder", "ids"})


@cache
def page_sizes() -> tuple[int, int]:
    """The install's default and maximum page size, read once per process."""
    settings = Settings()
    return settings.page_size_default, settings.page_size_max


class ListParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default_factory=lambda: page_sizes()[0], ge=1)
    search: str | None = None
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "desc"
    # Exact rows, for pickers and labels: the rows with these ids, whatever the search says.
    ids: list[str] | None = None
    filters: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("page_size")
    @classmethod
    def _capped(cls, size: int) -> int:
        return min(size, page_sizes()[1])


def list_params(
    request: Request,
    *,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(alias="pageSize", ge=1)] = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[Literal["asc", "desc"], Query(alias="sortOrder")] = "desc",
    ids: Annotated[list[str] | None, Query()] = None,
) -> ListParams:
    filters: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        if key not in SHARED and value:
            filters.setdefault(key, []).append(value)
    given = {} if page_size is None else {"page_size": page_size}
    return ListParams(
        page=page, search=search or None, sort_by=sort_by, sort_order=sort_order, ids=ids, filters=filters, **given
    )


ListQuery = Annotated[ListParams, Depends(list_params)]

__all__ = ["SHARED", "ListParams", "ListQuery", "list_params", "page_sizes"]
