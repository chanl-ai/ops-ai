"""models-service's door to its database: the tables (`tables`), provider connections (`providers`), aliases and
their versions (`aliases`), model keys and tenant shares (`keys`), the account's provider keys (`provider_keys`) and
the call log (`calls`). Only this package imports SQLAlchemy in models-service (the drivers-only-in-stores contract in
.importlinter)."""

from __future__ import annotations

from .aliases import SENSITIVITY, Aliases, cleared
from .calls import CallLog
from .keys import ModelKeys
from .provider_keys import ProviderKeyStore
from .providers import Providers
from .tables import (
    metadata,
    model_aliases,
    model_call_log,
    model_key_tenants,
    model_keys,
    provider_connections,
    provider_keys,
)

__all__ = [
    "SENSITIVITY",
    "Aliases",
    "CallLog",
    "ModelKeys",
    "ProviderKeyStore",
    "Providers",
    "cleared",
    "metadata",
    "model_aliases",
    "model_call_log",
    "model_key_tenants",
    "model_keys",
    "provider_connections",
    "provider_keys",
]
