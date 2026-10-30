"""Build an Ops AI plugin: a manifest (plugin.yaml), optional Python tools marked with `@tool`, and the `ops plugin`
commands. The guide is docs/guide/plugins.md."""

from .context import Context, Http, Response, Settings
from .errors import BadInput, DeadlineExceeded, EgressDenied, NeedsReconnect, PluginError, RateLimited
from .manifest import Manifest, ManifestError, read
from .plugin import Plugin, tool

__all__ = [
    "BadInput",
    "Context",
    "DeadlineExceeded",
    "EgressDenied",
    "Http",
    "Manifest",
    "ManifestError",
    "NeedsReconnect",
    "Plugin",
    "PluginError",
    "RateLimited",
    "Response",
    "Settings",
    "read",
    "tool",
]
