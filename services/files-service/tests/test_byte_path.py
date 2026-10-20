# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The obstore byte path inside each storage adapter (`StreamingObjectStore`): streamed, create-only writes and
streamed or ranged reads. Local runs on the filesystem, S3 on the moto server, Azure on obstore's in-memory store
standing in for the storage account (its signing and governance calls stay on the Azure SDK)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import boto3
import pytest
from azure.storage.blob import BlobServiceClient
from botocore.config import Config
from obstore.store import MemoryStore, S3Store

from ops_storage.azure_blob import AzureBlobConfig, AzureBlobObjectStore
from ops_storage.base import ObjectExistsError, ObjectNotFoundError, StreamingObjectStore
from ops_storage.local import LocalObjectStore
from ops_storage.s3 import S3Config, S3ObjectStore
from tests.conftest import AZURITE_KEY

KEY = "team_ops/chat_attachment/2026/10/fil_bytes"


def _local(tmp_path: Path, _moto: Callable[[], str]) -> StreamingObjectStore:
    return LocalObjectStore(tmp_path, signing_key=b"k" * 32)


def _s3(_tmp: Path, moto: Callable[[], str]) -> StreamingObjectStore:
    endpoint = moto()
    client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"ops-bytes-{abs(hash(_tmp)) % 10**10}"
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    byte_store = S3Store(
        bucket,
        config={
            "endpoint": endpoint,
            "region": "us-east-1",
            "access_key_id": "test",
            "secret_access_key": "test",
            "virtual_hosted_style_request": False,
        },
        client_options={"allow_http": True},
    )
    return S3ObjectStore(client, S3Config(bucket=bucket), byte_store=byte_store)


def _azure(_tmp: Path, _moto: Callable[[], str]) -> StreamingObjectStore:
    service = BlobServiceClient(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        credential={"account_name": "devstoreaccount1", "account_key": AZURITE_KEY},
    )
    config = AzureBlobConfig(container="files", allow_account_key_sas=True)
    return AzureBlobObjectStore(service, config, account_key=AZURITE_KEY, byte_store=MemoryStore())


BACKENDS: dict[str, Callable[[Path, Callable[[], str]], StreamingObjectStore]] = {
    "local": _local,
    "s3-moto": _s3,
    "azure-memory": _azure,
}


@pytest.fixture(params=list(BACKENDS))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> StreamingObjectStore:
    return BACKENDS[request.param](tmp_path, lambda: request.getfixturevalue("moto_endpoint"))


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def _read(store: StreamingObjectStore, key: str) -> bytes:
    return b"".join([chunk async for chunk in store.open_read(key, chunk_size=4)])


async def test_streamed_write_reads_back_whole_and_by_range(store: StreamingObjectStore) -> None:
    await store.put_stream(KEY, _chunks(b"%PDF-1.7\n", b"body ", b"bytes"), content_type="application/pdf")
    assert await _read(store, KEY) == b"%PDF-1.7\nbody bytes"
    assert await store.read_range(KEY, start=0, length=8) == b"%PDF-1.7"


async def test_a_streamed_write_never_replaces_an_object(store: StreamingObjectStore) -> None:
    await store.put_stream(KEY, _chunks(b"scanned clean"), content_type="text/plain")
    with pytest.raises(ObjectExistsError):
        await store.put_stream(KEY, _chunks(b"swapped after scan"), content_type="text/plain")
    assert await _read(store, KEY) == b"scanned clean"


async def test_a_missing_object_reads_as_not_found(store: StreamingObjectStore) -> None:
    with pytest.raises(ObjectNotFoundError):
        await _read(store, KEY)


async def test_a_streamed_write_is_seen_by_the_sync_contract(tmp_path: Path) -> None:
    """Local only: in-process callers (kb-service, chat attachments) read through `head` and `iter_bytes`."""
    store = LocalObjectStore(tmp_path, signing_key=b"k" * 32)
    await store.put_stream(KEY, _chunks(b"a,b\n1,2\n"), content_type="text/csv")
    info = store.head(KEY)
    assert info is not None and info.size == 8 and info.content_type == "text/csv"
    assert b"".join(store.iter_bytes(KEY)) == b"a,b\n1,2\n"
