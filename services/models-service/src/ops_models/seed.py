"""Development seed: the scripted provider, three bank aliases, a key per seeded agent and agents-service's own key.
With a fake OpenAI URL, also connection openai-local at that URL and alias `default` (agents-service's default) on it.
Idempotent: rows that exist are left alone, so a restart never resets a spent budget, except openai-local's URL,
which follows the fake's until an operator binds it to a real provider with a credential."""

from __future__ import annotations

from decimal import Decimal

from ops_service_kit.ids import now_iso
from ops_store.database import Database

from .app import secret_hash
from .store import Aliases, ModelKeys, Providers

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
# files-service's own key for extractions (c-235), on its own budget line so extraction spend shows apart.
EXTRACT_KEY = "files:extract"
EXTRACT_SECRET = "mk_dev_extract"
EXTRACT_TENANT_BUDGET = Decimal(10)
# tools-service's own key for checking writes against a team's sending policy (c-300), on its own budget line.
TOOLS_CHECK_KEY = "tools:check"
TOOLS_CHECK_SECRET = "mk_dev_tools_check"
OPENAI_LOCAL = "openai-local"
# The runtime's default alias, served by whatever openai-local points at: the fake in dev, where any model name answers.
# Pointing it at a real provider means setting its provider model too (PUT the alias); no vendor model is named here.
OPENAI_ALIASES: dict[str, tuple[str, str, str, str, str]] = {
    "default": ("chat", "default", "confidential", "1.25", "10"),
}


def dev_secret(agent: str) -> str:
    """The seeded keys' secrets in development, so a local agents-service can be configured without reading a log."""
    return f"mk_dev_{agent}"


async def seed(db: Database, fake_openai_url: str | None = None) -> None:
    providers, aliases, keys = Providers(db), Aliases(db), ModelKeys(db)
    scripted = {"id": SCRIPTED, "name": "scripted", "type": "scripted", "base_url": None, "key_ref": None}
    await providers.ensure({**scripted, "created_at": now_iso()})
    bound = {name: (SCRIPTED, *row) for name, row in ALIASES.items()}
    if fake_openai_url:
        local = {"id": OPENAI_LOCAL, "name": OPENAI_LOCAL, "type": "openai-compatible", "key_ref": None}
        await providers.ensure({**local, "base_url": fake_openai_url, "created_at": now_iso()})
        # The fake's URL wins over whatever a dev database kept (an old port, a provider with no credential), so
        # `default` does not reach a real provider by accident. A row with a credential name was bound to a real
        # provider on purpose (`make demo-model`, the shared stack's make up) and keeps it. Dev only.
        await providers.follow_url(OPENAI_LOCAL, fake_openai_url)
        bound |= {name: (OPENAI_LOCAL, *row) for name, row in OPENAI_ALIASES.items()}
    for name, (provider, kind, model, ceiling, price_in, price_out) in bound.items():
        prices = {"input_per_million": Decimal(price_in), "output_per_million": Decimal(price_out)}
        await aliases.create(
            name, kind, {"provider_id": provider, "model_id": model, "cleared_sensitivity": ceiling, **prices}
        )
    identities = [(f"agent:{a}", "agent", dev_secret(a)) for a in AGENTS] + [
        (RUNTIME_KEY, "purpose", RUNTIME_SECRET),
        (EXTRACT_KEY, "purpose", EXTRACT_SECRET),
        (TOOLS_CHECK_KEY, "purpose", TOOLS_CHECK_SECRET),
    ]
    for key_id, kind, secret in identities:
        row = {"id": key_id, "kind": kind, "budget": Decimal(50), "spent": Decimal(0), "status": "active"}
        await keys.ensure({**row, "rate_limit_per_minute": 600, "secret_hash": secret_hash(secret)})
    # files-service extracts for every tenant on one key; each tenant spends from its own share (c-251). Set on a key
    # seeded before the column existed, too.
    await keys.set_tenant_budget(EXTRACT_KEY, EXTRACT_TENANT_BUDGET)
