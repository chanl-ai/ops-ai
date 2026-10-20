"""The model a turn runs on: built directly from a provider key in this process (ADR-0014 loop; OpenAI by default),
or through models-service by alias, where the provider keys, budgets and rate limits live (ADR-0008).

Direct: an alias starting `claude-` selects Anthropic, and needs ANTHROPIC_API_KEY. There is no fallback chain: a
provider error fails the turn, and the message says so.
"""

from __future__ import annotations

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from ops_service_kit.settings import Settings


class NoModelKeyError(RuntimeError):
    pass


# The runtime's default alias, which models-service serves; it names no provider model, so a direct call cannot use it.
DEFAULT_ALIAS = "default"


def build_model(settings: Settings) -> Model:
    alias = settings.model_alias
    if alias == DEFAULT_ALIAS:
        raise NoModelKeyError(
            "The default alias is served by models-service (OPS_MODELS_URL). To call a provider directly, set "
            "OPS_MODEL_ALIAS to the provider's model name."
        )
    if alias.startswith("claude-"):
        if settings.anthropic_api_key is None:
            raise NoModelKeyError(f"Model {alias} needs ANTHROPIC_API_KEY in the environment.")
        return AnthropicModel(alias, provider=AnthropicProvider(api_key=settings.anthropic_api_key.get_secret_value()))
    if settings.openai_api_key is None:
        raise NoModelKeyError(f"Model {alias} needs OPENAI_API_KEY in the environment.")
    return OpenAIChatModel(alias, provider=OpenAIProvider(api_key=settings.openai_api_key.get_secret_value()))


class ModelsServiceModels:
    """One OpenAI-compatible model per alias, pointed at models-service with this service's model key."""

    def __init__(self, base_url: str, key: str, *, http_client: httpx2.AsyncClient | None = None) -> None:
        # No retries: models-service answers 429 for a key over its limit, and a retry would spend the limit again
        # and hide the refusal from the turn.
        self.client = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1/models", api_key=key, max_retries=0, http_client=http_client
        )
        self.models: dict[str, Model] = {}

    def model_for(self, alias: str) -> Model:
        if alias not in self.models:
            self.models[alias] = OpenAIChatModel(alias, provider=OpenAIProvider(openai_client=self.client))
        return self.models[alias]
