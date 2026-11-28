"""Where a turn's model calls go: through models-service by alias, where the provider keys, budgets and rate limits
live (ADR-0008), or straight to OpenAI with a key in this process.

Direct calls speak only OpenAI's API. Every other provider, Anthropic included, is served through models-service. There
is no fallback chain: a provider error fails the turn, and the message says so.
"""

from __future__ import annotations

import httpx2
from openai import AsyncOpenAI

from ops_service_kit.settings import Settings

from .contract import ModelEndpoint


class NoModelKeyError(RuntimeError):
    pass


# The runtime's default alias, which models-service serves; it names no provider model, so a direct call cannot use it.
DEFAULT_ALIAS = "default"


def build_model(settings: Settings) -> ModelEndpoint:
    alias = settings.model_alias
    if alias == DEFAULT_ALIAS:
        raise NoModelKeyError(
            "The default alias is served by models-service (OPS_MODELS_URL). To call a provider directly, set "
            "OPS_MODEL_ALIAS to the provider's model name."
        )
    if (settings.openai_api_type or "").lower() == "azure":
        # The direct path speaks only to api.openai.com, which would be sent the Azure resource's key.
        raise NoModelKeyError(
            "OPENAI_API_TYPE=azure is served through models-service: set OPS_MODELS_URL and OPS_MODELS_KEY."
        )
    if alias.startswith("claude-"):
        raise NoModelKeyError(f"Model {alias} is served through models-service: set OPS_MODELS_URL and OPS_MODELS_KEY.")
    if settings.openai_api_key is None:
        raise NoModelKeyError(f"Model {alias} needs OPENAI_API_KEY in the environment.")
    return ModelEndpoint(AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0), alias)


class ModelsServiceModels:
    """One endpoint per alias, pointed at models-service with this service's model key."""

    def __init__(self, base_url: str, key: str, *, http_client: httpx2.AsyncClient | None = None) -> None:
        # No retries: models-service answers 429 for a key over its limit, and a retry would spend the limit again
        # and hide the refusal from the turn.
        self.client = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1/models", api_key=key, max_retries=0, http_client=http_client
        )

    def model_for(self, alias: str) -> ModelEndpoint:
        return ModelEndpoint(self.client, alias)
