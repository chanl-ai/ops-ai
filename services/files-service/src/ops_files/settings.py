# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Where each upload purpose stores its bytes, under which limits, and with which credential (c-100).

One document per tenant, saved by an admin on the Security team: a target per purpose (or the default target), each
naming its backend, bucket or container, region, credential and upload path; size and type limits per purpose; the
retention class each purpose takes. A save probes every new or changed target with its credential (write, read and
delete a small object) and is refused naming the purpose when the probe fails, so a wrong target never takes uploads.
Files keep the backend and container they were stored in; a save may not drop a target that still holds files.

Credentials are kept by name in `storage_credentials`, sealed with the service's secrets key; nothing here returns a
credential's value. Design: docs/services/files-service/overview.md; card c-100.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

import boto3
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient
from obstore.store import AzureStore, S3Store
from pydantic import Field, model_validator

from ops_files.models import FilePurpose, Model, PurposeLimit
from ops_files.secrets import FIELDS, CredentialCipher, CredentialKind
from ops_files.service import FilesConfig
from ops_files.store.settings import SavedSettings, SettingsStore
from ops_service_kit.logging import get_logger
from ops_storage.azure_blob import AzureBlobConfig, AzureBlobObjectStore
from ops_storage.base import StreamingObjectStore
from ops_storage.local import LocalObjectStore
from ops_storage.s3 import S3Config, S3ObjectStore

log = get_logger("ops_files.settings")
TargetPurpose = FilePurpose | Literal["default"]
BackendName = Literal["local", "s3", "azure_blob"]

PROBE_KEY = "ops-files-probe/{nonce}"
_CACHE_SECONDS = 5.0


class StorageTarget(Model):
    """Where one purpose's bytes go. `default` covers every purpose without its own target."""

    purpose: TargetPurpose
    backend: BackendName
    # Bucket (S3), container (Azure Blob) or folder name under the files directory (local).
    container: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    region: str = ""
    # S3-compatible endpoint (MinIO, LocalStack) or the Azure account URL; empty uses the provider's default.
    endpoint: str = ""
    # A storage credential's name; empty on local, required elsewhere.
    credential: str = ""
    # direct: the browser sends bytes to storage with a signed URL; proxy: through files-service (files Q1).
    upload_path: Literal["direct", "proxy"] = "direct"
    # KMS key alias (S3) or encryption scope (Azure Blob).
    encryption: str = ""

    @model_validator(mode="after")
    def _credential_needed(self) -> StorageTarget:
        if self.backend != "local" and not self.credential:
            raise ValueError(f"the {self.purpose} target needs a credential to sign in to {self.backend}")
        return self

    @property
    def location(self) -> tuple[str, str]:
        return (self.backend, self.container)


class PurposeRetention(Model):
    purpose: FilePurpose
    retention_class: str


class StorageDocument(Model):
    targets: list[StorageTarget] = Field(default_factory=list[StorageTarget])
    limits: list[PurposeLimit] = Field(default_factory=list[PurposeLimit])
    retention: list[PurposeRetention] = Field(default_factory=list[PurposeRetention])
    # How long a signed download link lasts, at most what the backends sign.
    download_link_seconds: int = Field(300, ge=30, le=3600)

    @model_validator(mode="after")
    def _one_each(self) -> StorageDocument:
        for what, keys in (
            ("target", [t.purpose for t in self.targets]),
            ("limit", [x.purpose for x in self.limits]),
            ("retention", [r.purpose for r in self.retention]),
        ):
            if len(set(keys)) != len(keys):
                raise ValueError(f"one {what} per purpose")
        if self.targets and not any(t.purpose == "default" for t in self.targets):
            raise ValueError("name a default target for the purposes without their own")
        return self

    def target_for(self, purpose: str) -> StorageTarget | None:
        return next((t for t in self.targets if t.purpose == purpose), None) or next(
            (t for t in self.targets if t.purpose == "default"), None
        )


class StorageSettingsView(Model):
    version: int
    updated_by: str | None
    updated_at: datetime | None
    document: StorageDocument
    # Scanning is a deployment setting (files-service-design Q4), shown and never changed here.
    scanning: str
    retention_classes: list[dict[str, Any]]


class StorageSettingsInput(Model):
    version: int = Field(ge=0)
    document: StorageDocument


class CredentialView(Model):
    name: str
    kind: CredentialKind
    set_by: str
    set_at: datetime


class CredentialInput(Model):
    kind: CredentialKind
    # The values the kind needs (FIELDS); write-only.
    values: dict[str, str]

    @model_validator(mode="after")
    def _complete(self) -> CredentialInput:
        missing = [f for f in FIELDS[self.kind] if not self.values.get(f, "").strip()]
        if missing:
            raise ValueError(f"{self.kind} needs {', '.join(missing)}")
        extra = sorted(set(self.values) - set(FIELDS[self.kind]))
        if extra:
            raise ValueError(f"{self.kind} does not take {', '.join(extra)}")
        return self


class ProbeStep(Model):
    label: str
    ok: bool
    detail: str


class ProbeResult(Model):
    ok: bool
    steps: list[ProbeStep]


class ProbeFailedError(Exception):
    def __init__(self, purpose: str, result: ProbeResult) -> None:
        failed = next((s for s in result.steps if not s.ok), None)
        reason = f"{failed.label}: {failed.detail}" if failed else "unknown"
        super().__init__(f"the {purpose} target failed its test: {reason}")
        self.purpose = purpose
        self.result = result


class TargetInUseError(Exception):
    pass


class UnknownCredentialError(Exception):
    pass


StoreFactory = Callable[[StorageTarget, dict[str, str] | None], StreamingObjectStore]


def build_store(files_dir: Any, signing_key: bytes) -> StoreFactory:
    """Builds the store a target names. S3 and Azure sign in with the named credential's values; the byte path's
    obstore store gets the same credential, so signing and streaming use one identity."""

    def make(target: StorageTarget, values: dict[str, str] | None) -> StreamingObjectStore:
        if target.backend == "local":
            return LocalObjectStore(
                files_dir / "containers" / target.container, signing_key=signing_key, container=target.container
            )  # pyright: ignore[reportReturnType]
        assert values is not None
        if target.backend == "s3":
            kwargs: dict[str, Any] = {
                "aws_access_key_id": values["accessKeyId"],
                "aws_secret_access_key": values["secretAccessKey"],
                "region_name": target.region or None,
            }
            if target.endpoint:
                kwargs["endpoint_url"] = target.endpoint
            client = boto3.client("s3", **kwargs)  # pyright: ignore[reportUnknownMemberType]
            store_config: dict[str, Any] = {
                "access_key_id": values["accessKeyId"],
                "secret_access_key": values["secretAccessKey"],
                "region": target.region or "us-east-1",
            }
            if target.endpoint:
                store_config.update(endpoint=target.endpoint, allow_http=target.endpoint.startswith("http://"))
            byte_store = S3Store(target.container, config=store_config)  # pyright: ignore[reportArgumentType]
            config = S3Config(
                bucket=target.container,
                kms_key_id=target.encryption or None,
                region=target.region or None,
                endpoint_url=target.endpoint or None,
            )
            return S3ObjectStore(client, config, byte_store=byte_store)  # pyright: ignore[reportReturnType]

        credential = ClientSecretCredential(values["tenantId"], values["clientId"], values["clientSecret"])
        if not target.endpoint:
            raise ValueError(f"the {target.purpose} target needs the storage account URL")
        service = BlobServiceClient(target.endpoint, credential=credential)
        byte_store = AzureStore(
            target.container,
            config={
                "account_name": str(service.account_name),
                "client_id": values["clientId"],
                "client_secret": values["clientSecret"],
                "tenant_id": values["tenantId"],
            },
        )  # pyright: ignore[reportArgumentType]
        return AzureBlobObjectStore(
            service,
            AzureBlobConfig(container=target.container, encryption_scope=target.encryption or None),
            byte_store=byte_store,
        )  # pyright: ignore[reportReturnType]

    return make


# What a failed probe says to the admin. A cloud SDK's own message can carry the endpoint, the key id or a signed URL,
# so it goes to this service's log only; the page and the API get one of these.
AUTH_FAILED = "Storage refused the credential: check the key and secret."
NOT_FOUND = "The bucket or container was not found."
PERMISSION_DENIED = "The credential may not write, read or delete here."
UNREACHABLE = "Storage could not be reached at that endpoint."
TIMED_OUT = "Storage did not answer in time."
REFUSED = "Storage refused the request."

_AUTH_CODES = {
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
    "InvalidClientTokenId",
    "ExpiredToken",
    "AuthenticationFailed",
}
_NOT_FOUND_CODES = {"NoSuchBucket", "ContainerNotFound", "NotFound", "404"}
_DENIED_CODES = {"AccessDenied", "AuthorizationFailure", "AuthorizationPermissionMismatch", "403"}


def failure(step: str, error: BaseException) -> str:
    """One of the fixed messages for a failed probe step; the raw error is logged here and never returned."""
    log.warning("storage_probe_failed", step=step, error_type=type(error).__name__, error=str(error))
    name = type(error).__name__
    code = ""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = str(cast(dict[str, Any], response).get("Error", {}).get("Code", ""))
    code = code or str(getattr(error, "error_code", "") or getattr(error, "status_code", "") or "")
    if isinstance(error, TimeoutError) or "Timeout" in name:
        return TIMED_OUT
    if code in _AUTH_CODES or name in ("UnauthenticatedError", "ClientAuthenticationError", "NoCredentialsError"):
        return AUTH_FAILED
    if code in _NOT_FOUND_CODES or name in ("NotFoundError", "ResourceNotFoundError"):
        return NOT_FOUND
    if code in _DENIED_CODES or name in ("PermissionDeniedError",):
        return PERMISSION_DENIED
    if isinstance(error, (ConnectionError, OSError)) or name in ("EndpointConnectionError", "ServiceRequestError"):
        return UNREACHABLE
    text = str(error).lower()
    if "connect" in text or "dns" in text or "resolve" in text:
        return UNREACHABLE
    return REFUSED


async def _one(chunk: bytes) -> AsyncIterator[bytes]:
    yield chunk


async def probe(store: StreamingObjectStore) -> ProbeResult:
    """Writes, reads back and deletes a small object: the three things uploads, downloads and deletes need."""
    key = PROBE_KEY.format(nonce=os.urandom(8).hex())
    body = b"ops-files probe"
    steps: list[ProbeStep] = []
    try:
        await store.put_stream(key, _one(body), content_type="text/plain")
        steps.append(ProbeStep(label="Write", ok=True, detail="wrote a test object"))
    except Exception as e:
        return ProbeResult(ok=False, steps=[ProbeStep(label="Write", ok=False, detail=failure("Write", e))])
    try:
        got = b"".join([c async for c in store.open_read(key)])
        steps.append(
            ProbeStep(label="Read", ok=got == body, detail="read it back" if got == body else "read different bytes")
        )
    except Exception as e:
        steps.append(ProbeStep(label="Read", ok=False, detail=failure("Read", e)))
    try:
        await asyncio.to_thread(store.delete, key)
        steps.append(ProbeStep(label="Delete", ok=True, detail="deleted it"))
    except Exception as e:
        steps.append(ProbeStep(label="Delete", ok=False, detail=failure("Delete", e)))
    return ProbeResult(ok=all(s.ok for s in steps), steps=steps)


@dataclass(frozen=True)
class Placement:
    store: StreamingObjectStore
    proxy: bool


class StorageSettings:
    """The tenant's saved document, read per request with a few seconds' cache, and the stores its targets name."""

    def __init__(
        self,
        store: SettingsStore,
        cipher: CredentialCipher,
        factory: StoreFactory,
        defaults: FilesConfig,
        *,
        default_store: StreamingObjectStore,
        default_proxy: bool,
        scanning: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._factory = factory
        self._defaults = defaults
        self._default = Placement(default_store, default_proxy)
        self._scanning = scanning
        self._clock = clock
        self._cache: dict[str, tuple[float, SavedSettings | None]] = {}
        self._stores: dict[tuple[str, str, str], StreamingObjectStore] = {}

    # ── reads ──

    async def saved(self, tenant: str) -> SavedSettings | None:
        hit = self._cache.get(tenant)
        if hit is not None and time.monotonic() - hit[0] < _CACHE_SECONDS:
            return hit[1]
        saved = await self._store.get()
        self._cache[tenant] = (time.monotonic(), saved)
        return saved

    async def document(self, tenant: str) -> StorageDocument:
        saved = await self.saved(tenant)
        if saved is not None:
            return StorageDocument.model_validate(saved.document)
        return StorageDocument(
            limits=list(self._defaults.limits), download_link_seconds=self._defaults.max_download_url_seconds
        )

    async def view(self, tenant: str) -> StorageSettingsView:
        saved = await self.saved(tenant)
        return StorageSettingsView(
            version=saved.version if saved else 0,
            updated_by=saved.updated_by if saved else None,
            updated_at=saved.updated_at if saved else None,
            document=await self.document(tenant),
            scanning=self._scanning,
            retention_classes=[{"id": r.id, "name": r.name, "days": r.days} for r in self._defaults.retention_classes],
        )

    async def config_for(self, tenant: str) -> FilesConfig:
        """The service's config with the tenant's limits and link lifetime."""
        doc = await self.document(tenant)
        return replace(
            self._defaults,
            limits=tuple(doc.limits),
            max_download_url_seconds=min(doc.download_link_seconds, self._default.store.max_url_seconds),
        )

    async def retention_for(self, tenant: str, purpose: str) -> str | None:
        return next((r.retention_class for r in (await self.document(tenant)).retention if r.purpose == purpose), None)

    async def _values(self, tenant: str, name: str) -> dict[str, str]:
        row = await self._store.credential(name)
        if row is None:
            raise UnknownCredentialError(f"no storage credential named {name}")
        return self._cipher.open(tenant, name, row.sealed)

    async def _built(self, tenant: str, target: StorageTarget) -> StreamingObjectStore:
        cache_key = (tenant, target.model_dump_json(), target.credential)
        if cache_key not in self._stores:
            values = await self._values(tenant, target.credential) if target.backend != "local" else None
            self._stores[cache_key] = self._factory(target, values)
        return self._stores[cache_key]

    async def for_upload(self, tenant: str, purpose: str) -> Placement:
        target = (await self.document(tenant)).target_for(purpose)
        if target is None:
            return self._default
        store = await self._built(tenant, target)
        return Placement(store, target.upload_path == "proxy" or target.backend == "local")

    async def located(self, tenant: str, backend: str, container: str) -> Placement:
        """The store a file was written to: the service default, or a target of the tenant's document."""
        if (backend, container) == (self._default.store.backend, self._default.store.container):
            return self._default
        target = next((t for t in (await self.document(tenant)).targets if t.location == (backend, container)), None)
        if target is None:
            raise TargetInUseError(f"no target for {backend}/{container}; a target holding files cannot be removed")
        return Placement(await self._built(tenant, target), target.upload_path == "proxy" or target.backend == "local")

    # ── writes ──

    async def test(self, tenant: str, target: StorageTarget) -> ProbeResult:
        try:
            store = self._factory(
                target, await self._values(tenant, target.credential) if target.backend != "local" else None
            )
        except Exception as e:
            return ProbeResult(ok=False, steps=[ProbeStep(label="Sign in", ok=False, detail=failure("Sign in", e))])
        return await probe(store)

    async def save(self, tenant: str, body: StorageSettingsInput, *, by: str) -> StorageSettingsView:
        before = await self.document(tenant)
        old = {t.purpose: t for t in before.targets}
        for target in body.document.targets:
            if target.backend != "local" and await self._store.credential(target.credential) is None:
                raise UnknownCredentialError(
                    f"the {target.purpose} target names {target.credential}, which is not a storage credential"
                )
            if old.get(target.purpose) != target:
                result = await self.test(tenant, target)
                if not result.ok:
                    raise ProbeFailedError(target.purpose, result)
        kept = {t.location for t in body.document.targets} | {
            (self._default.store.backend, self._default.store.container)
        }
        used = await self._store.locations_in_use()
        if stranded := sorted(used - kept):
            raise TargetInUseError(f"{stranded[0][0]}/{stranded[0][1]} still holds files; keep a target on it")
        saved = await self._store.save(
            base_version=body.version,
            document=body.document.model_dump(mode="json", by_alias=True),
            by=by,
            at=self._clock(),
            detail=_changes(before, body.document),
        )
        self._cache[tenant] = (time.monotonic(), saved)
        return await self.view(tenant)

    async def has_credential(self, tenant: str, name: str) -> bool:
        return await self._store.credential(name) is not None

    async def credentials(self, tenant: str) -> list[CredentialView]:
        rows = await self._store.credentials()
        return [
            CredentialView.model_validate({"name": r.name, "kind": r.kind, "setBy": r.set_by, "setAt": r.set_at})
            for r in rows
        ]

    async def set_credential(self, tenant: str, name: str, body: CredentialInput, *, by: str) -> CredentialView:
        sealed = self._cipher.seal(tenant, name, {k: v.strip() for k, v in body.values.items()})
        at = self._clock()
        await self._store.put_credential(name, kind=body.kind, sealed=sealed, by=by, at=at)
        # A store built with the old values signs with them until rebuilt.
        self._stores = {k: v for k, v in self._stores.items() if not (k[0] == tenant and k[2] == name)}
        return CredentialView(name=name, kind=body.kind, set_by=by, set_at=at)

    async def delete_credential(self, tenant: str, name: str, *, by: str) -> bool:
        if any(t.credential == name for t in (await self.document(tenant)).targets):
            raise TargetInUseError(f"a target signs in with {name}; change the target first")
        return await self._store.delete_credential(name, by=by, at=self._clock())


def _changes(before: StorageDocument, after: StorageDocument) -> str:
    """What a save changed, in words for the audit row; credentials appear by name only."""
    out: list[str] = []
    b, a = {t.purpose: t for t in before.targets}, {t.purpose: t for t in after.targets}
    for p in sorted(set(b) | set(a)):
        if p not in a:
            out.append(f"removed the {p} target")
        elif b.get(p) != a[p]:
            t = a[p]
            out.append(f"{p} target {t.backend}/{t.container} ({t.upload_path}, credential {t.credential or 'none'})")
    if before.limits != after.limits:
        out.append("limits changed")
    if before.retention != after.retention:
        out.append("retention changed")
    if before.download_link_seconds != after.download_link_seconds:
        out.append(f"download links {after.download_link_seconds}s")
    return "; ".join(out) or "no change"
