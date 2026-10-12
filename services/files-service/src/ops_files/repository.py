# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""File metadata storage. The PostgreSQL implementation comes with the service; it needs a unique index on
(team, digest) for available files, which is what makes dedupe safe under concurrent completions."""

from __future__ import annotations

from typing import Protocol

from ops_files.models import StoredFile


class FileRepository(Protocol):
    def get(self, file_id: str) -> StoredFile | None: ...

    def save(self, record: StoredFile) -> None: ...

    def remove(self, file_id: str) -> None: ...

    def find_available_by_digest(self, team: str, digest: str) -> StoredFile | None:
        """The available file in `team` with this content digest. Never searches other teams."""
        ...


class InMemoryFileRepository:
    def __init__(self) -> None:
        self._files: dict[str, StoredFile] = {}

    def get(self, file_id: str) -> StoredFile | None:
        record = self._files.get(file_id)
        return record.model_copy(deep=True) if record else None

    def save(self, record: StoredFile) -> None:
        self._files[record.id] = record.model_copy(deep=True)

    def remove(self, file_id: str) -> None:
        self._files.pop(file_id, None)

    def find_available_by_digest(self, team: str, digest: str) -> StoredFile | None:
        for record in self._files.values():
            if record.team == team and record.digest == digest and record.status == "available":
                return record.model_copy(deep=True)
        return None
