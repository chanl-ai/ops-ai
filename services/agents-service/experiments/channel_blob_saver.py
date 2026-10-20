"""Experiment only (not adopted; see docs/services/agents-service/experiments/checkpoint-per-version.md).

A variant of AsyncpgSaver that stores each channel's value once per version, the way LangGraph's PostgreSQL saver
does, instead of every channel in every checkpoint.

A checkpoint row keeps its channel versions but no values; `ops_checkpoint_blobs` holds one row per (thread,
namespace, channel, version), written only for the channels a step changed (`new_versions`). A read joins the two
back. A channel that does not change, such as an email's attachments, is stored once per thread instead of once per
step. Blobs are written before their checkpoint, so a crash between the two leaves an unreferenced blob, never a
checkpoint without its values.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_metadata,
    get_serializable_checkpoint_metadata,
)

from ops_checkpointer import AsyncpgSaver

# The table and its tenant policy, as a migration would create them; the experiment applies them to a scratch database.
BLOB_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS ops_checkpoint_blobs (
        tenant_id text NOT NULL,
        team_id text NOT NULL,
        thread_id text NOT NULL,
        checkpoint_ns text NOT NULL DEFAULT '',
        channel text NOT NULL,
        version text NOT NULL,
        type text NOT NULL,
        blob bytea,
        PRIMARY KEY (tenant_id, team_id, thread_id, checkpoint_ns, channel, version)
    )
    """,
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ops_checkpoint_blobs TO ops_runtime_tenant",
    "ALTER TABLE ops_checkpoint_blobs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE ops_checkpoint_blobs FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS ops_checkpoint_blobs_tenant ON ops_checkpoint_blobs",
    "CREATE POLICY ops_checkpoint_blobs_tenant ON ops_checkpoint_blobs"
    " USING (tenant_id = current_setting('app.tenant_id', true))"
    " WITH CHECK (tenant_id = current_setting('app.tenant_id', true))",
)

_EMPTY = "empty"


def _configurable(config: RunnableConfig) -> dict[str, Any]:
    return config.get("configurable") or {}


class ChannelBlobSaver(AsyncpgSaver):
    def for_scope(self, tenant_id: str, team_id: str) -> ChannelBlobSaver:
        return ChannelBlobSaver(self.pool, tenant_id=tenant_id, team_id=team_id, role=self.role, serde=self.serde)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        tenant, team = self._scope(config)
        c = _configurable(config)
        thread_id, ns = c["thread_id"], c.get("checkpoint_ns", "")
        values: dict[str, Any] = checkpoint["channel_values"]
        rows: list[tuple[Any, ...]] = []
        for channel, version in new_versions.items():
            type_, blob = self.serde.dumps_typed(values[channel]) if channel in values else (_EMPTY, None)
            rows.append((tenant, team, thread_id, ns, channel, str(version), type_, blob))
        stripped = cast(Checkpoint, {**checkpoint, "channel_values": {}})
        cp_type, cp_blob = self.serde.dumps_typed(stripped)
        md_type, md_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        md_json = json.dumps(get_serializable_checkpoint_metadata(config, metadata), default=str)
        # One transaction: the blobs first, then the checkpoint that names them.
        async with self._tx(tenant, (thread_id, c.get("lease_generation"))) as conn:
            if rows:
                await conn.executemany(
                    "INSERT INTO ops_checkpoint_blobs (tenant_id, team_id, thread_id, checkpoint_ns, channel, version,"
                    " type, blob) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING",
                    rows,
                )
            await conn.execute(
                "INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id,"
                " parent_checkpoint_id, type, checkpoint, metadata_type, metadata_blob, metadata)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)"
                " ON CONFLICT (tenant_id, team_id, thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET"
                " type = EXCLUDED.type, checkpoint = EXCLUDED.checkpoint, metadata_type = EXCLUDED.metadata_type,"
                " metadata_blob = EXCLUDED.metadata_blob, metadata = EXCLUDED.metadata",
                tenant,
                team,
                thread_id,
                ns,
                checkpoint["id"],
                c.get("checkpoint_id"),
                cp_type,
                cp_blob,
                md_type,
                md_blob,
                md_json,
            )
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ns, "checkpoint_id": checkpoint["id"]}}

    async def _with_values(self, t: CheckpointTuple | None) -> CheckpointTuple | None:
        if t is None:
            return None
        c = _configurable(t.config)
        versions: dict[str, Any] = dict(t.checkpoint["channel_versions"])
        if not versions:
            return t
        tenant, team = self._scope(t.config)
        async with self._tx(tenant) as conn:
            rows = await conn.fetch(
                "SELECT b.channel, b.type, b.blob FROM ops_checkpoint_blobs b"
                " JOIN unnest($5::text[], $6::text[]) AS v(channel, version)"
                " ON b.channel = v.channel AND b.version = v.version"
                " WHERE b.tenant_id = $1 AND b.team_id = $2 AND b.thread_id = $3 AND b.checkpoint_ns = $4",
                tenant,
                team,
                c["thread_id"],
                c.get("checkpoint_ns", ""),
                list(versions),
                [str(v) for v in versions.values()],
            )
        values = {r["channel"]: self.serde.loads_typed((r["type"], r["blob"])) for r in rows if r["type"] != _EMPTY}
        return t._replace(checkpoint={**t.checkpoint, "channel_values": values})

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._with_values(await super().aget_tuple(config))

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        async for t in super().alist(config, filter=filter, before=before, limit=limit):
            full = await self._with_values(t)
            assert full is not None
            yield full

    async def adelete_thread(self, thread_id: str) -> None:
        await super().adelete_thread(thread_id)
        async with self._tx(self.tenant_id) as conn:
            await conn.execute(
                "DELETE FROM ops_checkpoint_blobs WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3",
                self.tenant_id,
                self.team_id,
                thread_id,
            )

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        await super().acopy_thread(source_thread_id, target_thread_id)
        async with self._tx(self.tenant_id) as conn:
            await conn.execute(
                "INSERT INTO ops_checkpoint_blobs (tenant_id, team_id, thread_id, checkpoint_ns, channel, version,"
                " type, blob) SELECT tenant_id, team_id, $4, checkpoint_ns, channel, version, type, blob"
                " FROM ops_checkpoint_blobs WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3"
                " ON CONFLICT DO NOTHING",
                self.tenant_id,
                self.team_id,
                source_thread_id,
                target_thread_id,
            )

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        """After the checkpoints are pruned, drops every blob no remaining checkpoint names."""
        await super().aprune(thread_ids, strategy=strategy)
        for thread_id in thread_ids:
            keep: set[tuple[str, str, str]] = set()
            async for t in super().alist({"configurable": {"thread_id": thread_id}}):
                ns = _configurable(t.config).get("checkpoint_ns", "")
                keep.update((ns, ch, str(v)) for ch, v in t.checkpoint["channel_versions"].items())
            async with self._tx(self.tenant_id) as conn:
                rows = await conn.fetch(
                    "SELECT checkpoint_ns, channel, version FROM ops_checkpoint_blobs"
                    " WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3",
                    self.tenant_id,
                    self.team_id,
                    thread_id,
                )
                gone = [r for r in rows if (r["checkpoint_ns"], r["channel"], r["version"]) not in keep]
                await conn.executemany(
                    "DELETE FROM ops_checkpoint_blobs WHERE tenant_id = $1 AND team_id = $2 AND thread_id = $3"
                    " AND checkpoint_ns = $4 AND channel = $5 AND version = $6",
                    [
                        (self.tenant_id, self.team_id, thread_id, r["checkpoint_ns"], r["channel"], r["version"])
                        for r in gone
                    ],
                )
