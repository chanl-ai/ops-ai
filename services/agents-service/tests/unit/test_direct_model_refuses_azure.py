"""The direct model path (no models-service) with Azure install settings (c-605): it can only call api.openai.com, so it
would send the Azure resource's key there. It refuses and names models-service instead."""

from __future__ import annotations

import pytest

from ops_agent_kernel.models import NoModelKeyError, build_model
from ops_service_kit.settings import Settings


def test_build_model_refuses_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    azure = {
        "OPENAI_API_TYPE": "azure",
        "OPENAI_API_BASE": "https://contoso-claims.openai.azure.com",
        "OPENAI_API_VERSION": "v1",
        "OPENAI_API_REGION": "swedencentral",
        "OPENAI_API_KEY": "azure-key-not-for-openai",
        "OPS_MODEL_ALIAS": "gpt-4o",
    }
    for name, value in azure.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(NoModelKeyError, match="OPS_MODELS_URL"):
        build_model(Settings())
    # Without the Azure type the same key builds an OpenAI model, as before.
    monkeypatch.delenv("OPENAI_API_TYPE")
    for name in ("OPENAI_API_BASE", "OPENAI_API_VERSION", "OPENAI_API_REGION"):
        monkeypatch.delenv(name)
    assert build_model(Settings()) is not None
