"""Embedding index units with the environment's one embedding model (settings.embedding_alias at embedding_width),
through models-service with kb-service's own key (`kb:index` spends there), so the meaning lane can compare a question
with each unit.

Each vector records the model that served it, as models-service names it in each reply, not the alias: an admin can
point the alias at another model (Settings, Model aliases), and vectors of two models are not comparable. The embedder
learns the serving model from every reply, so the first search or pass after a move sees every stored vector as stale
and the beat embeds every unit again under the new model, with no file read again. Until a reply has named the model, a
tenant's own stored vectors say which model it was: nothing calls the model just to ask.

After a sync or rebuild settles, its tenant's units without a vector of the current model are embedded at once; a
background beat embeds whatever is left (a model that was down, a model or width changed). Each batch is one request;
a refusal stops the pass and the beat tries again."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ops_service_kit.logging import get_logger
from ops_service_kit.model_calls import ModelCallError, ModelCalls
from ops_store import background, isolation

from .store import KnowledgeStore
from .store.vectors import PgVectorStore, UnitVector

log = get_logger(__name__)

# Units per request: well inside models-service's 2,048 inputs, and small enough that one slow batch holds nothing up.
BATCH = 64
# Units one pass embeds for one tenant before giving the next tenant a turn.
PASS_LIMIT = 2_000
EMBED_STEP = "kb:index"
FIND_PENDING = "background process: the knowledge embedder reads each tenant's units that have no vector yet"


class Embedder(Protocol):
    """The environment's embedding model: the model serving it and its width, which every stored vector records."""

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
    """The environment's alias through models-service. `model` is the model the last reply said served it; until a
    call has answered it is empty, which no stored vector records."""

    calls: ModelCalls
    alias: str
    width: int
    model: str = ""

    async def embed(self, texts: list[str], *, tenant: str) -> tuple[list[list[float]], int]:
        try:
            done = await self.calls.embed(texts, alias=self.alias, width=self.width, tenant=tenant, step=EMBED_STEP)
        except ModelCallError as e:
            raise EmbedFailed(e.code, str(e)) from e
        self.model = done.model
        return done.vectors, done.input_tokens


async def current_model(vectors: PgVectorStore, embedder: Embedder, tenant: str) -> str:
    """The model last heard from, else the model of one of the tenant's stored vectors ("" with none)."""
    return embedder.model or await vectors.stored_model(tenant, width=embedder.width)


def unit_text(heading: str | None, text: str) -> str:
    """What a unit's vector is made from: its heading path and its text, as the keyword lane weighs them."""
    return f"{heading}\n\n{text}" if heading else text


async def embed_pending(vectors: PgVectorStore, embedder: Embedder, tenant: str, *, limit: int = PASS_LIMIT) -> int:
    """Embeds the tenant's units with no vector of the current model, up to `limit`; the number embedded. Raises
    EmbedFailed when the model refuses, keeping what earlier batches stored."""
    if not await vectors.ready():
        return 0
    model = await current_model(vectors, embedder, tenant)
    done = 0
    while done < limit:
        units = await vectors.pending(tenant, model=model, width=embedder.width, limit=BATCH)
        if not units:
            break
        # A reply from another model than the one the units were listed for is stored under the model it names; the
        # next listing then holds every unit that model has not embedded.
        found, _ = await embedder.embed([unit_text(u["heading"], u["text"]) for u in units], tenant=tenant)
        model = embedder.model
        rows = [
            UnitVector(unit_id=u["id"], chunk_id=u["chunk_id"], item_id=u["item_id"], vector=v)
            for u, v in zip(units, found, strict=True)
        ]
        await vectors.put(tenant, rows, model=model, width=embedder.width)
        done += len(units)
    return done


class Backlog:
    """Units not yet embedded at the last beat, across tenants, for /health."""

    def __init__(self) -> None:
        self.pending: int | None = None
        self.last_error: str | None = None


async def embed_all(store: KnowledgeStore, vectors: PgVectorStore, embedder: Embedder, backlog: Backlog) -> int:
    """One beat: every tenant's pending units, tenant by tenant; the number embedded. A tenant the model refuses (its
    budget spent, the model down) is tried again at the next beat and holds no other tenant back."""
    total, left = 0, 0
    backlog.last_error = None
    for tenant in await store.tenants():
        with isolation.tenant_wide(FIND_PENDING, tenant_id=tenant):
            try:
                total += await embed_pending(vectors, embedder, tenant)
            except EmbedFailed as e:
                backlog.last_error = e.code
                log.warning("kb_embed_failed", tenant=tenant, code=e.code)
            if await vectors.ready():
                model = await current_model(vectors, embedder, tenant)
                left += await vectors.pending_count(tenant, model=model, width=embedder.width)
    backlog.pending = left
    return total


async def keep_embedding(
    store: KnowledgeStore, vectors: PgVectorStore, embedder: Embedder, backlog: Backlog, stop: asyncio.Event
) -> None:
    """Until `stop`; a failed beat shows in /health/background and is tried again at the next."""

    async def once() -> int:
        return await embed_all(store, vectors, embedder, backlog)

    await background.run("kb_embed", once, stop=stop, store=background.LOCAL)
