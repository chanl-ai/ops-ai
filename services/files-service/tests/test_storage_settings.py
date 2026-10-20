# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Storage settings (c-100), one test per failure mode: a credential's value returned or stored in the clear; someone
other than a Security admin seeing or changing storage; two admins overwriting each other; a target that fails its
test saved anyway, or the saved version changed by the failed save; uploads ignoring the saved target and limits, or
files stored earlier becoming unreadable; a target that still holds files dropped."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
import sqlalchemy as sa
from fastapi import Request

from ops_files.app import create_files_app, storage_admin, who
from ops_files.models import RetentionClass
from ops_files.secrets import CredentialCipher
from ops_files.service import FilesConfig
from ops_files.settings import StorageSettings, build_store
from ops_files.store import AsyncEngine, FilesStore, SettingsStore
from ops_files.store.settings import storage_credentials, storage_settings_audit
from ops_files.tenant_files import TenantFiles, Who
from ops_identity import Auth, CurrentCaller, CurrentPrincipal
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_storage.local import LocalObjectStore
from tests.test_api import sign_in

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n"
OPS = {"X-Team-Id": "team_ops"}
SECRET = "wJalrXUtnFEMI-not-a-real-key-" + uuid.uuid4().hex
KEY = "ab" * 32
CONFIG = FilesConfig(
    retention_classes=(
        RetentionClass(id="standard", name="Standard", days=None),
        RetentionClass(id="chat-90d", name="Chat attachment, 90 days", days=90, purposes=["chat_attachment"]),
    ),
    default_retention_class="standard",
)

Client = Callable[..., httpx.AsyncClient]


@pytest.fixture
def client(engine: AsyncEngine, tenant: str, tmp_path: Path) -> Client:
    default = LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32)
    storage = StorageSettings(
        SettingsStore(engine),
        CredentialCipher(KEY),
        build_store(tmp_path, b"k" * 32),
        CONFIG,
        default_store=default,  # pyright: ignore[reportArgumentType]
        default_proxy=True,
        scanning="off",
    )

    def make(*, admin: bool = True) -> httpx.AsyncClient:
        files = TenantFiles(default, FilesStore(engine), CONFIG, scanning="off", settings=storage)  # pyright: ignore[reportArgumentType]
        auth = Auth.for_dev(Settings(), audience="files", name="sam", email="sam@northfieldbank.com", tenant_id=tenant)
        app = create_files_app(files, engine=engine, auth=auth, settings=storage)
        if not admin:
            # A builder of team_ops: no Security admin, so `can()` refuses storage settings (c-149).
            sign_in(app, tenant, "builder", "sam@northfieldbank.com")
        if admin:
            # What a platform token with admin on team_security resolves to; dev sign-in carries no roles.
            async def as_admin(p: CurrentPrincipal) -> Who:
                return Who(tenant_id=p.tenant_id, team="team_security", actor=p.email or p.sub)

            app.dependency_overrides[storage_admin] = as_admin

            async def as_team_admin(p: CurrentCaller, request: Request) -> Who:
                base = await who(p, request)
                return Who(
                    tenant_id=base.tenant_id, team=base.team, actor=base.actor, admin_teams=frozenset({base.team})
                )

            app.dependency_overrides[who] = as_team_admin
        hooks = {"response": [response_checker(app)]}
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files", event_hooks=hooks)

    return make


def _data(r: httpx.Response) -> Any:
    assert r.status_code < 300, r.text
    return r.json()["data"]


async def _upload(
    c: httpx.AsyncClient, body: bytes = PDF, *, name: str = "s.pdf", mime: str = "application/pdf"
) -> httpx.Response:
    r = await c.post(
        "/v1/files/uploads",
        json={"name": name, "size": len(body), "mime": mime, "purpose": "chat_attachment"},
        headers=OPS,
    )
    if r.status_code != 201:
        return r
    ticket = r.json()["data"]
    put = await c.put(ticket["uploadUrl"], content=body, headers={**OPS, **ticket["headers"]})
    assert put.status_code == 204, put.text
    return await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS)


def _doc(*targets: dict[str, Any], limits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"targets": list(targets), "limits": limits or [], "retention": [], "downloadLinkSeconds": 300}


DEFAULT = {"purpose": "default", "backend": "local", "container": "local", "uploadPath": "proxy"}


async def test_a_credential_value_is_never_returned(client: Client, engine: AsyncEngine, tenant: str) -> None:
    async with client() as c:
        put = await c.put(
            "/v1/settings/storage/credentials/BANK_S3",
            json={"kind": "aws_access_key", "values": {"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": SECRET}},
        )
        listed = await c.get("/v1/settings/storage/credentials")
        view = await c.get("/v1/settings/storage")
    for r in (put, listed, view):
        assert r.status_code == 200 and SECRET not in r.text and "AKIAEXAMPLE" not in r.text, r.text
    assert [x["name"] for x in listed.json()["data"]] == ["BANK_S3"]
    async with engine.connect() as conn:
        sealed = (
            await conn.execute(sa.select(storage_credentials.c.sealed).where(storage_credentials.c.tenant_id == tenant))
        ).scalar_one()
        audit = [
            r[0]
            for r in await conn.execute(
                sa.select(storage_settings_audit.c.detail).where(storage_settings_audit.c.tenant_id == tenant)
            )
        ]
    assert SECRET not in sealed and audit and all(SECRET not in d for d in audit)
    assert CredentialCipher(KEY).open(tenant, "BANK_S3", sealed)["secretAccessKey"] == SECRET
    with pytest.raises(ValueError, match="does not decrypt"):
        CredentialCipher(KEY).open(tenant, "other-name", sealed)


async def test_only_a_security_admin_sees_or_changes_storage(client: Client) -> None:
    async with client(admin=False) as c:
        got = await c.get("/v1/settings/storage")
        saved = await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT)})
        cred = await c.put(
            "/v1/settings/storage/credentials/x",
            json={"kind": "aws_access_key", "values": {"accessKeyId": "a", "secretAccessKey": "b"}},
        )
    assert [got.status_code, saved.status_code, cred.status_code] == [403, 403, 403]


async def test_a_stale_version_is_refused(client: Client) -> None:
    async with client() as c:
        first = _data(await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT)}))
        again = await c.put(
            "/v1/settings/storage",
            json={
                "version": 0,
                "document": _doc(
                    DEFAULT, limits=[{"purpose": "chat_attachment", "allowedTypes": ["pdf"], "maxSizeMb": 5}]
                ),
            },
        )
        current = _data(await c.get("/v1/settings/storage"))
    assert first["version"] == 1 and again.status_code == 409 and again.json()["error"]["code"] == "stale_version"
    assert current["version"] == 1 and current["document"]["limits"] == []


async def test_a_failing_probe_leaves_the_saved_version_unchanged(client: Client) -> None:
    unreachable = {
        "purpose": "chat_attachment",
        "backend": "s3",
        "container": "bank-chat",
        "region": "us-east-1",
        "endpoint": "http://127.0.0.1:9",
        "credential": "BANK_S3",
        "uploadPath": "direct",
    }
    async with client() as c:
        await c.put(
            "/v1/settings/storage/credentials/BANK_S3",
            json={"kind": "aws_access_key", "values": {"accessKeyId": "a", "secretAccessKey": "b"}},
        )
        before = _data(await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT)}))
        refused = await c.put("/v1/settings/storage", json={"version": 1, "document": _doc(DEFAULT, unreachable)})
        after = _data(await c.get("/v1/settings/storage"))
    error = refused.json()["error"]
    assert (
        refused.status_code == 422
        and error["code"] == "target_test_failed"
        and error["details"]["purpose"] == "chat_attachment"
    )
    assert after["version"] == before["version"] == 1 and after["document"] == before["document"]


async def test_uploads_follow_the_saved_target_and_limits(client: Client, engine: AsyncEngine, tenant: str) -> None:
    chat = {"purpose": "chat_attachment", "backend": "local", "container": "chat-store", "uploadPath": "proxy"}
    async with client() as c:
        earlier = _data(await _upload(c, name="before.pdf"))["file"]
        _data(
            await c.put(
                "/v1/settings/storage",
                json={
                    "version": 0,
                    "document": _doc(
                        DEFAULT, chat, limits=[{"purpose": "chat_attachment", "allowedTypes": ["pdf"], "maxSizeMb": 1}]
                    ),
                },
            )
        )
        later = _data(await _upload(c, PDF + b"%later", name="after.pdf"))["file"]
        too_big = await _upload(c, PDF + b"x" * (1024 * 1024 + 1), name="big.pdf")
        wrong_type = await _upload(c, b"plain text", name="note.txt", mime="text/plain")
        reads: list[bytes] = []
        for f in (earlier, later):
            link = _data(await c.post(f"/v1/files/{f['id']}/download-url", headers=OPS))
            reads.append((await c.get(link["url"], headers=OPS)).content)
        dropped = await c.put("/v1/settings/storage", json={"version": 1, "document": _doc(DEFAULT)})
    assert earlier["storage"]["container"] == "local" and later["storage"]["container"] == "chat-store"
    assert too_big.status_code == 413 and wrong_type.status_code == 415
    assert reads == [PDF, PDF + b"%later"], "a file stored before the change stays readable where it is"
    assert dropped.status_code == 409 and dropped.json()["error"]["code"] == "target_in_use"


async def test_a_purposes_allowed_types_are_checked_against_the_bytes(client: Client) -> None:
    """c-234: a PDF sent as octet-stream under a bare name is taken and recorded as a PDF; a zip named .pdf and an
    executable declared as a PDF are refused with 415, which the mail trigger lists on the run and moves past."""
    zipped = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 64
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + b"\x00" * 64
    pdf_only = [{"purpose": "chat_attachment", "allowedTypes": ["pdf"], "maxSizeMb": 1}]
    async with client() as c:
        _data(await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT, limits=pdf_only)}))
        taken = _data(await _upload(c, name="scan", mime="application/octet-stream"))["file"]
        refused = [
            await _upload(c, zipped, name="notice.pdf", mime="application/zip"),
            await _upload(c, exe, name="notice.pdf", mime="application/pdf"),
        ]
    assert taken["mime"] == "application/pdf", taken
    assert [(r.status_code, r.json()["error"]["code"]) for r in refused] == [(415, "unsupported_media_type")] * 2


async def test_an_s3_target_passes_its_test_and_takes_uploads(client: Client, moto_endpoint: str) -> None:
    bucket = f"bank-{uuid.uuid4().hex[:8]}"
    s3_client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3", endpoint_url=moto_endpoint, region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b"
    )
    s3_client.create_bucket(Bucket=bucket)
    s3 = {
        "purpose": "chat_attachment",
        "backend": "s3",
        "container": bucket,
        "region": "us-east-1",
        "endpoint": moto_endpoint,
        "credential": "BANK_S3",
        "uploadPath": "proxy",
    }
    async with client() as c:
        await c.put(
            "/v1/settings/storage/credentials/BANK_S3",
            json={"kind": "aws_access_key", "values": {"accessKeyId": "a", "secretAccessKey": "b"}},
        )
        tested = _data(await c.post("/v1/settings/storage/test", json=s3))
        _data(await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT, s3)}))
        stored = _data(await _upload(c))["file"]
    assert tested["ok"] is True and [s["label"] for s in tested["steps"]] == ["Write", "Read", "Delete"]
    assert stored["storage"]["backend"] == "s3" and stored["storage"]["container"] == bucket


async def test_two_first_saves_at_once_are_one_save_and_one_409(engine: AsyncEngine, tenant: str) -> None:
    import asyncio  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from ops_files.store import StaleVersionError  # noqa: PLC0415

    store = SettingsStore(engine)

    async def first() -> object:
        try:
            return await store.save(tenant, base_version=0, document={}, by="sam", at=datetime.now(UTC), detail="first")
        except StaleVersionError as e:
            return e

    results = await asyncio.gather(first(), first(), first())
    assert sum(isinstance(r, StaleVersionError) for r in results) == 2, results
    saved = await store.get(tenant)
    assert saved is not None and saved.version == 1


async def test_an_old_style_credential_name_keeps_working_and_new_names_follow_the_rule(
    client: Client, engine: AsyncEngine, tenant: str, moto_endpoint: str
) -> None:
    from datetime import UTC, datetime  # noqa: PLC0415

    # A credential saved before the rule, as on the shared stack.
    sealed = CredentialCipher(KEY).seal(tenant, "bank-s3", {"accessKeyId": "a", "secretAccessKey": "b"})
    await SettingsStore(engine).put_credential(
        tenant, "bank-s3", kind="aws_access_key", sealed=sealed, by="sam", at=datetime.now(UTC)
    )
    bucket = f"old-{uuid.uuid4().hex[:8]}"
    s3_client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3", endpoint_url=moto_endpoint, region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b"
    )
    s3_client.create_bucket(Bucket=bucket)
    target = {
        "purpose": "chat_attachment",
        "backend": "s3",
        "container": bucket,
        "region": "us-east-1",
        "endpoint": moto_endpoint,
        "credential": "bank-s3",
        "uploadPath": "proxy",
    }
    values = {"kind": "aws_access_key", "values": {"accessKeyId": "a", "secretAccessKey": "b"}}
    async with client() as c:
        resolves = _data(await c.post("/v1/settings/storage/test", json=target))
        replaced = await c.put("/v1/settings/storage/credentials/bank-s3", json=values)
        new_lower = await c.put("/v1/settings/storage/credentials/new-one", json=values)
        new_upper = await c.put("/v1/settings/storage/credentials/NEW_ONE", json=values)
        deleted = await c.delete("/v1/settings/storage/credentials/bank-s3")
    assert resolves["ok"] is True, "a target naming the old-style credential still signs in"
    assert replaced.status_code == 200 and new_upper.status_code == 200
    assert new_lower.status_code == 400 and "capital letters" in new_lower.json()["error"]["message"]
    assert deleted.status_code == 204


async def test_a_probe_error_never_returns_the_sdks_text(client: Client) -> None:
    from ops_files.settings import (  # noqa: PLC0415
        AUTH_FAILED,
        NOT_FOUND,
        PERMISSION_DENIED,
        REFUSED,
        TIMED_OUT,
        UNREACHABLE,
        probe,
    )

    fixed = {AUTH_FAILED, NOT_FOUND, PERMISSION_DENIED, REFUSED, TIMED_OUT, UNREACHABLE}
    key_id = "AKIAFAKEKEYID9876"
    # Through the real SDK: the host names the fake key id, so a raw connect error would carry it.
    target = {
        "purpose": "chat_attachment",
        "backend": "s3",
        "container": "bank-chat",
        "region": "us-east-1",
        "endpoint": f"http://{key_id.lower()}.invalid:9",
        "credential": "BANK_S3",
        "uploadPath": "direct",
    }
    async with client() as c:
        await c.put(
            "/v1/settings/storage/credentials/BANK_S3",
            json={"kind": "aws_access_key", "values": {"accessKeyId": key_id, "secretAccessKey": "s3cr3t"}},
        )
        tested = await c.post("/v1/settings/storage/test", json=target)
        refused = await c.put("/v1/settings/storage", json={"version": 0, "document": _doc(DEFAULT, target)})
    for r in (tested, refused):
        assert key_id not in r.text and key_id.lower() not in r.text and ".invalid" not in r.text, r.text
    assert tested.json()["data"]["ok"] is False and all(
        s["detail"] in fixed or s["ok"] for s in tested.json()["data"]["steps"]
    )
    assert refused.status_code == 422 and all(
        s["detail"] in fixed or s["ok"] for s in refused.json()["error"]["details"]["steps"]
    )

    class Broken:
        async def put_stream(self, *_: object, **__: object) -> None:
            raise RuntimeError(
                f"InvalidAccessKeyId: The AWS Access Key Id {key_id} does not exist at https://s3.bank.internal"
            )

    result = await probe(Broken())  # pyright: ignore[reportArgumentType]
    assert result.steps[0].detail == REFUSED and key_id not in result.model_dump_json()
