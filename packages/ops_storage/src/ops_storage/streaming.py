# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The byte path every backend shares: obstore moves the bytes, the adapter keeps signing and governance.

obstore streams an async iterator into storage and switches to a multipart (S3) or block (Azure) upload above its
part size, so a large file never sits whole in memory. Every write is create-only (`mode="create"`): S3 sends
`If-None-Match: *`, Azure `If-None-Match: *`, the filesystem refuses an existing path, so content that has been
scanned cannot be replaced under the same key.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import TYPE_CHECKING

import obstore
from obstore.exceptions import AlreadyExistsError

from ops_storage.base import ObjectExistsError, ObjectNotFoundError, validate_key

if TYPE_CHECKING:
    from obstore.store import ObjectStore as ByteStore


async def _as_bytes(chunks: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    async for chunk in chunks:
        if chunk:
            yield chunk


async def put_create(store: ByteStore, key: str, chunks: AsyncIterable[bytes], *, content_type: str | None) -> None:
    """Write a new object at `key` from `chunks`. Raises `ObjectExistsError` when one is already there."""
    validate_key(key)
    attributes = {"Content-Type": content_type} if content_type is not None else None
    try:
        await obstore.put_async(store, key, _as_bytes(chunks), mode="create", attributes=attributes)
    except AlreadyExistsError as error:
        raise ObjectExistsError(key) from error


async def stream_object(store: ByteStore, key: str, *, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]:
    """The object's bytes in chunks of about `chunk_size`. Raises `ObjectNotFoundError` when there is none."""
    validate_key(key)
    try:
        result = await obstore.get_async(store, key)
    except FileNotFoundError as error:  # obstore's NotFoundError subclasses it
        raise ObjectNotFoundError(key) from error
    async for chunk in result.stream(min_chunk_size=chunk_size):
        yield bytes(chunk)


async def read_range(store: ByteStore, key: str, *, start: int, length: int) -> bytes:
    """`length` bytes from `start`; the caller keeps the range inside the object."""
    validate_key(key)
    if length <= 0:
        return b""
    try:
        return bytes(await obstore.get_range_async(store, key, start=start, length=length))
    except FileNotFoundError as error:
        raise ObjectNotFoundError(key) from error
