"""Embedding index units with the environment's one embedding model (settings.embedding_alias at embedding_width),
through models-service with kb-service's own key (`kb:index` spends there), so the meaning lane can compare a question
with each unit.

After a sync or rebuild settles, its tenant's units without a vector of the current model are embedded at once; a
background beat embeds whatever is left (a model that was down, a model or width changed, which embeds every unit
again and reads nothing again). Each batch is one request; a refusal stops the pass and the beat tries again."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ops_service_kit.logging import get_logger
from ops_service_kit.model_calls import ModelCallError, ModelCalls
from ops_store import background, isolation

from .store import KnowledgeStore
from .store.vectors import PgVectorStore

log = get_logger(__name__)

# Units per request: well inside models-service's 2,048 inputs, and small enough that one slow batch holds nothing up.
BATCH = 64
# Units one pass embeds for one tenant before giving the next tenant a turn.
PASS_LIMIT = 2_000
EMBED_STEP = "kb:index"
FIND_PENDING = "background process: the knowledge embedder reads each tenant's units that have no vector yet"


class Embedder(Protocol):
    """The environment's embedding model: its name and width, which every stored vector records."""

    model: str
    width: int

    async def embed(self, texts: list[str], *, tenant: str) -> tuple[list[list[float]], int]:
        """One vector per text and the input tokens charged; raises EmbedFailed when the model cannot answer."""
        ...


class EmbedFailed(Exception):
    """The embedding model did not answer (down, out of budget, refused); `code` says which, for a lane's reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ModelsEmbedder:
    calls: ModelCalls
    model: str
    width: int

    async def embed(self, texts: list[str], *, tenant: str) -> tuple[list[list[float]], int]:
        try:
            done = await self.calls.embed(texts, alias=self.model, width=self.width, tenant=tenant, step=EMBED_STEP)
        except ModelCallError as e:
            raise EmbedFailed(e.code, str(e)) from e
        return done.vectors, done.input_tokens


def unit_text(heading: str | None, text: str) -> str:
    """What a unit's vector is made from: its heading path and its text, as the keyword lane weighs them."""
    return f"{heading}\n\n{text}" if heading else text


async def embed_pending(vectors: PgVectorStore, embedder: Embedder, tenant: str, *, limit: int = PASS_LIMIT) -> int:
    """Embeds the tenant's units with no vector of the current model, up to `limit`; the number embedded. Raises
    EmbedFailed when the model refuses, keeping what earlier batches stored."""
    if not await vectors.ready():
        return 0
    done = 0
    while done < limit:
        units = await vectors.pending(tenant, model=embedder.model, width=embedder.width, limit=BATCH)
        if not units:
            break
        found, _ = await embedder.embed([unit_text(u["heading"], u["text"]) for u in units], tenant=tenant)
        rows = [{**u, "unit_id": u["id"], "vector": v} for u, v in zip(units, found, strict=True)]
        await vectors.put(tenant, rows, model=embedder.model, width=embedder.width)
        done += len(units)
    return done


class Backlog:
    """Units not yet embedded at the last beat, across tenants, for /health."""

    def __init__(self) -> None:
        self.pending: int | None = None
        self.last_error: str | None = None


async def embed_all(store: KnowledgeStore, vectors: PgVectorStore, embedder: Embedder, backlog: Backlog) -> int:
    """One beat: every tenant's pending units, tenant by tenant; the number embedded."""
    total, left = 0, 0
    backlog.last_error = None
    for tenant in await store.tenants():
        with isolation.tenant_wide(FIND_PENDING, tenant_id=tenant):
            try:
                total += await embed_pending(vectors, embedder, tenant)
            except EmbedFailed as e:
                backlog.last_error = e.code
                log.warning("kb_embed_failed", tenant=tenant, code=e.code)
            left += await vectors.pending_count(tenant, model=embedder.model, width=embedder.width)
    backlog.pending = left
    return total


async def keep_embedding(
    store: KnowledgeStore, vectors: PgVectorStore, embedder: Embedder, backlog: Backlog, stop: asyncio.Event
) -> None:
    """Until `stop`; a failed beat shows in /health/background and is tried again at the next."""

    async def once() -> int:
        return await embed_all(store, vectors, embedder, backlog)

    await background.run("kb_embed", once, stop=stop, store=background.LOCAL)
