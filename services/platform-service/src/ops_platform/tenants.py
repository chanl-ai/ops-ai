"""Whether this install may hold a tenant (c-418). `tenancy_mode` is the only difference between a single-tenant and a
multi-tenant install: in `single` every tenant but the install's own is refused where tenants are created (the dev seed
today, the provisioner's create-tenant route in c-272), with 409 `single_tenant`. Nothing else reads the mode, which
`tests/test_tenancy_mode.py` holds."""

from __future__ import annotations

from ops_identity.fastapi import DEV_TENANT
from ops_service_kit.errors import Conflict
from ops_service_kit.settings import Settings

SINGLE_TENANT = "single_tenant"


def install_tenant(settings: Settings) -> str | None:
    """The one tenant a single-tenant install holds (the bootstrap tenant, else the dev seed's); None when it holds
    many."""
    if settings.tenancy_mode == "multi":
        return None
    return settings.bootstrap_tenant_id or DEV_TENANT


def require_tenant_allowed(only: str | None, tenant_id: str) -> None:
    """Refuses `tenant_id` on a single-tenant install whose tenant is `only`."""
    if only is not None and tenant_id != only:
        raise Conflict(
            f"This install holds one tenant ({only}); it cannot create {tenant_id}. Set OPS_TENANCY_MODE=multi to "
            "hold several.",
            code=SINGLE_TENANT,
            details={"tenant": only},
        )
