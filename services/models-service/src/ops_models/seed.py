"""Development seed: the scripted provider, three bank aliases, a key per seeded agent and agents-service's own key.
Idempotent: rows that exist are left alone, so a restart never resets a spent budget."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso

from .app import secret_hash
from .store import model_aliases, model_keys, provider_connections

SCRIPTED = "prov_scripted"
# alias: (kind, model id, cleared sensitivity, input and output price per million)
ALIASES: dict[str, tuple[str, str, str, str, str]] = {
    "bank-standard": ("chat", "scripted-standard", "confidential", "1.25", "10"),
    "bank-reasoning": ("chat", "scripted-reasoning", "internal", "5", "20"),
    "bank-embed": ("embedding", "scripted-embed", "confidential", "0.10", "0"),
}
AGENTS = ("ag_fraud", "ag_dispute", "ag_branch")
# agents-service's own key: every turn it sends through models-service spends from it (OPS_MODELS_KEY).
RUNTIME_KEY = "agents:dev"
RUNTIME_SECRET = "mk_dev_agents"


def dev_secret(agent: str) -> str:
    """The seeded keys' secrets in development, so a local agents-service can be configured without reading a log."""
    return f"mk_dev_{agent}"


async def seed(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(
            postgresql.insert(provider_connections)
            .values(id=SCRIPTED, name="scripted", type="scripted", base_url=None, key_ref=None, created_at=now_iso())
            .on_conflict_do_nothing()
        )
        for name, (kind, model, ceiling, price_in, price_out) in ALIASES.items():
            if (await c.execute(sa.select(model_aliases.c.name).where(model_aliases.c.name == name))).first():
                continue
            await c.execute(
                model_aliases.insert().values(
                    name=name,
                    version=1,
                    kind=kind,
                    provider_id=SCRIPTED,
                    model_id=model,
                    cleared_sensitivity=ceiling,
                    input_per_million=Decimal(price_in),
                    output_per_million=Decimal(price_out),
                    status="current",
                    created_at=now_iso(),
                )
            )
        keys = [(f"agent:{a}", "agent", dev_secret(a)) for a in AGENTS] + [(RUNTIME_KEY, "purpose", RUNTIME_SECRET)]
        for key_id, kind, secret in keys:
            await c.execute(
                postgresql.insert(model_keys)
                .values(
                    id=key_id,
                    kind=kind,
                    budget=Decimal(50),
                    spent=Decimal(0),
                    rate_limit_per_minute=600,
                    status="active",
                    secret_hash=secret_hash(secret),
                )
                .on_conflict_do_nothing()
            )
