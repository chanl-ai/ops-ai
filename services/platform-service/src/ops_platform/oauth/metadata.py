"""The authorization server's metadata document (RFC 8414): where to register, authorize and exchange, and that only
S256 challenges are taken."""

from __future__ import annotations

from typing import Any

from . import OAuthError


def server_metadata(public_url: str | None) -> dict[str, Any]:
    if not public_url:
        raise OAuthError(
            "server_error",
            "This install names no public address (OPS_PLATFORM_PUBLIC_URL), so it has no issuer.",
            status=503,
        )
    base = public_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": True,
    }
