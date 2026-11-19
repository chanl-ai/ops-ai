"""Before any test builds Settings: the fixed dev user unless a test asks for sign-in, and none of a running stack's
service addresses."""

from __future__ import annotations

from ops_service_kit.testdb import isolate_from_stack

isolate_from_stack()
