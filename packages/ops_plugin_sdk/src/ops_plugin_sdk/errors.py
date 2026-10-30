"""The errors a plugin function raises, each mapped by the service onto the gateway's failure codes, so a plugin's
failure reads as any tool's: an expired or revoked sign-in becomes "needs reconnect", a vendor's limit RATE_LIMITED."""

from __future__ import annotations


class PluginError(Exception):
    code = "PLUGIN_FAILED"


class NeedsReconnect(PluginError):
    code = "AUTH_EXPIRED"


class RateLimited(PluginError):
    code = "RATE_LIMITED"


class EgressDenied(PluginError):
    code = "EGRESS_DENIED"


class DeadlineExceeded(PluginError):
    code = "TIMEOUT"


class BadInput(PluginError):
    code = "INVALID_INPUT"
