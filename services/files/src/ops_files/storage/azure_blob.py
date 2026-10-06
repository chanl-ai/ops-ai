# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Azure Blob Storage object store.

SAS tokens are signed with a user delegation key, which comes from Microsoft Entra ID, expires with the key
and can be revoked by revoking the delegation keys. An account-key SAS can be revoked only by rotating the
account key, which breaks every other client, so it is refused unless `allow_account_key_sas` is set, which
only the Azurite test stack does.

Upload SAS tokens grant `create` only. Azure refuses a write to an existing blob under that permission, so a
leaked or reused upload URL cannot replace content that has already been scanned. A SAS cannot bind the
request length, so `FileService.complete_upload` checks the stored size and deletes an object of the wrong
size.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ImmutabilityPolicy,
    generate_blob_sas,
)

from ops_files.storage.base import (
    ObjectExistsError,
    ObjectInfo,
    ObjectLockedError,
    ObjectNotFoundError,
    PresignedRequest,
    RetentionMode,
    RetentionShortenError,
    StorageBackend,
    StorageError,
    check_expiry,
    check_retention_change,
    content_disposition,
    validate_key,
)

if TYPE_CHECKING:
    from azure.storage.blob import BlobClient, UserDelegationKey

# User delegation keys, and the SAS tokens signed with them, last at most seven days.
AZURE_MAX_URL_SECONDS = 7 * 24 * 3600
_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class AzureBlobConfig:
    container: str
    # Encryption scope (customer-managed key). Written into each upload SAS so writes through it are
    # encrypted with the scope's key. None uses the container default and is acceptable only in tests.
    encryption_scope: str | None = None
    max_url_seconds: int = 3600
    allow_account_key_sas: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.max_url_seconds <= AZURE_MAX_URL_SECONDS:
            raise ValueError(f"max_url_seconds must be between 1 and {AZURE_MAX_URL_SECONDS}")


_MODE_TO_AZURE: dict[RetentionMode, Literal["Locked", "Unlocked"]] = {"compliance": "Locked", "governance": "Unlocked"}


class AzureBlobObjectStore:
    def __init__(
        self,
        service: BlobServiceClient,
        config: AzureBlobConfig,
        *,
        account_key: str | None = None,
    ) -> None:
        if account_key is not None and not config.allow_account_key_sas:
            raise ValueError("account-key SAS is refused; use a token credential so SAS uses a user delegation key")
        self._service = service
        self._config = config
        self._account_key = account_key
        self._delegation: UserDelegationKey | None = None
        self._delegation_expires = datetime.min.replace(tzinfo=UTC)

    @property
    def backend(self) -> StorageBackend:
        return "azure_blob"

    @property
    def container(self) -> str:
        return self._config.container

    @property
    def max_url_seconds(self) -> int:
        return self._config.max_url_seconds

    def _blob(self, key: str) -> BlobClient:
        return self._service.get_blob_client(self._config.container, validate_key(key))

    def _delegation_key(self, needed_until: datetime) -> UserDelegationKey:
        if self._delegation is None or self._delegation_expires < needed_until:
            now = datetime.now(UTC)
            expires = now + timedelta(seconds=AZURE_MAX_URL_SECONDS) - _CLOCK_SKEW
            self._delegation = self._service.get_user_delegation_key(now - _CLOCK_SKEW, expires)
            self._delegation_expires = expires
        return self._delegation

    def _sas(self, key: str, permission: BlobSasPermissions, expires_in: int, **extra: str) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expiry = now + timedelta(seconds=expires_in)
        signer: dict[str, object] = (
            {"account_key": self._account_key}
            if self._account_key is not None
            else {"user_delegation_key": self._delegation_key(expiry)}
        )
        token = generate_blob_sas(
            account_name=str(self._service.account_name),
            container_name=self._config.container,
            blob_name=key,
            permission=permission,
            expiry=expiry,
            start=now - _CLOCK_SKEW,
            **signer,  # type: ignore[arg-type]
            **extra,
        )
        return f"{self._blob(key).url}?{token}", expiry

    def presign_put(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedRequest:
        validate_key(key)
        check_expiry(expires_in, self._config.max_url_seconds)
        extra = {"encryption_scope": self._config.encryption_scope} if self._config.encryption_scope else {}
        url, expiry = self._sas(key, BlobSasPermissions(create=True), expires_in, **extra)
        return PresignedRequest(
            url=url,
            method="PUT",
            headers={"x-ms-blob-type": "BlockBlob", "Content-Type": content_type, "If-None-Match": "*"},
            expires_at=expiry,
        )

    def presign_get(self, key: str, *, expires_in: int, filename: str) -> str:
        validate_key(key)
        check_expiry(expires_in, self._config.max_url_seconds)
        url, _ = self._sas(
            key, BlobSasPermissions(read=True), expires_in, content_disposition=content_disposition(filename)
        )
        return url

    def head(self, key: str) -> ObjectInfo | None:
        try:
            props = self._blob(key).get_blob_properties()
        except ResourceNotFoundError:
            return None
        policy = props.immutability_policy
        mode: RetentionMode | None = None
        if policy.expiry_time is not None:
            mode = "compliance" if policy.policy_mode == "Locked" else "governance"
        return ObjectInfo(
            key=key,
            size=props.size,
            content_type=props.content_settings.content_type or "application/octet-stream",
            version_id=props.version_id,
            retention_until=policy.expiry_time,
            retention_mode=mode,
            legal_hold=bool(props.has_legal_hold),
            metadata=dict(props.metadata or {}),
        )

    def iter_bytes(self, key: str, *, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        try:
            stream = self._blob(key).download_blob(max_concurrency=1)
        except ResourceNotFoundError as error:
            raise ObjectNotFoundError(key) from error
        yield from stream.chunks()

    def _require(self, key: str) -> ObjectInfo:
        info = self.head(key)
        if info is None:
            raise ObjectNotFoundError(key)
        return info

    def delete(self, key: str) -> None:
        info = self._require(key)
        if info.legal_hold:
            raise ObjectLockedError(f"{key} is under legal hold")
        if info.retention_until is not None and info.retention_until > datetime.now(UTC):
            raise ObjectLockedError(f"{key} is retained until {info.retention_until.isoformat()}")
        container = self._service.get_container_client(self._config.container)
        try:
            self._blob(key).delete_blob(delete_snapshots="include")
            # With versioning on, the delete above turns the current version into a previous version and the
            # bytes stay. Remove each remaining version of this exact name.
            for item in container.list_blobs(name_starts_with=key, include=["versions"]):
                if item.name == key and item.version_id:
                    self._blob(key).delete_blob(version_id=item.version_id)
        except ResourceNotFoundError:
            pass
        except HttpResponseError as error:
            if error.status_code in (403, 409):
                raise ObjectLockedError(f"{key}: {error.message}") from error
            raise

    def set_retention(self, key: str, until: datetime, mode: RetentionMode) -> None:
        info = self._require(key)
        check_retention_change(info.retention_until, info.retention_mode, until, mode)
        try:
            self._blob(key).set_immutability_policy(
                ImmutabilityPolicy(expiry_time=until, policy_mode=_MODE_TO_AZURE[mode])
            )
        except HttpResponseError as error:
            if error.status_code in (403, 409):
                raise RetentionShortenError(f"{key}: {error.message}") from error
            raise StorageError(f"{key}: {error.message}") from error

    def set_legal_hold(self, key: str, on: bool) -> None:
        self._require(key)
        try:
            self._blob(key).set_legal_hold(on)
        except HttpResponseError as error:
            raise StorageError(f"{key}: {error.message}") from error

    def copy(self, src: str, dst: str) -> None:
        self._require(src)
        if self.head(dst) is not None:
            raise ObjectExistsError(dst)
        source_url, _ = self._sas(src, BlobSasPermissions(read=True), 300)
        try:
            self._blob(dst).upload_blob_from_url(
                source_url, overwrite=False, encryption_scope=self._config.encryption_scope
            )
        except ResourceExistsError as error:
            raise ObjectExistsError(dst) from error
