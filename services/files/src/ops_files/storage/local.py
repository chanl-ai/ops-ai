# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Filesystem object store for development and tests.

It enforces what the cloud backends enforce: signed URLs bound to one key, method, content type, size
limit and expiry; no overwrite of an existing object; retention that only extends; legal holds that block
deletion. URLs use the `local://` scheme and are redeemed with `receive_put` and `receive_get`, which
stand in for the HTTP endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from ops_files.storage.base import (
    ObjectExistsError,
    ObjectInfo,
    ObjectLockedError,
    ObjectNotFoundError,
    PresignedRequest,
    RetentionMode,
    StorageBackend,
    UploadRejectedError,
    check_expiry,
    check_retention_change,
    content_disposition,
    validate_key,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LocalObjectStore:
    def __init__(
        self,
        root: Path,
        *,
        container: str = "local",
        signing_key: bytes,
        max_url_seconds: int = 3600,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("signing_key must be at least 32 bytes")
        self._root = root.resolve()
        self._container = container
        self._key = signing_key
        self._max_url_seconds = max_url_seconds
        self._clock = clock
        (self._root / "data").mkdir(parents=True, exist_ok=True)
        (self._root / "meta").mkdir(parents=True, exist_ok=True)

    @property
    def backend(self) -> StorageBackend:
        return "local"

    @property
    def container(self) -> str:
        return self._container

    @property
    def max_url_seconds(self) -> int:
        return self._max_url_seconds

    # ── paths ──

    def _path(self, area: Literal["data", "meta"], key: str) -> Path:
        validate_key(key)
        base = self._root / area
        path = (base / (key + (".json" if area == "meta" else ""))).resolve()
        # validate_key already excludes `..`; this guards a future change to the pattern.
        if not path.is_relative_to(base):
            raise ValueError(f"key {key!r} resolves outside the store")
        return path

    def _read_meta(self, key: str) -> dict[str, str | bool | None] | None:
        path = self._path("meta", key)
        if not path.exists():
            return None
        return cast(dict[str, str | bool | None], json.loads(path.read_text()))

    def _write_meta(self, key: str, meta: Mapping[str, str | bool | None]) -> None:
        path = self._path("meta", key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(meta)))

    def path_of(self, key: str) -> Path:
        """Filesystem path of an object's bytes, for tests that check where data lands."""
        return self._path("data", key)

    # ── signing ──

    def _sign(self, fields: Mapping[str, str]) -> str:
        message = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
        return hmac.new(self._key, message.encode(), hashlib.sha256).hexdigest()

    def _signed_url(self, key: str, fields: dict[str, str]) -> str:
        signature = self._sign({**fields, "key": key})
        return f"local://{self._container}/{quote(key)}?{urlencode({**fields, 'sig': signature})}"

    def _verify(self, url: str, op: str) -> tuple[str, dict[str, str]]:
        parts = urlsplit(url)
        if parts.scheme != "local" or parts.netloc != self._container:
            raise UploadRejectedError("URL is not for this store")
        key = unquote(parts.path.lstrip("/"))
        query = {k: v[0] for k, v in parse_qs(parts.query, strict_parsing=True).items()}
        signature = query.pop("sig", "")
        if not hmac.compare_digest(signature, self._sign({**query, "key": key})):
            raise UploadRejectedError("signature does not match")
        if query.get("op") != op:
            raise UploadRejectedError(f"URL is not valid for {op}")
        if self._clock() >= datetime.fromisoformat(query["exp"]):
            raise UploadRejectedError("URL has expired")
        return validate_key(key), query

    # ── ObjectStore ──

    def presign_put(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedRequest:
        validate_key(key)
        check_expiry(expires_in, self._max_url_seconds)
        expires_at = self._clock() + timedelta(seconds=expires_in)
        fields = {"op": "put", "ct": content_type, "max": str(max_bytes), "exp": expires_at.isoformat()}
        return PresignedRequest(
            url=self._signed_url(key, fields),
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=expires_at,
        )

    def receive_put(self, url: str, headers: Mapping[str, str], body: bytes) -> None:
        """What the HTTP endpoint would do with a PUT to a presigned URL."""
        key, query = self._verify(url, "put")
        sent_type = next((v for k, v in headers.items() if k.lower() == "content-type"), None)
        if sent_type != query["ct"]:
            raise UploadRejectedError("content type does not match the signed type")
        if len(body) > int(query["max"]):
            raise UploadRejectedError(f"body is {len(body)} bytes; limit is {query['max']}")
        path = self._path("data", key)
        if path.exists():
            raise UploadRejectedError("object exists; presigned uploads never overwrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(body)
        os.replace(tmp, path)
        self._write_meta(key, {"content_type": query["ct"], "retention_until": None, "mode": None, "hold": False})

    def presign_get(self, key: str, *, expires_in: int, filename: str) -> str:
        validate_key(key)
        check_expiry(expires_in, self._max_url_seconds)
        expires_at = self._clock() + timedelta(seconds=expires_in)
        fields = {"op": "get", "exp": expires_at.isoformat(), "cd": content_disposition(filename)}
        return self._signed_url(key, fields)

    def receive_get(self, url: str) -> bytes:
        key, _ = self._verify(url, "get")
        path = self._path("data", key)
        if not path.exists():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def head(self, key: str) -> ObjectInfo | None:
        path = self._path("data", key)
        meta = self._read_meta(key)
        if not path.exists() or meta is None:
            return None
        until = meta.get("retention_until")
        return ObjectInfo(
            key=key,
            size=path.stat().st_size,
            content_type=str(meta["content_type"]),
            retention_until=datetime.fromisoformat(until) if isinstance(until, str) else None,
            retention_mode=cast(RetentionMode | None, meta.get("mode")),
            legal_hold=bool(meta.get("hold")),
        )

    def iter_bytes(self, key: str, *, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        path = self._path("data", key)
        if not path.exists():
            raise ObjectNotFoundError(key)
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def _require(self, key: str) -> ObjectInfo:
        info = self.head(key)
        if info is None:
            raise ObjectNotFoundError(key)
        return info

    def delete(self, key: str) -> None:
        info = self._require(key)
        if info.legal_hold:
            raise ObjectLockedError(f"{key} is under legal hold")
        if info.retention_until is not None and info.retention_until > self._clock():
            raise ObjectLockedError(f"{key} is retained until {info.retention_until.isoformat()}")
        self._path("data", key).unlink()
        self._path("meta", key).unlink()

    def set_retention(self, key: str, until: datetime, mode: RetentionMode) -> None:
        info = self._require(key)
        check_retention_change(info.retention_until, info.retention_mode, until, mode)
        meta = self._read_meta(key) or {}
        self._write_meta(key, {**meta, "retention_until": until.isoformat(), "mode": mode})

    def set_legal_hold(self, key: str, on: bool) -> None:
        self._require(key)
        meta = self._read_meta(key) or {}
        self._write_meta(key, {**meta, "hold": on})

    def copy(self, src: str, dst: str) -> None:
        info = self._require(src)
        target = self._path("data", dst)
        if target.exists():
            raise ObjectExistsError(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self._path("data", src).read_bytes())
        self._write_meta(dst, {"content_type": info.content_type, "retention_until": None, "mode": None, "hold": False})
