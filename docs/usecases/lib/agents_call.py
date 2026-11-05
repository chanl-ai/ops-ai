"""One gateway call as agents-service makes it for a run with nobody behind it: prints the status and answer.

python agents_call.py <tools-url> <tenant> <team> <tool> <input-json> [account]
"""

from __future__ import annotations

import json
import sys
from uuid import uuid4

import httpx
from usecase_harness import service_headers


def main() -> None:
    base, tenant, team, tool, given = sys.argv[1:6]
    account = sys.argv[6] if len(sys.argv) > 6 else None
    context: dict[str, str] = {"environment": "live", **({"account": account} if account else {})}
    body = {"tool": tool, "input": json.loads(given), "key": uuid4().hex, "runContext": context}
    headers = service_headers("tools", tenant=tenant, service="agents", team=team) | {"X-Team-Id": team}
    r = httpx.post(f"{base}/v1/calls", json=body, headers=headers, timeout=60)
    print(json.dumps({"status": r.status_code, "body": r.json()}))


if __name__ == "__main__":
    main()
