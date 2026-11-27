"""Prove builder-facing typed returns against the local stack or staging.

Signs in through the same path as `make api` / `make sdk-call` (`AS=`, `ENV=`): no passwords on argv,
no hard-coded secrets. Lists agents through the typed noun and checks the public exports a builder
imports. A failed-run `wait(check=True)` walk is the use case, not this smoke:

    make usecase-test UC=uc-workflows-2 LAYER=sdk

Usage:

    make sdk-typed-proof AS=builder
    make sdk-typed-proof AS=builder ENV=staging
"""

from __future__ import annotations

import argparse
import inspect
import sys
from typing import Any, get_type_hints

import httpx
import ops_ai
from api_as import Refused, addresses, token
from ops_ai import OpsAI, RunFailed, WaitedRun
from ops_ai._client import Runs


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as", dest="role", default="builder")
    p.add_argument("--env", choices=("local", "staging"), default="local")
    p.add_argument("--team")
    args = p.parse_args(argv)

    def _unreachable(exc: BaseException) -> int:
        hint = (
            "make up && make health"
            if args.env == "local"
            else "check STG_APP / staging reachability (docs/deploy/fly-staging.md)"
        )
        print(f"sdk-typed-proof: cannot reach {args.env} ({exc}). {hint}", file=sys.stderr)
        return 2

    try:
        urls = addresses(args.env)
        session = token(args.env, args.role, urls)
    except Refused as e:
        print(e.message, file=sys.stderr)
        return 2
    except httpx.ConnectError as e:
        return _unreachable(e)

    team = args.team or session.get("team")
    try:
        with OpsAI(base_url=urls["platform"], services=urls, access_token=session["token"], team=team) as ops:
            # One page of agents: the typed list noun against a real service.
            listed: list[dict[str, Any]] = []
            for agent in ops.agents.list(page_size=5):
                listed.append(agent)
                if len(listed) >= 5:
                    break
            me = ops.raw.platform.me_me()
    except httpx.ConnectError as e:
        return _unreachable(e)

    # Type checks read the package class so a test can mock the constructor without
    # losing the public annotation seam (ops_ai.OpsAI.runs → Runs, wait(check=)).
    hints = get_type_hints(ops_ai.OpsAI)
    if hints.get("runs") is not Runs:
        print("sdk-typed-proof: OpsAI.runs is not the typed Runs noun", file=sys.stderr)
        return 1
    if "check" not in inspect.signature(Runs.wait).parameters:
        print("sdk-typed-proof: Runs.wait lacks check=", file=sys.stderr)
        return 1
    if RunFailed.__name__ != "RunFailed" or WaitedRun.__name__ != "WaitedRun":
        print("sdk-typed-proof: RunFailed / WaitedRun not exported", file=sys.stderr)
        return 1

    print(
        "sdk-typed-proof: ok",
        f"env={args.env}",
        f"as={args.role}",
        f"agents={len(listed)}",
        f"me={me.get('email') or me.get('id')}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
