"""The Python snippets of docs/sdk/upgrading.md, run against a fake API, so the page cannot drift from the client."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from ops_ai import OpsAI

PAGE = Path(__file__).resolve().parents[3] / "docs" / "sdk" / "upgrading.md"


def handler(r: httpx.Request) -> httpx.Response:
    if r.method == "GET" and r.url.path.endswith("/v1/agents"):
        page = int(r.url.params.get("page", "1"))
        assert int(r.url.params["pageSize"]) <= 50
        body: Any = {"data": [f"a{page}"], "pagination": {"page": page, "hasNext": page < 3}, "facets": {}}
        return httpx.Response(200, json={"success": True, "data": body})
    if r.url.path.endswith("/pages"):
        error = {"code": "file_not_ready", "message": "not scanned yet"}
        return httpx.Response(409, json={"success": False, "error": error})
    return httpx.Response(200, json={"success": True, "data": {"id": "b1", "sent": json.loads(r.content or b"{}")}})


def test_the_upgrading_page_snippets_run_and_say_what_they_claim() -> None:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    ops = OpsAI(api_key="ok", base_url="https://ops.test", team="t", http=http)
    scope: dict[str, Any] = {"ops": ops, "workflow_id": "wf", "file_id": "f1", "kb_id": "kb1"}
    for code in re.findall(r"```python\n(.*?)```", PAGE.read_text(), flags=re.S):
        exec("# after" + code.partition("# after")[2], scope)  # the "before" halves are what no longer works
    assert scope["rows"] == ["a1", "a2", "a3"]
