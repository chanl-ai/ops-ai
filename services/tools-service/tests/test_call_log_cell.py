"""Who reads the tool-call log (GET /v1/executions), which names who called each tool: a reviewer, builder or admin of
the team, on the activity.view cell; a viewer gets 403 role_required, so a hidden page is never the only guard."""

from __future__ import annotations

import httpx

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person


async def test_only_who_holds_activity_view_reads_the_call_log(client: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    viewer = person(tenant, "Ravi Menon", {"team_platform": "viewer"})
    for path in ("/v1/executions", "/v1/executions/call_missing"):
        r = await client.get(path, headers=viewer)
        assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", (path, r.text)
    for role in ("approver", "builder", "admin"):
        r = await client.get("/v1/executions", headers=person(tenant, f"Someone {role}", {"team_platform": role}))
        assert r.status_code == 200, (role, r.text)
