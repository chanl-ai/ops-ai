"""An operation added to a published module is a major change (c-070): publish sends any new operation to Security,
so the staged change must say major too, or the module page offers a minor publish that then opens a review."""

from __future__ import annotations

from typing import Any

from .conftest import Api


async def test_a_read_added_to_a_published_module_is_staged_and_published_as_major(api: Api) -> None:
    detail: dict[str, Any] = (await api.call("GET", "/mod_core_banking")).json()["data"]
    assert detail["status"] == "published"
    read = {
        "name": "get_branch",
        "description": "A branch by its id",
        "access": "read",
        "method": "GET",
        "url": detail["endpoint"].rstrip("/") + "/branches/{branch_id}",
    }
    r = await api.call("POST", "/mod_core_banking/operations", json=read)
    assert r.status_code in (200, 201), r.text
    [change] = [c for c in r.json()["data"]["pendingChanges"] if c["operation"] == "get_branch"]
    assert change["kind"] == "added" and change["major"] is True
    published = await api.call("POST", "/mod_core_banking/versions", json={"note": "Branch lookups"})
    assert published.status_code == 200, published.text
    a = detail["version"].split(".")[0]
    assert published.json()["data"]["version"] == f"{int(a) + 1}.0.0"
