"""uc-615, cli layer: docs/usecases/tools-service/a-team-admin-sets-its-own.md, story S6 (step 7), group B of an earlier change.
The api layer's stack; the team admin runs `ops apps credential` from the repo, signed in as their dev role the way
`make api` signs in, with the client secret on standard input so it is never on a command line (L1). No model call."""

from __future__ import annotations

from apps_walk import apps_stack, ops_cli, target
from usecase_harness import check, data, finish

APP = "plugin:test.person"

with apps_stack(ops_ai_apps={"test.person": "multi-zoom"}) as w:
    secret = w.m["clients"]["multi-app"]
    account = w.turn_on("admin", "test.person", signIn="team")
    check("set-up: the person desk is on for the team account", account != "con_missing", account)

    # 7. Set from standard input; the environment then holds the team's client, and the secret is in no output.
    code, out = ops_cli(
        "admin", "apps", "credential", "set", APP, "--client-id", "multi-app", "--client-secret", "-", stdin=secret
    )
    detail = data(w.gw.get(f"/v1/connections/{account}", headers=w.who["admin"])) or {}
    env = (detail.get("environments") or {}).get("production") or {}
    check(
        "7 `ops apps credential set` takes the secret on standard input, puts the team's client on the app, and the "
        "secret is in no output",
        code == 0 and (env.get("settings") or {}).get("clientId") == "multi-app" and secret not in str(out),
        (target("L1"), {"set": (code, out), "env": env}),
    )

finish()
