"""PKCE (RFC 7636) with S256 only: a verifier kept encrypted with the sign-in, its challenge sent to the system."""

from __future__ import annotations

import base64
import hashlib
import secrets


def verifier() -> str:
    """43 to 128 characters of [A-Za-z0-9-._~]; 64 random bytes base64url-encoded give 86."""
    return secrets.token_urlsafe(64)


def challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
