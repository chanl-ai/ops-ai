"""Migration 0099 names the person who asked on reviews a service opened, by failure mode: a row written before keeps
"tools-service on behalf of <person>" as its requester, so Human Tasks still shows a service; the service that opened
it is lost instead of kept on the request; a request a person opened is touched."""

from __future__ import annotations

import asyncio
import json

from alembic import command
from alembic.config import Config

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0098_copies_record_digest"


def test_a_service_opened_review_names_the_person_and_keeps_the_service(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    tenant, seeded, own = new_id("ten"), new_id("pr"), new_id("pr")
    row = (
        "INSERT INTO registry_publish_requests (tenant_id, id, kind, subject_id, version, status, note, requested_by, "
        "created_at, body) VALUES (:t, :id, 'tool_module', 'mod_x', 1, 'pending', '', :by, :at, CAST(:b AS json))"
    )
    body = json.dumps({"moduleId": "mod_x"})
    asyncio.run(
        _sql(
            database_url,
            (
                row,
                {"t": tenant, "id": seeded, "by": "tools-service on behalf of Anika Singh", "at": now_iso(), "b": body},
            ),
            (row, {"t": tenant, "id": own, "by": "james@harborpine.example", "at": now_iso(), "b": body}),
        )
    )
    command.upgrade(cfg, "head")
    (rows,) = asyncio.run(
        _sql(
            database_url,
            (
                "SELECT id, requested_by, CAST(body AS text) FROM registry_publish_requests WHERE tenant_id = :t",
                {"t": tenant},
            ),
        )
    )
    got = {r[0]: (r[1], json.loads(r[2])) for r in rows}
    assert got[seeded] == ("Anika Singh", {"moduleId": "mod_x", "openedBy": "tools-service"}), got
    assert got[own] == ("james@harborpine.example", {"moduleId": "mod_x"}), got
