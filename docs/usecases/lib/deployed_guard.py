"""What a use case run against a deployed host (OPS_USECASE_BASE_URL) may do. The runner (packages/usecase-runner/src/
deployed.ts) applies the same rules before it starts a script; this is the copy a script's own harness applies, so a
script started by hand is held to them too. Each function returns the reason for a refusal, or None."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

# A host whose name says production is refused even when it is the allowed one.
PRODUCTION = re.compile(r"(^|[-.])(prod|production|prd|live)([-.]|$)", re.IGNORECASE)
SCRIPT_NAME = re.compile(r"^test-(uc-(?:\d{3}|[a-z]+-\d+))-([a-z]+)\.")


STAGING_HOST_VAR = "OPS_USECASE_STAGING_HOST"
HOST_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def host_refusal(base_url: str, allowed: str | None) -> str | None:
    """Only the one host named in OPS_USECASE_STAGING_HOST (exact, set by the staging workflow from its app variable)
    may be called; unset or not a host name, nothing may. No pattern: another app of the same shape is not staging."""
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return f"{base_url} is not an https origin"
    if parts.username or parts.password or parts.port or parts.path.strip("/") or parts.query or parts.fragment:
        return f"{base_url} is more than an origin (user, port, path or query)"
    if PRODUCTION.search(host):
        return f"{host} looks like production"
    want = (allowed or "").strip().lower()
    if not HOST_NAME.fullmatch(want):
        return f"{STAGING_HOST_VAR} is not set to a host name, so no host is allowed"
    if host != want:
        return f"{host} is not the staging host ({STAGING_HOST_VAR})"
    return None


def deployed_use_cases(registry: str) -> set[str]:
    """The ids of the registry rows whose Deployed column says `safe`; a use case with no mark is not safe."""
    rows = [line for line in registry.splitlines() if line.strip().startswith("|")]
    head = [c.strip().lower() for c in rows[0].strip().strip("|").split("|")] if rows else []
    if "deployed" not in head:
        return set()
    col = head.index("deployed")
    safe: set[str] = set()
    for row in rows[2:]:
        cells = [c.strip().strip("`") for c in row.strip().strip("|").split("|")]
        if len(cells) > col and cells[col].lower() == "safe":
            safe.add(cells[0])
    return safe


def script_refusal(script: str | None, registry: str) -> str | None:
    match = SCRIPT_NAME.match(Path(script).name) if script else None
    if not match:
        return f"{script or 'this process'} is not a use case script (test-uc-NNN-api.py)"
    uc, layer = match.groups()
    if layer != "api":
        return f"{uc} {layer} is not an api script; only the api layer runs on a deployed host"
    if uc not in deployed_use_cases(registry):
        return f"{uc} is not marked safe for a deployed host (the Deployed column of docs/usecases/README.md)"
    return None
