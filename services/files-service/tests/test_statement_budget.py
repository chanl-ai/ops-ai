# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Every GET route of files-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its files, a route over its row, and a route that opens a second
transaction or checks out a second connection. The routes that move bytes are not GETs; they keep a transaction per
store call, so none is open while storage works (tests/test_request_transactions.py holds the download to that)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ops_files.app import create_files_app, storage_admin
from ops_files.secrets import CredentialCipher
from ops_files.settings import StorageSettings, build_store
from ops_files.store import FilesStore, SettingsStore, engine_for
from ops_files.tenant_files import TenantFiles, Who
from ops_identity import Auth, CurrentPrincipal
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check
from ops_storage.local import LocalObjectStore

from .test_api import CONFIG, OPS, PDF, sign_in

BUDGETS = Path(__file__).parents[1] / "budgets.toml"

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
async def app(database_url: str, tenant: str, tmp_path: Path) -> AsyncIterator[FastAPI]:
    # The service's own engine, whose statements and transactions the request line counts.
    engine = engine_for(database_url)
    default = LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32)
    storage = StorageSettings(
        SettingsStore(engine),
        CredentialCipher("ab" * 32),
        build_store(tmp_path, b"k" * 32),
        CONFIG,
        default_store=default,  # pyright: ignore[reportArgumentType]
        default_proxy=True,
        scanning="off",
    )
    files = TenantFiles(default, FilesStore(engine), CONFIG, scanning="off", settings=storage)  # pyright: ignore[reportArgumentType]
    auth = Auth.for_dev(Settings(), audience="files", name="sam", email="sam@harborpine.example", tenant_id=tenant)
    built = create_files_app(files, engine=engine, auth=auth, settings=storage)
    # An admin of team_ops for the files routes, and the Security admin storage settings need.
    sign_in(built, tenant, "admin", "sam@harborpine.example")

    async def security_admin(p: CurrentPrincipal) -> Who:
        return Who(tenant_id=p.tenant_id, team="team_security", actor=p.email or p.sub)

    built.dependency_overrides[storage_admin] = security_admin
    yield built
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://files", event_hooks=hooks) as http:
        yield http


@pytest.fixture
def seed_team(client: httpx.AsyncClient) -> SeedTeam:
    """`n` more files of team_ops, each with its own bytes so none is deduplicated, `n` more storage credentials and
    watched folders, and one read request on the first file."""
    first: dict[str, str] = {}

    async def seed(n: int) -> Seeded:
        for i in range(n):
            body = PDF + uuid.uuid4().hex.encode()
            ask = {"name": f"statement-{n}-{i}.pdf", "size": len(body), "mime": "application/pdf"}
            ticket = await client.post("/v1/files/uploads", json={**ask, "purpose": "chat_attachment"}, headers=OPS)
            ticket.raise_for_status()
            t = ticket.json()["data"]
            put = await client.put(t["uploadUrl"], content=body, headers={**OPS, **t["headers"]})
            assert put.status_code == 204, put.text
            done = await client.post(f"/v1/files/uploads/{t['fileId']}/complete", headers=OPS)
            assert done.status_code == 200, done.text
            first.setdefault("file_id", t["fileId"])
            values = {"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": uuid.uuid4().hex}
            credential = {"kind": "aws_access_key", "values": values}
            put = await client.put(f"/v1/settings/storage/credentials/BANK_{n}_{i}", json=credential, headers=OPS)
            assert put.status_code == 200, put.text
            watch = {
                "name": f"Folder {n}-{i}",
                "plugin": "sharepoint",
                "source": "files",
                "values": {"libraries": ["L"]},
            }
            made = await client.post("/v1/watches", json=watch, headers=OPS)
            assert made.status_code == 201, made.text
            first.setdefault("watch_id", made.json()["data"]["id"])
        if "key" not in first:
            ask = {"documentTypeId": "restraining_notice", "typeName": "Restraining notice"}
            asked = await client.post(f"/v1/files/{first['file_id']}/read-requests", json=ask, headers=OPS)
            assert asked.status_code == 202, asked.text
            first["key"] = asked.json()["data"]["key"]
        return Seeded(headers=OPS, ids=dict(first))

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
