# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Amazon S3 and S3-compatible object store.

Uploads use a presigned PUT whose signature covers `Content-Length`, `Content-Type`, `If-None-Match: *` and
the SSE-KMS headers. S3 recomputes the signature from the headers it receives, so a body of any other
length, a different type, a different key, an overwrite of an existing object or an upload without the KMS
key all fail with 403 or 412 before a byte is stored.

A presigned POST with a `content-length-range` condition was the alternative. It was not chosen because
(1) it enforces a range where the signed PUT enforces the exact declared size, (2) its safety depends on a
hand-written policy document, where a missing `key` condition or a `starts-with` lets the client pick the
key, and (3) it is a multipart form, where Azure Blob and the local store use a plain PUT, so the console
uploads the same way to every backend.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from botocore.exceptions import ClientError

from ops_files.storage.base import (
    ObjectExistsError,
    ObjectInfo,
    ObjectLockedError,
    ObjectNotFoundError,
    PresignedRequest,
    RetentionMode,
    RetentionShortenError,
    StorageBackend,
    check_expiry,
    check_retention_change,
    content_disposition,
    validate_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

# SigV4 presigned URLs are capped at seven days by S3.
S3_MAX_URL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class S3Config:
    bucket: str
    # KMS key id, ARN or alias ("alias/ops-files"). None leaves encryption to the bucket default, which is
    # acceptable only for the local stack; production settings always name a key.
    kms_key_id: str | None = None
    max_url_seconds: int = 3600

    def __post_init__(self) -> None:
        if not 0 < self.max_url_seconds <= S3_MAX_URL_SECONDS:
            raise ValueError(f"max_url_seconds must be between 1 and {S3_MAX_URL_SECONDS}")


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


_NOT_FOUND = {"404", "NoSuchKey", "NotFound"}
_LOCKED = {"AccessDenied", "InvalidRequest", "ObjectLocked"}


class S3ObjectStore:
    def __init__(self, client: S3Client, config: S3Config) -> None:
        self._s3 = client
        self._config = config

    @property
    def backend(self) -> StorageBackend:
        return "s3"

    @property
    def container(self) -> str:
        return self._config.bucket

    @property
    def max_url_seconds(self) -> int:
        return self._config.max_url_seconds

    def _sse(self) -> dict[str, str]:
        if self._config.kms_key_id is None:
            return {}
        return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self._config.kms_key_id}

    def presign_put(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedRequest:
        validate_key(key)
        check_expiry(expires_in, self._config.max_url_seconds)
        params: dict[str, Any] = {
            "Bucket": self._config.bucket,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": max_bytes,
            "IfNoneMatch": "*",
            **self._sse(),
        }
        url = self._s3.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT")
        headers = {"Content-Type": content_type, "Content-Length": str(max_bytes), "If-None-Match": "*"}
        if self._config.kms_key_id is not None:
            headers["x-amz-server-side-encryption"] = "aws:kms"
            headers["x-amz-server-side-encryption-aws-kms-key-id"] = self._config.kms_key_id
        return PresignedRequest(
            url=url, method="PUT", headers=headers, expires_at=datetime.now(UTC) + timedelta(seconds=expires_in)
        )

    def presign_get(self, key: str, *, expires_in: int, filename: str) -> str:
        validate_key(key)
        check_expiry(expires_in, self._config.max_url_seconds)
        params = {
            "Bucket": self._config.bucket,
            "Key": key,
            "ResponseContentDisposition": content_disposition(filename),
        }
        return self._s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)

    def head(self, key: str) -> ObjectInfo | None:
        validate_key(key)
        try:
            out = self._s3.head_object(Bucket=self._config.bucket, Key=key)
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                return None
            raise
        mode = out.get("ObjectLockMode")
        return ObjectInfo(
            key=key,
            size=out["ContentLength"],
            content_type=out.get("ContentType", "application/octet-stream"),
            version_id=out.get("VersionId"),
            retention_until=out.get("ObjectLockRetainUntilDate"),
            retention_mode=cast(RetentionMode, mode.lower()) if mode else None,
            legal_hold=out.get("ObjectLockLegalHoldStatus") == "ON",
            metadata=out.get("Metadata", {}),
        )

    def iter_bytes(self, key: str, *, chunk_size: int = 1 << 20) -> Iterator[bytes]:
        validate_key(key)
        try:
            body = self._s3.get_object(Bucket=self._config.bucket, Key=key)["Body"]
        except ClientError as error:
            if _code(error) in _NOT_FOUND:
                raise ObjectNotFoundError(key) from error
            raise
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

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
        # In a versioned bucket a plain delete only adds a delete marker and the bytes stay; remove every
        # version of this exact key so a delete means the content is gone.
        paginator = self._s3.get_paginator("list_object_versions")
        try:
            for page in paginator.paginate(Bucket=self._config.bucket, Prefix=key):
                entries = [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
                for entry in entries:
                    if entry.get("Key") != key:
                        continue
                    self._s3.delete_object(
                        Bucket=self._config.bucket, Key=key, VersionId=entry.get("VersionId", "null")
                    )
        except ClientError as error:
            if _code(error) in _LOCKED:
                raise ObjectLockedError(f"{key}: {_code(error)}") from error
            raise

    def set_retention(self, key: str, until: datetime, mode: RetentionMode) -> None:
        info = self._require(key)
        check_retention_change(info.retention_until, info.retention_mode, until, mode)
        try:
            self._s3.put_object_retention(
                Bucket=self._config.bucket,
                Key=key,
                Retention={"Mode": "COMPLIANCE" if mode == "compliance" else "GOVERNANCE", "RetainUntilDate": until},
            )
        except ClientError as error:
            if _code(error) in _LOCKED:
                raise RetentionShortenError(f"{key}: {_code(error)}") from error
            raise

    def set_legal_hold(self, key: str, on: bool) -> None:
        self._require(key)
        self._s3.put_object_legal_hold(Bucket=self._config.bucket, Key=key, LegalHold={"Status": "ON" if on else "OFF"})

    def copy(self, src: str, dst: str) -> None:
        self._require(src)
        validate_key(dst)
        if self.head(dst) is not None:
            raise ObjectExistsError(dst)
        extra = self._sse()
        self._s3.copy_object(
            Bucket=self._config.bucket,
            Key=dst,
            CopySource={"Bucket": self._config.bucket, "Key": src},
            MetadataDirective="COPY",
            **extra,  # type: ignore[arg-type]
        )
