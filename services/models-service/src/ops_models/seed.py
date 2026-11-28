"""Development seed: the scripted provider, three bank aliases, a key per seeded agent and each service's own key.
With the install's model connection in settings (OPENAI_API_TYPE or OPENAI_API_BASE), connection openai-local
is that provider, rewritten from the settings on every start; otherwise, with a fake OpenAI URL, openai-local is at
that URL. Either way alias `default` (agents-service's default) is on it. Idempotent: rows that exist are left alone,
so a restart never resets a spent budget, except openai-local, which follows the settings, or the fake's URL until an
operator binds it to a real provider with a credential."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from ops_identity.fastapi import DEV_TENANT
from ops_service_kit.ids import now_iso
from ops_store import isolation
from ops_store.database import Database

from .app import secret_hash
from .connection_settings import ModelConnectionSettings
from .store import Aliases, ModelKeys, Providers
from .store.providers import InstallConnection

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
# files-service's own key for extractions, on its own budget line so extraction spend shows apart.
EXTRACT_KEY = "files:extract"
EXTRACT_SECRET = "mk_dev_extract"
EXTRACT_TENANT_BUDGET = Decimal(10)
# tools-service's own key for checking writes against a team's sending policy, on its own budget line.
TOOLS_CHECK_KEY = "tools:check"
TOOLS_CHECK_SECRET = "mk_dev_tools_check"
# kb-service's own key for embeddings, likely questions and FAQ drafts, spent per tenant like extractions.
KB_KEY = "kb:index"
KB_SECRET = "mk_dev_kb"
KB_TENANT_BUDGET = Decimal(10)
OPENAI_LOCAL = "openai-local"
# The runtime's default alias, and the team assistant's own, served by whatever openai-local points at: the fake in dev,
# where any model name answers. Pointing one at a real provider means setting its provider model too (PUT the alias);
# no vendor model is named here. `assistant` carries no reasoning effort: a model that refuses function tools with one
# (gpt-5.5 on chat completions) would refuse every assistant turn.
OPENAI_ALIASES: dict[str, tuple[str, str, str, str, str]] = {
    "default": ("chat", "default", "confidential", "1.25", "10"),
    "assistant": ("chat", "assistant", "confidential", "1.25", "10"),
}


# OpenAI's own endpoint, for OPENAI_API_TYPE=openai with no OPENAI_API_BASE.
OPENAI_URL = "https://api.openai.com/v1"
# The key name the dev stack saves OPENAI_API_KEY under (scripts/stack.sh, OPS_MODEL_PROVIDER_KEYS).
OPENAI_KEY_NAME = "openai"


def install_connection(settings: ModelConnectionSettings) -> InstallConnection | None:
    """openai-local's fields from the install's model settings, or None when neither OPENAI_API_TYPE nor
    OPENAI_API_BASE is set. A base with no type is an OpenAI-compatible endpoint. The settings class has already refused
    a combination that cannot work."""
    if settings.openai_api_type is None and settings.openai_api_base is None:
        return None
    if settings.openai_api_type == "azure":
        return {
            "type": "azure-openai",
            "base_url": settings.openai_api_base,
            "api_version": settings.openai_api_version,
            "region": settings.openai_api_region,
            "key_ref": OPENAI_KEY_NAME,
        }
    base = settings.openai_api_base or OPENAI_URL
    return {
        "type": "openai-compatible",
        "base_url": base,
        "api_version": None,
        "region": None,
        "key_ref": OPENAI_KEY_NAME,
    }


def dev_secret(agent: str) -> str:
    """The seeded keys' secrets in development, so a local agents-service can be configured without reading a log."""
    return f"mk_dev_{agent}"


async def seed(
    db: Database,
    fake_openai_url: str | None = None,
    install: InstallConnection | None = None,
    *,
    tenant: str = DEV_TENANT,
    kb_daily_cap: float = 50.0,
) -> None:
    """Seeds `tenant`, the install's account, with its connections and aliases (`seed_account`), and the install's
    keys."""
    await seed_account(db, tenant, install_tenant=tenant, fake_openai_url=fake_openai_url, install=install)
    await _keys(db, kb_daily_cap)


def connection_id(base: str, tenant: str, install_tenant: str) -> str:
    """The id of a seeded connection in `tenant`. A connection id is unique across the install, so another account's
    copy of `scripted` or `openai-local` gets its own; the install's account keeps the plain ids its scripts name."""
    if tenant == install_tenant:
        return base
    return f"{base}_{hashlib.sha256(tenant.encode()).hexdigest()[:12]}"


async def seed_account(
    db: Database,
    tenant: str,
    *,
    install_tenant: str,
    fake_openai_url: str | None,
    install: InstallConnection | None,
) -> int:
    """`tenant`'s dev connections and aliases, `default` among them when there is an OpenAI-compatible model, written
    as that account; rows it already holds are left alone. Returns how many aliases it made."""
    with isolation.scope(tenant, None):
        return await _connections_and_aliases(
            db,
            fake_openai_url,
            install,
            connection_id(SCRIPTED, tenant, install_tenant),
            connection_id(OPENAI_LOCAL, tenant, install_tenant),
        )


async def _connections_and_aliases(
    db: Database, fake_openai_url: str | None, install: InstallConnection | None, scripted: str, openai_local: str
) -> int:
    providers, aliases = Providers(db), Aliases(db)
    await providers.ensure(
        {
            "id": scripted,
            "name": "scripted",
            "type": "scripted",
            "base_url": None,
            "key_ref": None,
            "created_at": now_iso(),
        }
    )
    bound = {name: (scripted, *row) for name, row in ALIASES.items()}
    if install is not None:
        # The settings win over whatever the row held, type included, so setting OPENAI_API_TYPE moves the stack's
        # default model on the next start; the fake is not used.
        await providers.ensure(
            {
                "id": openai_local,
                "name": OPENAI_LOCAL,
                "type": install["type"],
                "base_url": install["base_url"],
                "key_ref": install["key_ref"],
                "api_version": install["api_version"],
                "region": install["region"],
                "created_at": now_iso(),
            }
        )
        await providers.rebind(openai_local, install)
        bound |= {name: (openai_local, *row) for name, row in OPENAI_ALIASES.items()}
    elif fake_openai_url:
        await providers.ensure(
            {
                "id": openai_local,
                "name": OPENAI_LOCAL,
                "type": "openai-compatible",
                "key_ref": None,
                "base_url": fake_openai_url,
                "created_at": now_iso(),
            }
        )
        # The fake's URL wins over whatever a dev database kept (an old port, a provider with no credential), so
        # `default` does not reach a real provider by accident. A row with a credential name was bound to a real
        # provider on purpose (`make demo-model`, the shared stack's make up) and keeps it. Dev only.
        await providers.follow_url(openai_local, fake_openai_url)
        bound |= {name: (openai_local, *row) for name, row in OPENAI_ALIASES.items()}
    made = 0
    for name, (provider, kind, model, ceiling, price_in, price_out) in bound.items():
        created = await aliases.create(
            name,
            kind,
            {
                "provider_id": provider,
                "model_id": model,
                "cleared_sensitivity": ceiling,
                "input_per_million": Decimal(price_in),
                "output_per_million": Decimal(price_out),
            },
        )
        made += created is True
    return made


async def _keys(db: Database, kb_daily_cap: float) -> None:
    keys = ModelKeys(db)
    identities = [(f"agent:{a}", "agent", dev_secret(a)) for a in AGENTS] + [
        (RUNTIME_KEY, "purpose", RUNTIME_SECRET),
        (EXTRACT_KEY, "purpose", EXTRACT_SECRET),
        (TOOLS_CHECK_KEY, "purpose", TOOLS_CHECK_SECRET),
        (KB_KEY, "purpose", KB_SECRET),
    ]
    for key_id, kind, secret in identities:
        await keys.ensure(
            {
                "id": key_id,
                "kind": kind,
                "budget": Decimal(50),
                "spent": Decimal(0),
                "status": "active",
                "rate_limit_per_minute": 600,
                "secret_hash": secret_hash(secret),
            }
        )
    # files-service extracts for every tenant on one key; each tenant spends from its own share. Set on a key
    # seeded before the column existed, too.
    await keys.set_tenant_budget(EXTRACT_KEY, EXTRACT_TENANT_BUDGET)
    await keys.set_tenant_budget(KB_KEY, KB_TENANT_BUDGET)
    # The environment's daily ceiling on kb-service's model work.
    await keys.set_daily_cap(KB_KEY, Decimal(str(kb_daily_cap)))
