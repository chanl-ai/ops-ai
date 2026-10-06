# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""One harness per backend. Every test that takes `harness` runs against each of them.

- `local` always runs and can prove every check.
- `s3-moto` always runs. Moto does not verify presigned signatures, so edge checks skip there.
- `s3-localstack` runs when LocalStack answers on `OPS_FILES_LOCALSTACK_URL`; it verifies signatures,
  signed length and type, `If-None-Match` and Object Lock.
- `azure-azurite` runs when Azurite answers on `OPS_FILES_AZURITE_URL`; it verifies SAS tokens but does
  not implement immutability policies or legal holds, so those checks skip there.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import boto3
import httpx
import pytest
from azure.storage.blob import BlobServiceClient
from botocore.config import Config
from moto.server import ThreadedMotoServer

from ops_files.models import RetentionClass
from ops_files.repository import InMemoryFileRepository
from ops_files.scanning import EicarScanner
from ops_files.service import FilesConfig, FileService
from ops_files.storage.azure_blob import AzureBlobConfig, AzureBlobObjectStore
from ops_files.storage.base import ObjectStore, UploadRejectedError
from ops_files.storage.local import LocalObjectStore
from ops_files.storage.s3 import S3Config, S3ObjectStore

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

LOCALSTACK_URL = os.environ.get("OPS_FILES_LOCALSTACK_URL", "http://127.0.0.1:4566")
AZURITE_URL = os.environ.get("OPS_FILES_AZURITE_URL", "http://127.0.0.1:10000/devstoreaccount1")
# Azurite's published development account key; not a secret.
AZURITE_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="

BACKENDS = ["local", "s3-moto", "s3-localstack", "azure-azurite"]
MAX_DOWNLOAD_SECONDS = 300


@dataclass
class Harness:
    name: str
    store: ObjectStore
    put: Callable[[str, Mapping[str, str], bytes], int]
    get: Callable[[str], tuple[int, bytes]]
    url_ttl: Callable[[str], float]
    versions_left: Callable[[str], int]
    verifies_signatures: bool = True
    worm: bool = True
    notes: dict[str, str] = field(default_factory=dict[str, str])

    def require_signatures(self) -> None:
        if not self.verifies_signatures:
            pytest.skip(f"{self.name}: does not verify presigned signatures, so this edge check cannot fail here")

    def require_worm(self) -> None:
        if not self.worm:
            pytest.skip(f"{self.name}: does not implement immutability policies or legal holds")


def _reachable(url: str) -> bool:
    try:
        httpx.get(url, timeout=1.0)
    except httpx.HTTPError:
        return False
    return True


def _http_put(url: str, headers: Mapping[str, str], body: bytes) -> int:
    # The client library sets Content-Length from the body, as a browser or attacker would.
    sent = {k: v for k, v in headers.items() if k.lower() != "content-length"}
    return httpx.put(url, content=body, headers=sent, timeout=10.0).status_code


def _http_get(url: str) -> tuple[int, bytes]:
    response = httpx.get(url, timeout=10.0)
    return response.status_code, response.content


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@pytest.fixture(scope="session")
def moto_endpoint() -> Iterator[str]:
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


def _s3_harness(name: str, endpoint: str, *, verifies: bool) -> Harness:
    client: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"ops-files-{uuid.uuid4().hex[:12]}"
    # Object Lock turns versioning on, which is the production bucket setting.
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    store = S3ObjectStore(client, S3Config(bucket=bucket, kms_key_id="alias/ops-files"))

    def versions_left(key: str) -> int:
        out = client.list_object_versions(Bucket=bucket, Prefix=key)
        entries = [*out.get("Versions", []), *out.get("DeleteMarkers", [])]
        return sum(1 for entry in entries if entry.get("Key") == key)

    return Harness(
        name=name,
        store=store,
        put=_http_put,
        get=_http_get,
        url_ttl=lambda url: float(_query(url)["X-Amz-Expires"]),
        versions_left=versions_left,
        verifies_signatures=verifies,
    )


def _azure_harness() -> Harness:
    service = BlobServiceClient(
        account_url=AZURITE_URL, credential={"account_name": "devstoreaccount1", "account_key": AZURITE_KEY}
    )
    container = f"ops-files-{uuid.uuid4().hex[:12]}"
    service.create_container(container)  # pyright: ignore[reportUnknownMemberType]
    store = AzureBlobObjectStore(
        service, AzureBlobConfig(container=container, allow_account_key_sas=True), account_key=AZURITE_KEY
    )

    def ttl(url: str) -> float:
        expiry = datetime.fromisoformat(_query(url)["se"].replace("Z", "+00:00"))
        return (expiry - datetime.now(UTC)).total_seconds()

    def versions_left(key: str) -> int:
        items = service.get_container_client(container).list_blobs(name_starts_with=key, include=["versions"])
        return sum(1 for item in items if item.name == key)

    return Harness(
        name="azure-azurite",
        store=store,
        put=_http_put,
        get=_http_get,
        url_ttl=ttl,
        versions_left=versions_left,
        worm=False,
    )


def _local_harness(root: Path) -> Harness:
    store = LocalObjectStore(root, signing_key=b"k" * 32)

    def put(url: str, headers: Mapping[str, str], body: bytes) -> int:
        try:
            store.receive_put(url, headers, body)
        except UploadRejectedError:
            return 403
        return 200

    def get(url: str) -> tuple[int, bytes]:
        try:
            return 200, store.receive_get(url)
        except UploadRejectedError:
            return 403, b""

    def ttl(url: str) -> float:
        return (datetime.fromisoformat(_query(url)["exp"]) - datetime.now(UTC)).total_seconds()

    return Harness(
        name="local",
        store=store,
        put=put,
        get=get,
        url_ttl=ttl,
        versions_left=lambda key: int(store.path_of(key).exists()),
    )


@pytest.fixture(params=BACKENDS)
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Harness:
    name: str = request.param
    if name == "local":
        return _local_harness(tmp_path)
    if name == "s3-moto":
        return _s3_harness(name, request.getfixturevalue("moto_endpoint"), verifies=False)
    if name == "s3-localstack":
        if not _reachable(f"{LOCALSTACK_URL}/_localstack/health"):
            pytest.skip(f"LocalStack not reachable at {LOCALSTACK_URL}")
        return _s3_harness(name, LOCALSTACK_URL, verifies=True)
    if not _reachable(AZURITE_URL):
        pytest.skip(f"Azurite not reachable at {AZURITE_URL}")
    return _azure_harness()


RETENTION_CLASSES = (
    RetentionClass(id="standard", name="Standard", days=None),
    RetentionClass(
        id="case-7y", name="Case record, 7 years", days=2555, purposes=["case_attachment"], keep_until_end=True
    ),
    RetentionClass(id="evidence-10y", name="Evidence, 10 years", days=3650, purposes=["evidence_bundle"], worm=True),
    RetentionClass(id="evidence-1y", name="Evidence, 1 year", days=365, worm=True),
)


@pytest.fixture
def service(harness: Harness) -> FileService:
    config = FilesConfig(
        retention_classes=RETENTION_CLASSES,
        default_retention_class="standard",
        max_download_url_seconds=MAX_DOWNLOAD_SECONDS,
    )
    return FileService(harness.store, InMemoryFileRepository(), config, scanner=EicarScanner())
