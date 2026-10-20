"""Resolves who is calling a service: a platform token, an API key or a service token, to a `Principal`."""

from __future__ import annotations

from .client import ServiceCallError, ServiceClient, ServiceUnreachable
from .fastapi import (
    Auth,
    CurrentCaller,
    CurrentPrincipal,
    CurrentService,
    CurrentTenantCaller,
    current_caller,
    current_principal,
    current_service,
    current_tenant_caller,
    install_auth,
)
from .http import http_introspect, http_jwks
from .jwks import JwksCache
from .principal import Principal
from .resolve import Identity, ServiceAuth, mint_service_token
from .service_keys import dev_service_signer, service_signer, service_verifiers

__all__ = [
    "Auth",
    "CurrentCaller",
    "CurrentPrincipal",
    "CurrentService",
    "CurrentTenantCaller",
    "Identity",
    "JwksCache",
    "Principal",
    "ServiceAuth",
    "ServiceCallError",
    "ServiceClient",
    "ServiceUnreachable",
    "current_caller",
    "current_principal",
    "current_service",
    "current_tenant_caller",
    "dev_service_signer",
    "http_introspect",
    "http_jwks",
    "install_auth",
    "mint_service_token",
    "service_signer",
    "service_verifiers",
]
