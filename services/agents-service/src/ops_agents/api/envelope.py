"""The console's envelope (apps/console/src/lib/api/http.ts), shared by every service in `ops_service_kit.http`."""

from __future__ import annotations

from ops_service_kit.http import error_body, install_error_handlers, ok

__all__ = ["error_body", "install_error_handlers", "ok"]
