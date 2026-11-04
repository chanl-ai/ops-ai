"""The install's model connection, read and checked by models-service alone, so no other
service can fail to start over it, under the names the OpenAI and Azure OpenAI clients read.

OPENAI_API_BASE alone, or OPENAI_API_TYPE=openai, is an OpenAI-compatible endpoint called with a bearer key: vLLM,
Ollama, LiteLLM, a gateway, or api.openai.com (the default base for `openai`). OPENAI_API_TYPE=azure makes
OPENAI_API_BASE an Azure resource's endpoint, called with the `api-key` header; OPENAI_API_VERSION is then required and
OPENAI_API_REGION is optional, only flagging an answer from another region. OPENAI_BASE_URL, the OpenAI SDK's name that
make setup writes, is read as OPENAI_API_BASE. Only a combination that cannot work stops start-up, naming the variable.
The key itself is OPENAI_API_KEY in dev (scripts/stack.sh saves it as provider key `openai`) and a saved provider key on
an install; it is never read from here."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Azure's v1 API: no dated version, the deployment sent as `model`. A dated version builds the deployment path;
# 2024-10-21 is the first GA whose streams carry usage under stream_options.include_usage, and an older one streams
# none, so a call's spend would read zero.
AZURE_OPENAI_V1 = "v1"
AZURE_OPENAI_MIN_VERSION = "2024-10-21"
_DATED_VERSION = re.compile(r"^\d{4}-\d{2}-\d{2}(-preview)?$")


def is_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def azure_openai_problem(endpoint: str | None, api_version: str | None) -> tuple[str, str] | None:
    """The first thing wrong with an Azure OpenAI connection, as (field, why) with field endpoint or api_version; None
    when it can be called. The region is never a reason: it only flags an answer from elsewhere. One rule for these
    settings and the connection route."""
    if not is_url(endpoint or ""):
        return "endpoint", "is the resource's endpoint, such as https://<resource>.openai.azure.com"
    parts = urlsplit(endpoint or "")
    if parts.path.strip("/") or parts.query:
        return (
            "endpoint",
            f"is the resource's endpoint with no path (https://{parts.netloc}); the path is built from it",
        )
    if not api_version:
        return "api_version", f"is missing: {AZURE_OPENAI_V1}, or a dated version from {AZURE_OPENAI_MIN_VERSION} on"
    if api_version != AZURE_OPENAI_V1:
        if not _DATED_VERSION.match(api_version):
            return "api_version", f"{api_version!r} is neither {AZURE_OPENAI_V1} nor a date such as 2024-10-21"
        if api_version[:10] < AZURE_OPENAI_MIN_VERSION:
            return "api_version", (
                f"{api_version} is older than {AZURE_OPENAI_MIN_VERSION}, whose streams carry no usage, so spend would "
                "read zero"
            )
    return None


_NAMES = {"endpoint": "OPENAI_API_BASE", "api_version": "OPENAI_API_VERSION"}


class ModelConnectionSettings(BaseSettings):
    # An empty value is unset, as in the shared settings, so a compose file can name a variable and leave it blank.
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    openai_api_type: Literal["openai", "azure"] | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_TYPE")
    )
    openai_api_base: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_BASE", "OPENAI_BASE_URL")
    )
    openai_api_version: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_VERSION"))
    openai_api_region: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_REGION"))

    @model_validator(mode="after")
    def _can_work(self) -> ModelConnectionSettings:
        if self.openai_api_base is not None and not is_url(self.openai_api_base):
            raise ValueError(f"OPENAI_API_BASE {self.openai_api_base!r} is not a URL")
        if self.openai_api_type == "azure":
            problem = azure_openai_problem(self.openai_api_base, self.openai_api_version)
            if problem is not None:
                raise ValueError(f"OPENAI_API_TYPE=azure: {_NAMES[problem[0]]} {problem[1]}")
        return self
