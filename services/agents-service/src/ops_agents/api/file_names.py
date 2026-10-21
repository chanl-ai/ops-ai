"""File display names for detail responses (c-434): a case or run that names a file by id says what the file is
called, which only files-service knows. Read through FilesClient as the record's team, a capped number per response;
a name that cannot be read is None and the console shows the id."""

from __future__ import annotations

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


async def named(rt: Runtime, team: str, files: list[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
    """`files` (each `{key: id, "name": ...}`) with each missing name read from files-service; unchanged without one."""
    reader = cast(FilesServiceNames | None, getattr(rt, "file_names", None))
    missing = [str(f[key]) for f in files if not f.get("name")]
    if reader is None or not missing:
        return files
    names = await reader.names(team, missing)
    return [f if f.get("name") else f | {"name": names.get(str(f[key]))} for f in files]
