"""tools-service's binding of `ops_store.isolation`: the database role every store transaction runs as.

Every store class extends `ops_store.store.Store` with `role = ROLE`, so `tx()` runs as `ops_tools_tenant` in the
caller's tenant and team: row-level security on PostgreSQL and the security policies on SQL Server show and accept only
those rows, whatever the query says. Inside a request it is the request's one transaction.
"""

from __future__ import annotations

ROLE = "ops_tools_tenant"
# The role a store's `system_tx(reason)` runs as (tools_0081): row-level security does not apply to it, and its grants
# are only the reads a listing across tenants makes before each item is worked in its own tenant and team.
SYSTEM_ROLE = "ops_tools_system"
