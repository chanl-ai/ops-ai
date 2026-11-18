"""File display names for detail responses: a case or run that names a file by id says what the file is
called, which only files-service knows. Read through FilesClient as the record's team, a capped number per response;
a name that cannot be read is None and the console shows the id."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, cast

from ops_files_client import FilesClient, FilesRefused
from ops_identity import ServiceUnreachable
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant
from .deps import Runtime

log = get_logger("ops_agents.file_names")

# A response reads at most this many names, so a record listing many files costs a bounded number of calls.
NAMES_CAP = 10


class FilesServiceNames:
    def __init__(self, files: FilesClient) -> None:
        self.files = files

    async def names(self, team: str, ids: list[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for file_id in ids[:NAMES_CAP]:
            try:
                found[file_id] = (await self.files.get(current_tenant(), team, file_id)).name
            except (FilesRefused, ServiceUnreachable) as e:
                log.warning("file name unread; showing the id", extra={"file": file_id, "error": str(e)})
        return found


# The names this request already asked files-service for, by (team, file id); None outside `names_asked_once`, where
# every call asks.
_ASKED: ContextVar[dict[tuple[str, str], str | None] | None] = ContextVar("file_names_asked", default=None)


@contextmanager
def names_asked_once() -> Generator[None]:
    """Within the block, each file's name is asked of files-service once, however many times a page words it: a route
    asks for them with no transaction open (the names are warmed first), then builds from the answers."""
    token = _ASKED.set({})
    try:
        yield
    finally:
        _ASKED.reset(token)


async def named(rt: Runtime, team: str, files: list[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
    """`files` (each `{key: id, "name": ...}`) with each missing name read from files-service; unchanged without one."""
    reader = cast(FilesServiceNames | None, getattr(rt, "file_names", None))
    missing = [str(f[key]) for f in files if not f.get("name")]
    if reader is None or not missing:
        return files
    asked = _ASKED.get()
    if asked is None:
        names = await reader.names(team, missing)
    else:
        todo = [i for i in missing if (team, i) not in asked]
        if todo:
            read = await reader.names(team, todo)
            asked |= {(team, i): read.get(i) for i in todo}
        names = {i: n for i in missing if (n := asked[(team, i)]) is not None}
    return [f if f.get("name") else f | {"name": names.get(str(f[key]))} for f in files]
