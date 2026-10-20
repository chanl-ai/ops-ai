"""The keys (from deploy/fly/generate_keys.py) each service uses besides its own signing key: one table every
deployment target reads (deploy/fly/staging/apps.py, deploy/k8s/secrets.py), so no service is handed a key it does
not use. The worker uses agents-service's."""

from __future__ import annotations

USES: dict[str, tuple[str, ...]] = {
    "platform": ("OPS_PLATFORM_SIGNING_KEY",),
    "agents": ("OPS_REVIEW_KEY",),
    "tools": ("OPS_REVIEW_KEY", "OPS_SECRETS_KEY"),
    "files": ("OPS_SECRETS_KEY",),
    "models": (),
    "kb": (),
    "documents": (),
}
