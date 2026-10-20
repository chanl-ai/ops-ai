"""Prints a fresh set of the keys an install outside dev must have, as NAME=value lines for a secrets store:
`uv run python deploy/fly/generate_keys.py | fly secrets import -a <app>`. Nothing is written to disk.

Per service, OPS_SVC_KEY_<SERVICE> is its Ed25519 signing key; deploy/fly/processes.toml hands each process its own
as OPS_SERVICE_SIGNING_KEY under kid svc-<service>-1, and OPS_SERVICE_PUBLIC_KEYS lists every public key so each
callee can verify every caller. The platform signing key signs people's tokens; the review key signs approval tokens;
the secrets key seals tool and storage credentials.
"""

from __future__ import annotations

import base64
import json
import secrets

from cryptography.hazmat.primitives import serialization

from ops_policy import Ed25519Signer

SERVICES = ("platform", "agents", "tools", "kb", "files", "models", "documents")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> dict[str, str]:
    """A fresh key set by setting name; deploy/fly/staging/apps.py hands each app its share."""
    public: dict[str, dict[str, str]] = {}
    keys: dict[str, str] = {}
    for svc in SERVICES:
        signer = Ed25519Signer.generate(f"svc-{svc}-1")
        raw = signer.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        public[signer.kid] = {"service": svc, "x": _b64(raw)}
        keys[f"OPS_SVC_KEY_{svc.upper()}"] = signer.private_text()
    keys["OPS_SERVICE_PUBLIC_KEYS"] = json.dumps(public, separators=(",", ":"))
    keys["OPS_PLATFORM_SIGNING_KEY"] = Ed25519Signer.generate("platform-1").private_text()
    keys["OPS_REVIEW_KEY"] = secrets.token_urlsafe(32)
    keys["OPS_SECRETS_KEY"] = secrets.token_hex(32)
    return keys


def main() -> None:
    print("\n".join(f"{k}={v}" for k, v in generate().items()))


if __name__ == "__main__":
    main()
