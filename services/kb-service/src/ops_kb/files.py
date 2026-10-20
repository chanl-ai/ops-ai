"""Where a source's uploaded files are kept, behind one adapter: a source holds file ids, `FileIntake.put` stores an
upload and `FileIntake.read` gives its bytes back at sync. kb-service has no upload store of its own.

`FilesServiceIntake` stores through files-service (`ops_files_client`), the store every service shares; kb-service
uses it when `files_url` (OPS_FILES_URL) names files-service. `make up` sets it for kb-service (scripts/stack.sh, the
kb start line) and so does the use-case harness; unset, kb-service falls back to `KnowledgeFiles`.
`KnowledgeFiles` keeps files in a directory under `kb_files_dir`, for tests and a kb-service run without
files-service. kb-service never imports files-service's own code (tests/test_boundary.py). File ids from one are
unknown to the other, so switching a deployment re-uploads its files (the dev seed does this for the demo bases).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import httpx

from ops_files_client import FileNotFound, FileNotReady, FilesClient, FilesRefused
from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class FileMissing(Exception):
    """The file id is not in storage, or not in this team."""


class FileNotScanned(Exception):
    """The file is stored but not yet scanned clean, so it cannot be read; a later sync reads it."""


@dataclass(frozen=True)
class Stored:
    file_id: str
    name: str
    mime: str
    size: int
    digest: str
    deduplicated: bool


class FileIntake(Protocol):
    async def put(self, tenant: str, team: str, data: bytes, *, name: str, mime: str, actor: str) -> Stored:
        """Stores an upload; ValueError when it is refused (too large, empty, a type files do not take)."""
        ...

    async def read(self, tenant: str, team: str, file_id: str) -> tuple[str, str, bytes]:
        """(name, mime, bytes); FileMissing when there is no such file, FileNotScanned before it is clean."""
        ...

    async def use(self, tenant: str, team: str, file_id: str, *, source_id: str, source_name: str) -> str:
        """Records that the source reads a file already stored in `team` and returns its name; FileMissing when the
        team has no such file, FileNotScanned when it is not scanned clean."""
        ...

    async def release(self, tenant: str, team: str, file_id: str, *, source_id: str) -> None:
        """Removes the source's reference to the file; a file or reference already gone is not an error."""
        ...


def _too_large(name: str, data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{name} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")


def _unavailable(e: FilesRefused | httpx.HTTPError, doing: str) -> ServiceUnavailable:
    """What a person reads when files-service refuses or cannot be reached: which store failed, that nothing changed,
    and what to do, rather than a generic server error."""
    why = f"it refused the request ({e.status} {e.code})" if isinstance(e, FilesRefused) else "it could not be reached"
    return ServiceUnavailable(
        f"The file store could not {doing}: {why}. Nothing was changed; try again in a minute, and tell an admin if it "
        "keeps happening.",
        code="files_unavailable",
    )


class FilesServiceIntake:
    def __init__(self, client: FilesClient) -> None:
        self._client = client

    async def put(self, tenant: str, team: str, data: bytes, *, name: str, mime: str, actor: str) -> Stored:
        _too_large(name, data)
        try:
            stored = await self._client.write(
                tenant, team, data, name=name, mime=mime, purpose="knowledge_source", uploaded_by=actor
            )
        except FileNotReady as e:
            raise ValueError(str(e)) from e
        except (FilesRefused, httpx.HTTPError) as e:
            raise _unavailable(e, "store the file") from e
        f = stored.file
        return Stored(f.id, f.name, f.mime, f.size, f.digest, stored.deduplicated)

    async def read(self, tenant: str, team: str, file_id: str) -> tuple[str, str, bytes]:
        try:
            info = await self._client.get(tenant, team, file_id)
            return info.name, info.mime, await self._client.read(tenant, team, file_id)
        except FileNotFound as e:
            raise FileMissing(file_id) from e
        except FileNotReady as e:
            raise FileNotScanned(file_id) from e
        except (FilesRefused, httpx.HTTPError) as e:
            raise _unavailable(e, "read this source's files") from e

    async def use(self, tenant: str, team: str, file_id: str, *, source_id: str, source_name: str) -> str:
        # The reference keeps the file in Files while the source reads it; attaching the same source again is a no-op.
        try:
            info = await self._client.attach(tenant, team, file_id, type="source", ref_id=source_id, name=source_name)
        except FileNotFound as e:
            raise FileMissing(file_id) from e
        except FileNotReady as e:
            raise FileNotScanned(file_id) from e
        except (FilesRefused, httpx.HTTPError) as e:
            raise _unavailable(e, "add the file") from e
        return info.name

    async def release(self, tenant: str, team: str, file_id: str, *, source_id: str) -> None:
        with contextlib.suppress(FileNotFound):
            await self._client.detach(tenant, team, file_id, type="source", ref_id=source_id)


@dataclass(frozen=True)
class _Record:
    stored: Stored
    team: str
    bytes_at: Path


class KnowledgeFiles:
    """Files in a directory: each file's bytes under its digest and its record as JSON, so a restart keeps every
    uploaded file readable. One team's identical upload is stored once, under its first name, as files-service does.

    Directories written before c-094 hold the files-service library's layout: a StoredFile record (`id`, `storage.key`)
    with the bytes at `objects/data/<key>`. Both are read, so a stack that has not moved to files-service keeps its
    files; new uploads use the digest layout."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._blobs = root / "blobs"
        self._records = root / "records"
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._records.mkdir(parents=True, exist_ok=True)

    def _load(self, path: Path) -> _Record | None:
        body = json.loads(path.read_text())
        if not isinstance(body, dict):
            return None
        rec: dict[str, Any] = body  # pyright: ignore[reportUnknownVariableType]
        storage: dict[str, Any] | None = rec.get("storage")
        if storage is not None and "id" in rec:
            if rec.get("status") != "available":
                return None
            at = self._root / "objects" / "data" / str(storage["key"])
            file_id = str(rec["id"])
        else:
            at = self._blobs / str(rec["digest"])
            file_id = str(rec["file_id"])
        stored = Stored(file_id, str(rec["name"]), str(rec["mime"]), int(rec["size"]), str(rec["digest"]), False)
        return _Record(stored, str(rec["team"]), at)

    async def put(self, tenant: str, team: str, data: bytes, *, name: str, mime: str, actor: str) -> Stored:
        # One store per deployment under kb_files_dir: the tenant is not part of a file's key here.
        _too_large(name, data)
        digest = hashlib.sha256(data).hexdigest()
        for path in self._records.glob("*.json"):
            rec = self._load(path)
            if rec is not None and rec.team == team and rec.stored.digest == digest and rec.bytes_at.exists():
                return replace(rec.stored, deduplicated=True)
        stored = Stored(new_id("fil"), name, mime, len(data), digest, False)
        (self._blobs / digest).write_bytes(data)
        (self._records / f"{stored.file_id}.json").write_text(json.dumps({**asdict(stored), "team": team}))
        return stored

    async def read(self, tenant: str, team: str, file_id: str) -> tuple[str, str, bytes]:
        path = self._records / f"{file_id}.json"
        if not file_id.replace("_", "").isalnum() or not path.exists():
            raise FileMissing(file_id)
        rec = self._load(path)
        if rec is None or rec.team != team or not rec.bytes_at.exists():
            raise FileMissing(file_id)
        return rec.stored.name, rec.stored.mime, rec.bytes_at.read_bytes()

    async def use(self, tenant: str, team: str, file_id: str, *, source_id: str, source_name: str) -> str:
        # No scan and no references in this store: a file of the team is always readable.
        return (await self.read(tenant, team, file_id))[0]

    async def release(self, tenant: str, team: str, file_id: str, *, source_id: str) -> None:
        return None


async def move_files(
    tenant: str, team: str, file_ids: list[str], names: dict[str, str], *, to: FileIntake, old: FileIntake
) -> dict[str, str]:
    """Copies each file `to` cannot read but `old` can into `to`, under the name the source gave it; returns the
    moved ids, old to new. A file neither store has is left for sync to report as missing."""
    moved: dict[str, str] = {}
    for file_id in file_ids:
        try:
            await to.read(tenant, team, file_id)
            continue
        except FileMissing:
            pass
        except (FileNotScanned, FilesRefused):
            # Not readable yet, or files-service could not answer: left as it is, and sync says why.
            continue
        try:
            name, mime, data = await old.read(tenant, team, file_id)
        except FileMissing:
            continue
        stored = await to.put(tenant, team, data, name=names.get(file_id, name), mime=mime, actor="kb-service")
        moved[file_id] = stored.file_id
    return moved


def file_intake(settings: Settings) -> FileIntake:
    """files-service when `files_url` names it; otherwise the in-process store under `kb_files_dir`."""
    if settings.files_url:
        return FilesServiceIntake(FilesClient.from_settings(settings, service="kb"))
    return KnowledgeFiles(settings.kb_files_dir)
