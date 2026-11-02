"""uc-614 a developer calls any API as a standard dev user, api layer:
docs/usecases/platform-service/a-developer-calls-any-api-as.md. Runs `make api` and `make sdk-call` themselves against
this run's platform-service and tools-service, as each role, with the seed's own roles (a viewer is not an admin here).
No model call."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    TOOLS_PORT,
    check,
    finish,
    platform,
    tools,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
ROLES = {
    k: v
    for k, v in json.loads((ROOT / "services/platform-service/seed/dev-roles.json").read_text()).items()
    if k[0] != "_"
}
TEAMS = {"admin": "team_ops", "builder": "team_ops", "approver": "team_ops", "viewer": "team_ops"} | {
    "security": "team_security",
    "platform": "team_platform",
}
TOKENS = Path(tempfile.mkdtemp(prefix="uc614-tokens-"))
# The make commands reach this run's services, and keep their tokens apart from the developer's.
ENV = {
    **os.environ,
    "OPS_PLATFORM_PORT": str(PLATFORM_PORT),
    "OPS_TOOLS_PORT": str(TOOLS_PORT),
    "OPS_API_TOKENS": str(TOKENS),
}
DEMO_PASSWORD = "northfield-demo"
outputs: list[str] = []


def make(*args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["make", "-s", *args], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=180, check=False
    )
    out = p.stdout + p.stderr
    outputs.append(out)
    return p.returncode, out


with ExitStack() as stack:
    api, _ = stack.enter_context(platform())
    stack.enter_context(tools(AUTH))

    # 1. Each role reads its own session answer, signed in as its seeded person, acting in its team.
    for role, email in ROLES.items():
        code, out = make("api", "GET", "/v1/me", f"AS={role}")
        check(
            f"1 make api GET /v1/me AS={role} answers as {email} in {TEAMS[role]}",
            code == 0 and f"({email}, {TEAMS[role]}): 200" in out and f'"email": "{email}"' in out,
            out[:300],
        )

    # 2. A viewer is refused an invite; the admin sends it.
    invite = 'BODY={"emails":["uc614.invitee@harborpine.example"],"role":"viewer"}'
    code, out = make("api", "POST", "/v1/settings/members/invite", "AS=viewer", invite)
    check("2 the viewer is refused an invite (403, exit 1)", code != 0 and ": 403" in out, out[:300])
    code, out = make("api", "POST", "/v1/settings/members/invite", "AS=admin", invite)
    check("2 the admin's invite is accepted", code == 0 and ": 200" in out, out[:300])

    # 3. The service is found from the path: a tools-service list, with its query in Q=.
    code, out = make("api", "GET", "/v1/tool-modules", "Q=pageSize=1", "AS=builder")
    check(
        "3 a tools route goes to tools-service as the builder",
        code == 0 and out.startswith("GET tools/v1/tool-modules?pageSize=1 as builder"),
        out[:200],
    )

    # 4. A token the platform no longer honours is dropped and the role signs in again.
    cached = TOKENS / "local-builder.json"
    saved = json.loads(cached.read_text())
    cached.write_text(json.dumps({**saved, "token": "not-a-token"}))
    code, out = make("api", "GET", "/v1/me", "AS=builder")
    check(
        "4 a broken cached token is replaced by a fresh sign-in",
        code == 0 and ": 200" in out and json.loads(cached.read_text())["token"] != "not-a-token",
        out[:200],
    )

    cached.write_text("{not json")
    code, out = make("api", "GET", "/v1/me", "AS=builder")
    check("4 an unreadable cache file counts as no cache", code == 0 and ": 200" in out, out[:200])

    # 5. A path two services hold is refused, naming both, until SVC= picks one.
    code, out = make("api", "GET", "/v1/templates", "AS=builder")
    check(
        "5 /v1/templates is refused naming agents and documents", code != 0 and "agents and documents" in out, out[:200]
    )
    code, out = make("api", "GET", "/v1/templates", "SVC=agents", "AS=builder")
    check("5 SVC=agents sends it to agents-service", out.startswith("GET agents/v1/templates as builder"), out[:200])

    # 6. One Python SDK call as the approver.
    code, out = make("sdk-call", 'CALL=ops.raw.platform.me_me()["user"]["email"]', "AS=approver")
    check("6 make sdk-call runs the SDK as the approver", code == 0 and ROLES["approver"] in out, out[-300:])

    # 7. No password in what was printed or kept.
    kept = " ".join(f.read_text() for f in TOKENS.glob("*.json"))
    check(
        "7 the demo password is in no output and no cached token file",
        all(DEMO_PASSWORD not in o for o in outputs) and DEMO_PASSWORD not in kept,
        "",
    )

finish()
