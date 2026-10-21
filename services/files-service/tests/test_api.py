# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's HTTP API in-process on the test database: one test per failure mode of the first slice."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import boto3
import httpx
import pytest
from azure.storage.blob import BlobServiceClient
from botocore.config import Config
from fastapi import FastAPI, Header, Request
from obstore.store import MemoryStore, S3Store

from ops_files.app import create_files_app
from ops_files.models import RetentionClass
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore
from ops_files.tenant_files import ScanningMode, TenantFiles
from ops_identity import Auth, Principal, dev_service_signer, mint_service_token
from ops_identity.fastapi import current_caller, current_principal
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_storage.azure_blob import AzureBlobConfig, AzureBlobObjectStore
from ops_storage.base import StreamingObjectStore
from ops_storage.local import LocalObjectStore
from ops_storage.s3 import S3Config, S3ObjectStore
from ops_store import isolation
from tests.conftest import AZURITE_KEY

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n"
OPS = {"X-Team-Id": "team_ops"}
SECURITY = {"X-Team-Id": "team_security"}
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
    def make(
        *,
        scanning: ScanningMode = "off",
        admin: bool = False,
        store: StreamingObjectStore | None = None,
        role: str | None = None,
    ) -> httpx.AsyncClient:
        files = TenantFiles(
            store or LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32),
            FilesStore(engine),
            CONFIG,
            scanning=scanning,
        )
        auth = Auth.for_dev(
            Settings(), audience="files", name="james", email="james@harborpine.example", tenant_id=tenant
        )
        app = create_files_app(files, engine=engine, auth=auth)

        sign_in(app, tenant, role or ("admin" if admin else "builder"))
        hooks = {"response": [response_checker(app)]}
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files", event_hooks=hooks)

    return make


def sign_in(app: FastAPI, tenant: str, role: str, email: str = "james@harborpine.example") -> None:
    """A person signed in with a real role in the team they act in (X-Team-Id, else team_ops), so `can()` decides as
    it does in a deployment (c-149); a request with a bearer token (a service) is resolved as usual."""

    async def as_person(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_caller(request, authorization=authorization)
        team = x_team_id or "team_ops"
        p = Principal(
            kind="person",
            sub="usr_dev",
            email=email,
            name=email.split("@", maxsplit=1)[0],
            tenant_id=tenant,
            team_id=team,
            team_ids=[team],
            roles={team: role},
            scopes=[],
            auth_method="session",
        )
        # The stand-in replaces ops_identity's dependency, so it enters the request's context as that one does.
        isolation.enter_caller(p, dev=False)
        return p

    async def as_person_only(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_principal(request, authorization=authorization)
        return await as_person(request, None, x_team_id)

    app.dependency_overrides[current_caller] = as_person
    app.dependency_overrides[current_principal] = as_person_only


def _data(r: httpx.Response) -> Any:
    return r.json()["data"]


async def _upload(
    c: httpx.AsyncClient, body: bytes = PDF, *, mime: str = "application/pdf", name: str = "s.pdf"
) -> Any:
    ticket = _data(
        await c.post(
            "/v1/files/uploads",
            json={"name": name, "size": len(body), "mime": mime, "purpose": "chat_attachment"},
            headers=OPS,
        )
    )
    put = await c.put(ticket["uploadUrl"], content=body, headers={**OPS, **ticket["headers"]})
    assert put.status_code == 204, put.text
    return ticket


async def test_upload_complete_get_download_delete_on_the_local_backend(client: Client) -> None:
    async with client() as c:
        ticket = await _upload(c)
        assert ticket["uploadUrl"] == f"http://files/v1/files/uploads/{ticket['fileId']}/content"
        done = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))
        assert done["deduplicated"] is False
        f = done["file"]
        assert f["digest"] == hashlib.sha256(PDF).hexdigest() and f["scan"]["status"] == "clean"
        assert f["retention"]["classId"] == "chat-90d" and f["sensitivity"] == "confidential"
        assert _data(await c.get(f"/v1/files/{f['id']}", headers=OPS))["versionCount"] == 1
        mine = _data(await c.get("/v1/files", params={"uploadedBy": "me"}, headers=OPS))
        assert [row["id"] for row in mine["data"]] == [f["id"]]
        link = _data(await c.post(f"/v1/files/{f['id']}/download-url", headers=OPS))
        got = await c.get(link["url"], headers=OPS)
        assert got.status_code == 200 and got.content == PDF and "attachment" in got.headers["content-disposition"]
        assert (await c.delete(f"/v1/files/{f['id']}", headers=OPS)).status_code == 204
        assert (await c.get(f"/v1/files/{f['id']}", headers=OPS)).status_code == 404


async def test_the_same_bytes_complete_as_the_first_file(client: Client) -> None:
    async with client() as c:
        first = await _upload(c)
        one = _data(await c.post(f"/v1/files/uploads/{first['fileId']}/complete", headers=OPS))
        second = await _upload(c, name="again.pdf")
        two = _data(await c.post(f"/v1/files/uploads/{second['fileId']}/complete", headers=OPS))
        assert two["deduplicated"] is True and two["file"]["id"] == one["file"]["id"]
        assert (await c.get(f"/v1/files/{second['fileId']}", headers=OPS)).status_code == 404


async def test_another_teams_file_is_missing_on_every_route(client: Client) -> None:
    async with client() as c:
        ticket = await _upload(c)
        file_id = ticket["fileId"]
        refused = [
            await c.post(f"/v1/files/uploads/{file_id}/complete", headers=SECURITY),
            await c.put(f"/v1/files/uploads/{file_id}/content", content=PDF, headers=SECURITY),
        ]
        await c.post(f"/v1/files/uploads/{file_id}/complete", headers=OPS)
        refused += [
            await c.get(f"/v1/files/{file_id}", headers=SECURITY),
            await c.post(f"/v1/files/{file_id}/download-url", headers=SECURITY),
            await c.get(f"/v1/files/{file_id}/content", headers=SECURITY),
            await c.delete(f"/v1/files/{file_id}", headers=SECURITY),
        ]
        assert [r.status_code for r in refused] == [404] * 6
        assert _data(await c.get("/v1/files", headers=SECURITY))["pagination"]["total"] == 0
        assert (await c.get(f"/v1/files/{file_id}", headers=OPS)).status_code == 200


async def test_a_file_is_recorded_as_what_its_bytes_are_not_its_declared_type(client: Client) -> None:
    async with client() as c:
        ticket = await _upload(c, b"just some text, not a pdf at all\n")
        r = await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS)
        assert _data(r)["file"]["mime"] == "text/plain", r.text


async def test_a_proxy_body_longer_than_its_ticket_is_refused(client: Client) -> None:
    async with client() as c:
        ticket = _data(
            await c.post(
                "/v1/files/uploads",
                json={"name": "a.pdf", "size": 10, "mime": "application/pdf", "purpose": "export"},
                headers=OPS,
            )
        )
        r = await c.put(ticket["uploadUrl"], content=PDF, headers={**OPS, "Content-Type": "application/pdf"})
        assert r.status_code == 409


async def test_a_held_file_is_not_deleted_and_only_an_admin_holds(client: Client) -> None:
    async with client(admin=True) as admin, client() as member:
        ticket = await _upload(admin)
        file_id = _data(await admin.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        hold = {"ids": [file_id], "hold": True, "reason": "Litigation 2026-114"}
        assert (await member.post("/v1/files/legal-hold", json=hold, headers=OPS)).status_code == 403
        assert _data(await admin.post("/v1/files/legal-hold", json=hold, headers=OPS))["updated"] == [file_id]
        held = _data(await admin.get(f"/v1/files/{file_id}", headers=OPS))
        assert held["legalHold"]["reason"] == "Litigation 2026-114"
        assert (await admin.delete(f"/v1/files/{file_id}", headers=OPS)).status_code == 409
        release = {**hold, "hold": False, "reason": "Matter closed"}
        assert _data(await admin.post("/v1/files/legal-hold", json=release, headers=OPS))["updated"] == [file_id]
        assert (await admin.delete(f"/v1/files/{file_id}", headers=OPS)).status_code == 204


async def test_a_file_is_unreadable_until_the_scan_hook_says_clean(client: Client, tenant: str) -> None:
    token = mint_service_token(
        dev_service_signer(), service="scanner", audience="files", tenant_id=tenant, scopes=["files:decide"]
    )
    service = {"Authorization": f"Bearer {token}"}
    kb_token = mint_service_token(
        dev_service_signer(),
        service="kb",
        audience="files",
        tenant_id=tenant,
        scopes=["files:edit"],
        team_id="team_ops",
    )
    kb_edit = {"Authorization": f"Bearer {kb_token}"}
    async with client(scanning="hook") as c:
        ticket = await _upload(c)
        f = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]
        assert f["scan"]["status"] == "pending"
        assert (await c.post(f"/v1/files/{f['id']}/download-url", headers=OPS)).status_code == 423
        attach = {"type": "chat", "refId": "msg_1", "name": "Chat message"}
        assert (await c.post(f"/v1/files/{f['id']}/references", json=attach, headers=kb_edit)).status_code == 409
        verdict = {"fileId": f["id"], "status": "clean", "engine": "clamav"}
        # kb holds a key for files, but only the scanner holds files:decide; asking for it is refused outright.
        kb = mint_service_token(dev_service_signer(), service="kb", audience="files", tenant_id=tenant)
        kb_claims = mint_service_token(
            dev_service_signer(), service="kb", audience="files", tenant_id=tenant, scopes=["files:decide"]
        )
        refused = await c.post("/v1/files/scan-results", json=verdict, headers={"Authorization": f"Bearer {kb}"})
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "scope_required"
        forged = {"Authorization": f"Bearer {kb_claims}"}
        assert (await c.post("/v1/files/scan-results", json=verdict, headers=forged)).status_code == 401
        assert (await c.post(f"/v1/files/{f['id']}/download-url", headers=OPS)).status_code == 423
        assert _data(await c.post("/v1/files/scan-results", json=verdict, headers=service))["scan"]["status"] == "clean"
        assert (await c.post(f"/v1/files/{f['id']}/download-url", headers=OPS)).status_code == 200
        # The scanner records verdicts and nothing else: attaching needs files:edit.
        scanner_attach = await c.post(f"/v1/files/{f['id']}/references", json=attach, headers=service)
        assert scanner_attach.status_code == 403, scanner_attach.text
        attached = await c.post(f"/v1/files/{f['id']}/references", json=attach, headers=kb_edit)
        assert _data(attached)["referenceCount"] == 1
        assert (await c.delete(f"/v1/files/{f['id']}", headers=OPS)).status_code == 409


def _kb(tenant: str, team: str, scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="kb", audience="files", tenant_id=tenant, scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_service_writes_and_reads_a_file_for_the_team_its_token_names(client: Client, tenant: str) -> None:
    service = {**_kb(tenant, "team_ops", ["files:create", "files:view"]), "Content-Type": "application/pdf"}
    # A team in the query is not read: the token's team decides (c-168).
    params = {"team": "team_security", "name": "mail.pdf", "purpose": "case_attachment", "uploadedBy": "mailbox"}
    async with client() as c:
        done = _data(await c.post("/v1/files", params=params, content=PDF, headers=service))
        file_id = done["file"]["id"]
        got = await c.get(f"/v1/files/{file_id}/content", headers=service)
        assert got.content == PDF
        other = await c.get(f"/v1/files/{file_id}", headers=_kb(tenant, "team_security", ["files:view"]))
        assert other.status_code == 404
        unscoped = await c.get(f"/v1/files/{file_id}", headers=_kb(tenant, "team_ops", ["files:create"]))
        assert unscoped.status_code == 403 and unscoped.json()["error"]["code"] == "scope_required"
        # A service reaches only the routes that take service tokens.
        listing = await c.get("/v1/files", headers=service)
        assert listing.status_code == 403


# ── signed grants on the cloud backends; bytes still move through obstore inside the adapter ──


async def test_s3_uploads_get_a_presigned_put_and_complete_through_obstore(
    client: Client, moto_endpoint: str, tenant: str
) -> None:
    s3 = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=moto_endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"ops-api-{tenant.replace('_', '-')}"
    s3.create_bucket(Bucket=bucket)
    byte_store = S3Store(
        bucket,
        config={
            "endpoint": moto_endpoint,
            "region": "us-east-1",
            "access_key_id": "test",
            "secret_access_key": "test",
            "virtual_hosted_style_request": False,
        },
        client_options={"allow_http": True},
    )
    store = S3ObjectStore(s3, S3Config(bucket=bucket), byte_store=byte_store)
    async with client(store=store) as c:
        ticket = _data(
            await c.post(
                "/v1/files/uploads",
                json={"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "export"},
                headers=OPS,
            )
        )
        assert ticket["uploadUrl"].startswith(f"{moto_endpoint}/{bucket}/") and "X-Amz-Signature" in ticket["uploadUrl"]
        headers = {k: v for k, v in ticket["headers"].items() if k.lower() != "content-length"}
        assert httpx.put(ticket["uploadUrl"], content=PDF, headers=headers).status_code == 200
        done = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))
        assert done["file"]["digest"] == hashlib.sha256(PDF).hexdigest()
        link = _data(await c.post(f"/v1/files/{done['file']['id']}/download-url", headers=OPS))
        assert link["url"].startswith(moto_endpoint) and httpx.get(link["url"]).content == PDF


async def test_azure_uploads_get_a_create_only_sas(client: Client) -> None:
    service = BlobServiceClient(
        account_url="http://127.0.0.1:10000/devstoreaccount1",
        credential={"account_name": "devstoreaccount1", "account_key": AZURITE_KEY},
    )
    config = AzureBlobConfig(container="files", allow_account_key_sas=True)
    store = AzureBlobObjectStore(service, config, account_key=AZURITE_KEY, byte_store=MemoryStore())
    async with client(store=store) as c:
        ticket = _data(
            await c.post(
                "/v1/files/uploads",
                json={"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "export"},
                headers=OPS,
            )
        )
        assert ticket["uploadUrl"].startswith("http://127.0.0.1:10000/devstoreaccount1/files/")
        assert "sp=c&" in ticket["uploadUrl"] and ticket["headers"]["If-None-Match"] == "*"
        # The proxy route is closed when browsers upload to storage directly.
        r = await c.put(
            f"/v1/files/uploads/{ticket['fileId']}/content",
            content=PDF,
            headers={**OPS, "Content-Type": "application/pdf"},
        )
        assert r.status_code == 409


async def test_a_storage_level_hold_refuses_a_delete_the_service_let_through(client: Client, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32)
    async with client(store=store, admin=True) as c:
        ticket = await _upload(c)
        file_id = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        got = await c.get(f"/v1/files/{file_id}", headers=OPS)
        assert got.status_code == 200, got.text
        key = _data(got)["storage"]["key"]
        store.set_legal_hold(key, True)  # set by a storage administrator, not through the service
        r = await c.delete(f"/v1/files/{file_id}", headers=OPS)
        assert r.status_code == 409 and r.json()["error"]["code"] == "locked_in_storage"


async def test_two_completes_of_one_ticket_keep_the_file(client: Client) -> None:
    async with client() as c:
        ticket = await _upload(c)
        url = f"/v1/files/uploads/{ticket['fileId']}/complete"
        first, second = await asyncio.gather(c.post(url, headers=OPS), c.post(url, headers=OPS))
        assert [first.status_code, second.status_code] == [200, 200], (first.text, second.text)
        assert {_data(first)["file"]["id"], _data(second)["file"]["id"]} == {ticket["fileId"]}
        assert not _data(first)["deduplicated"] and not _data(second)["deduplicated"]
        assert (await c.get(f"/v1/files/{ticket['fileId']}", headers=OPS)).status_code == 200
        got = await c.get(f"/v1/files/{ticket['fileId']}/content", headers=OPS)
        assert got.content == PDF


async def test_the_storage_location_is_shown_to_the_teams_admins_only(client: Client) -> None:
    async with client(admin=True) as admin, client() as member:
        ticket = await _upload(member)
        file_id = _data(await member.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        assert _data(await member.get(f"/v1/files/{file_id}", headers=OPS)).get("storage") is None
        assert all(row.get("storage") is None for row in _data(await member.get("/v1/files", headers=OPS))["data"])
        assert _data(await admin.get(f"/v1/files/{file_id}", headers=OPS))["storage"]["key"].endswith(file_id)


async def test_a_retried_upload_with_one_idempotency_key_is_one_file(client: Client, tenant: str) -> None:
    body = {"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "export"}
    keyed = {**OPS, "Idempotency-Key": "upload-7f3a"}
    async with client() as c:
        first, second = await asyncio.gather(
            c.post("/v1/files/uploads", json=body, headers=keyed), c.post("/v1/files/uploads", json=body, headers=keyed)
        )
        assert _data(first)["fileId"] == _data(second)["fileId"]
        other = await c.post("/v1/files/uploads", json={**body, "name": "other.pdf"}, headers=keyed)
        assert other.status_code == 409
        assert _data(await c.post("/v1/files/uploads", json=body, headers=OPS))["fileId"] != _data(first)["fileId"]

        service = {
            **_kb(tenant, "team_ops", ["files:create"]),
            "Content-Type": "application/pdf",
            "Idempotency-Key": "mail-1",
        }
        params = {"name": "mail.pdf", "purpose": "case_attachment", "uploadedBy": "mailbox"}
        one = _data(await c.post("/v1/files", params=params, content=PDF, headers=service))
        again = _data(await c.post("/v1/files", params=params, content=PDF, headers=service))
        assert again["file"]["id"] == one["file"]["id"] and again["deduplicated"] is False


async def test_the_detail_says_who_may_delete_and_a_chat_only_member_cannot(client: Client) -> None:
    """c-216: a chat-only member reads a team file but neither sees Delete nor deletes it; a builder does both."""
    async with client() as builder:
        ticket = await _upload(builder)
        f = _data(await builder.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]
        mine = _data(await builder.get(f"/v1/files/{f['id']}", headers=OPS))
    assert (mine["canEdit"], mine["canDelete"], mine["canPublish"]) == (False, True, False)
    async with client(role="chat_user") as chatter:
        seen = _data(await chatter.get(f"/v1/files/{f['id']}", headers=OPS))
        refused = await chatter.delete(f"/v1/files/{f['id']}", headers=OPS)
    assert seen["canDelete"] is False
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "role_required"), refused.text
