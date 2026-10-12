# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The object-store contract every storage backend implements, and its typed errors."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import quote

StorageBackend = Literal["s3", "azure_blob", "local"]
RetentionMode = Literal["governance", "compliance"]

# Keys are built by the service from platform values only. A key that does not match is refused by
# every backend, so a user-supplied name or a `..` segment cannot reach a bucket path or the filesystem.
_KEY_SEGMENT = r"[a-z0-9][a-z0-9_-]{0,127}"
KEY_PATTERN = re.compile(rf"^{_KEY_SEGMENT}(?:/{_KEY_SEGMENT}){{1,15}}$")


class StorageError(Exception):
    """Base class for object-store failures."""


class InvalidKeyError(StorageError):
    """The key does not match `KEY_PATTERN`."""


class ObjectNotFoundError(StorageError):
    """No object at the key."""


class ObjectExistsError(StorageError):
    """The destination already holds an object; stores never overwrite."""


class ObjectLockedError(StorageError):
    """A retention period or legal hold forbids the change."""


class RetentionShortenError(ObjectLockedError):
    """The request would shorten retention or weaken its mode."""


class ExpiryTooLongError(StorageError):
    """A signed URL was requested for longer than the store allows."""


class UploadRejectedError(StorageError):
    """The store refused an upload made with a presigned request (signature, expiry, size or type)."""


@dataclass(frozen=True)
class PresignedRequest:
    """One upload the client may make. The headers are part of the signature; sending others fails."""

    url: str
    method: Literal["PUT"]
    headers: Mapping[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    content_type: str
    version_id: str | None = None
    retention_until: datetime | None = None
    retention_mode: RetentionMode | None = None
    legal_hold: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict[str, str])


class ObjectStore(Protocol):
    """Byte storage behind the Files service. Only `FileService` calls it."""

    @property
    def backend(self) -> StorageBackend: ...

    @property
    def container(self) -> str: ...

    @property
    def max_url_seconds(self) -> int:
        """Longest lifetime this store will sign a URL for."""
        ...

    def presign_put(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedRequest:
        """A single-use upload to exactly `key`. Stores that can bind the length bind it to `max_bytes`."""
        ...

    def presign_get(self, key: str, *, expires_in: int, filename: str) -> str: ...

    def head(self, key: str) -> ObjectInfo | None: ...

    def iter_bytes(self, key: str, *, chunk_size: int = 1 << 20) -> Iterator[bytes]: ...

    def delete(self, key: str) -> None:
        """Remove every version of the object. Raises `ObjectLockedError` while retained or held."""
        ...

    def set_retention(self, key: str, until: datetime, mode: RetentionMode) -> None:
        """Extend retention. Raises `RetentionShortenError` for an earlier date or a weaker mode."""
        ...

    def set_legal_hold(self, key: str, on: bool) -> None: ...

    def copy(self, src: str, dst: str) -> None:
        """Copy within the store. Raises `ObjectExistsError` when `dst` exists."""
        ...


def validate_key(key: str) -> str:
    if not KEY_PATTERN.fullmatch(key):
        raise InvalidKeyError(f"invalid object key {key!r}")
    return key


def check_expiry(expires_in: int, maximum: int) -> int:
    if expires_in <= 0 or expires_in > maximum:
        raise ExpiryTooLongError(f"expires_in must be between 1 and {maximum} seconds, got {expires_in}")
    return expires_in


_RANK: dict[RetentionMode, int] = {"governance": 0, "compliance": 1}


def check_retention_change(
    current_until: datetime | None,
    current_mode: RetentionMode | None,
    until: datetime,
    mode: RetentionMode,
) -> None:
    """Retention only moves later and only gets stricter, in every mode.

    S3 lets a caller with `s3:BypassGovernanceRetention` shorten governance retention; this service never
    uses that permission, and refusing here keeps the three backends identical.
    """
    if current_until is None or current_mode is None:
        return
    if until < current_until:
        raise RetentionShortenError(f"retention ends {current_until.isoformat()}; refusing {until.isoformat()}")
    if _RANK[mode] < _RANK[current_mode]:
        raise RetentionShortenError(f"retention mode is {current_mode}; refusing {mode}")


def content_disposition(filename: str) -> str:
    """`attachment` with an ASCII fallback and an RFC 5987 UTF-8 name, so a name cannot inject headers."""
    cleaned = "".join(ch for ch in filename if unicodedata.category(ch)[0] != "C").replace("/", "_").replace("\\", "_")
    cleaned = cleaned.strip() or "download"
    ascii_name = cleaned.encode("ascii", "replace").decode("ascii").replace('"', "'").replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(cleaned, safe='')}"
