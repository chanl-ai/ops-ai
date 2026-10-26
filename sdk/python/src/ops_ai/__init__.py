"""The Ops AI SDK for Python. `OpsAI` and `AsyncOpsAI` call the platform's public API with an API key, acting in one
team; docs: https://opsai.chanl.ai/docs/sdk/python"""

from ._client import AsyncOpsAI, OpsAI
from ._config import Config
from .errors import (
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    OpsError,
    RateLimited,
    ServerError,
    Unauthorized,
)

__all__ = [
    "AsyncOpsAI",
    "BadRequest",
    "Config",
    "Conflict",
    "Forbidden",
    "NotFound",
    "OpsAI",
    "OpsError",
    "RateLimited",
    "ServerError",
    "Unauthorized",
]
__version__ = "0.1.0"
