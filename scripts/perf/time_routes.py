"""Times the routes behind the console's busiest screens on any install, signed in as a workspace admin (c-451).

    uv run python scripts/perf/time_routes.py --origin http://localhost:3016 --admin-env .run/demo.env
    uv run python scripts/perf/time_routes.py --origin https://<staging host> --admin-env <file> --runs 9

`--origin` and `--admin-env` are the seed's (scripts/demo/seed_demo_team.py): an origin that serves `/api/<service>/`,
or a local console whose services sit on their own ports, and a file holding OPS_DEMO_ADMIN_EMAIL and
OPS_DEMO_ADMIN_PASSWORD. The admin acts in `--team` (a name or id; default the demo team). Each route is called once to
warm up, then `--runs` times in turn; the table gives each route's median and max in milliseconds and its status. The
exit status is the number of routes whose median is over `--budget-ms` or that answered an error. The password is
never printed.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "demo"))
from seed_demo_team import data, read_env, service_urls, sign_in  # noqa: E402

DEMO_TEAM = "Customer Operations"


@dataclass(frozen=True)
class Route:
    name: str
    service: str
    path: str
    params: dict[str, Any]


# The calls the console makes on Overview, Reviews, Agents, Runs and Knowledge, with two fast lists for comparison.
ROUTES = [
    Route("reviews open count", "agents", "/reviews", {"view": "open", "page": 1, "pageSize": 1}),
    Route("reviews open list", "agents", "/reviews", {"view": "open", "page": 1, "pageSize": 25}),
    Route("reviews resolved", "agents", "/reviews", {"view": "resolved", "page": 1, "pageSize": 25}),
    Route("agents list", "agents", "/v1/agents", {"page": 1, "pageSize": 25}),
    Route("runs list", "agents", "/runs", {"page": 1, "pageSize": 25}),
    Route("kb bases", "kb", "/v1/knowledge-bases", {"page": 1, "pageSize": 25}),
    Route("platform me", "platform", "/v1/me", {}),
    Route("cases (compare)", "agents", "/v1/cases", {"page": 1, "pageSize": 25}),
    Route("files (compare)", "files", "/v1/files", {"page": 1, "pageSize": 25}),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--origin", required=True)
    p.add_argument("--admin-env", type=Path, required=True)
    p.add_argument("--team", default=DEMO_TEAM, help="team name or id the admin acts in")
    p.add_argument("--runs", type=int, default=7)
    p.add_argument("--budget-ms", type=float, default=300.0)
    p.add_argument("--only", help="comma-separated route names to time")
    p.add_argument(
        "--together", action="store_true", help="each run calls every route at once, as a page load does, not in turn"
    )
    args = p.parse_args()

    env = read_env(args.admin_env)
    urls = service_urls(args.origin)
    who = sign_in(urls, env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"])
    teams = data(who("platform").get("/v1/me"))["teams"]
    team = next((t for t in teams if args.team in (t["id"], t["name"])), None)
    if team is None:
        raise SystemExit(f"time_routes: the admin is not in team {args.team!r}")
    who.team = team["id"]
    routes = [r for r in ROUTES if not args.only or r.name in args.only.split(",")]

    took: dict[str, list[float]] = {r.name: [] for r in routes}
    status: dict[str, int] = {r.name: 0 for r in routes}

    def call(r: Route) -> None:
        start = time.perf_counter()
        resp = who(r.service).get(r.path, params=r.params)
        took[r.name].append((time.perf_counter() - start) * 1000)
        status[r.name] = max(status[r.name], resp.status_code)

    for r in routes:
        who(r.service).get(r.path, params=r.params)
    if args.together:
        # One client per route, so the calls run at once over separate connections as a browser's do.
        with ThreadPoolExecutor(len(routes)) as pool:
            for _ in range(args.runs):
                list(pool.map(call, routes))
    else:
        for r in routes:
            for _ in range(args.runs):
                call(r)

    over = 0
    mode = "at once" if args.together else "in turn"
    print(f"{'route':<22} {'median ms':>10} {'max ms':>8}  status   (team {team['name']}, {args.runs} runs {mode})")
    for r in routes:
        median = statistics.median(took[r.name])
        bad = status[r.name] >= 400 or (median > args.budget_ms and "compare" not in r.name)
        over += bad
        flag = "  OVER" if bad else ""
        print(f"{r.name:<22} {median:>10.0f} {max(took[r.name]):>8.0f}  {status[r.name]}{flag}")
    return over


if __name__ == "__main__":
    sys.exit(main())
