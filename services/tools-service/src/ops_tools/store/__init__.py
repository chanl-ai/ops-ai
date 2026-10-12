"""tools-service's door to its database: the gateway's call log and fences (`calls`), the tool-module registry
(`modules`), the tenant's egress allow-list (`egress`), tool secrets (`secrets`) and the per-operation rate counters
(`rate_windows`). Only modules in this package import a database driver (check_standards rule 15)."""

from __future__ import annotations

from . import egress as egress  # registers the allow-list tables on the modules metadata, for migrations
from . import rate_windows as rate_windows  # and the gateway's per-operation rate counters
from . import secrets as secrets  # and the secrets tables
from .calls import CallLog, LeaseSupersededError, gateway_calls, gateway_fences, metadata

__all__ = ["CallLog", "LeaseSupersededError", "gateway_calls", "gateway_fences", "metadata"]
