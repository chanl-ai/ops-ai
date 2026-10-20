# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The bytes documents-service reads, through files-service as the caller's team (c-256): a file that team cannot see
is not found, one not scanned clean is refused, and a sample's file is kept by a `test_set` reference."""

from __future__ import annotations

from dataclasses import dataclass, field

from ops_documents.errors import FileMissingError, FileNotReadyError
from ops_files_client import FileInfo, FileNotFound, FileNotReady, FilesClient


@dataclass(frozen=True)
class Who:
    """The caller, from its token: tenant, the team it acts in and who it is. `edits` is documents.edit in the team, as
    `can()` decides it, which the console reads back as canCreate and canEdit; `manages` is documents.manage, which
    turning on page images needs (c-295)."""

    tenant_id: str
    team: str
    actor: str
    edits: bool = True
    manages: bool = False
    admin_teams: frozenset[str] = field(default_factory=frozenset[str])


@dataclass
class Files:
    client: FilesClient

    async def readable(self, who: Who, file_id: str) -> FileInfo:
        try:
            info = await self.client.get(who.tenant_id, who.team, file_id)
        except FileNotFound as e:
            raise FileMissingError(file_id) from e
        if info.scan.status != "clean":
            raise FileNotReadyError(f"{file_id} scan is {info.scan.status}")
        return info

    async def read(self, who: Who, file: FileInfo) -> bytes:
        try:
            return await self.client.read(who.tenant_id, who.team, file.id)
        except FileNotFound as e:
            raise FileMissingError(file.id) from e
        except FileNotReady as e:
            raise FileNotReadyError(str(e)) from e

    async def keep(self, who: Who, file_id: str, *, ref_id: str, name: str) -> None:
        """Files keeps the file while a sample names it (files 5.3.4)."""
        try:
            await self.client.attach(who.tenant_id, who.team, file_id, type="test_set", ref_id=ref_id, name=name)
        except FileNotFound as e:
            raise FileMissingError(file_id) from e
        except FileNotReady as e:
            raise FileNotReadyError(str(e)) from e

    async def release(self, who: Who, file_id: str, *, ref_id: str) -> None:
        try:
            await self.client.detach(who.tenant_id, who.team, file_id, type="test_set", ref_id=ref_id)
        except FileNotFound:
            return  # the file is gone already, and so is its reference
