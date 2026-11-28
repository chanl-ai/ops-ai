"""The replay record: the provider's final answer for a request under a replay key, so a re-run after a crash is
answered without calling the provider or paying again. The one table holding completion text: tenant scoped, run as
ROLE in the tenant, kept until `expires_at` or until the run that made it deletes its prefix, and never listed."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import sqlalchemy as sa

from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import model_replays as t


class Replays(Store):
    role = ROLE
    # Two servers finishing the same request write one row (insert_ignore); the row lands with the call's spend.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    async def find(self, tenant_id: str, replay_key: str, request_hash: str, now: datetime) -> str | None:
        """The recorded answer's JSON, or None when there is none or it expired."""
        q = sa.select(t.c.response).where(
            t.c.tenant_id == tenant_id,
            t.c.replay_key == replay_key,
            t.c.request_hash == request_hash,
            t.c.expires_at > now,
        )
        async with self.tx() as c:
            found = await c.scalar(q)
        return None if found is None else str(found)

    async def record(
        self, tenant_id: str, replay_key: str, request_hash: str, *, response: str, call_id: str, expires_at: datetime
    ) -> None:
        """Writes the answer in the open transaction unless the same request under the key has one."""
        row = {
            "tenant_id": tenant_id,
            "replay_key": replay_key,
            "request_hash": request_hash,
            "response": response,
            "call_id": call_id,
            "expires_at": expires_at,
        }
        async with self.tx() as c:
            await c.execute(insert_ignore(c, t, row, keys=["tenant_id", "replay_key", "request_hash"]))

    async def delete_prefix(self, tenant_id: str, prefix: str) -> int:
        """Deletes the tenant's records whose key starts with `prefix`, its `%` and `_` matched as themselves."""
        gone = t.delete().where(t.c.tenant_id == tenant_id, t.c.replay_key.startswith(prefix, autoescape=True))
        async with self.tx() as c:
            return int((await c.execute(gone)).rowcount)
