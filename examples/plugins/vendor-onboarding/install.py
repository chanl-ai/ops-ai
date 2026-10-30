"""Installs the vendor-onboarding example plugin into one team, through the public HTTP APIs only, then tries it.

    uv run python examples/plugins/vendor-onboarding/install.py install [--team NAME] [--origin URL]
    uv run python examples/plugins/vendor-onboarding/install.py run [--team NAME] [--decision approve|reject]

This is the stand-in for the plugin system until it exists (docs/plans/ops-ai/plugins.html, proposed): it reads
plugin.yaml, installs each contribution with the routes scripts/sample_team.py uses, replaces `@kind/id` references
with the ids the team got, and publishes each record through the review it needs. Each line says MADE, FOUND or FAIL,
and a second run finds everything. `run` starts the workflow as a test run, prints each step's output, decides the
human review as the approver and waits for the run to end.

People: the first admin from --admin-env (.run/dev-admin.env, written by `make up`), building as --builder and deciding
as --approver, both members of the team, whose password is OPS_DEMO_PASSWORD in the same file (`make sample-team`
makes all three). A Security admin step (egress host, secret, module reviews) is done by the first admin acting in the
workspace's Security team, as a Security admin would in the console.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sample_team as st  # noqa: E402 - the sample-team installer's sign-in, envelope and review helpers

MANIFEST = yaml.safe_load((HERE / "plugin.yaml").read_text())
# `@kind/id` or `@kind/id#operation` inside a contribution: a record this plugin brings.
REFS: dict[str, str] = {}


def contribution(kind: str) -> tuple[dict[str, Any], Path]:
    entry = next(c for c in MANIFEST["contributions"] if c["kind"] == kind)
    path = HERE / entry["path"]
    return yaml.safe_load(path.read_text()), path


def resolved(value: Any) -> Any:
    """`value` with each plugin reference replaced by the team's id or operation name."""
    if isinstance(value, str):
        for ref, real in REFS.items():
            value = value.replace(ref, real)
        if "@" in value and value.lstrip('"').startswith("@"):
            raise SystemExit(f"install: {value} names nothing this plugin has installed yet")
        return value
    if isinstance(value, list):
        return [resolved(v) for v in value]
    if isinstance(value, dict):
        return {k: resolved(v) for k, v in value.items()}
    return value


# ── People ───────────────────────────────────────────────────────────────────────────────────────────────────────


class People:
    def __init__(self, args: argparse.Namespace) -> None:
        env = st.admin_env(args.admin_env)
        urls = st.service_urls(args.origin)
        email, password = env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"]
        admin = st.sign_in(urls, email, password)
        teams = st.items(st.data(admin("platform").get("/v1/settings/teams", params={"search": args.team})))
        team = next((t for t in teams if t["name"].lower() == args.team.lower()), None)
        if team is None:
            raise SystemExit(f"install: no team named {args.team}; `make sample-team` makes Customer Operations")
        self.team = str(team["id"])
        self.admin = st.sign_in(urls, email, password, self.team)
        st.ADMIN.append(self.admin)
        security_team = str(st.data(self.admin("platform").get("/v1/settings/workspace-teams"))["securityTeam"])
        self.security = st.sign_in(urls, email, password, security_team)
        self.builder = st.sign_in(urls, args.builder, env["OPS_DEMO_PASSWORD"], self.team)
        self.approver = st.sign_in(urls, args.approver, env["OPS_DEMO_PASSWORD"], self.team)


# ── Contributions ────────────────────────────────────────────────────────────────────────────────────────────────


def ensure_egress(p: People) -> None:
    """The plugin's declared hosts on the workspace's egress list: a module may only name a host that is on it."""
    tools = p.security("tools")
    have = {x["host"] for x in st.data(tools.get("/v1/egress"))["hosts"]}
    for host in MANIFEST["permissions"]["egress"]:
        if host in have:
            st.say("FOUND", f"egress {host}")
            continue
        note = f"{MANIFEST['title']} plugin ({MANIFEST['id']})"
        st.data(tools.post("/v1/egress/hosts", json={"value": host, "note": note}))
        st.say("MADE", f"egress {host}", note)


def ensure_secrets(p: People) -> None:
    """Each secret the plugin requires, as the team's own; the value comes from the environment, never the plugin."""
    for need in (r for r in MANIFEST["requires"] if r["kind"] == "secret"):
        value = os.environ.get(need["name"]) or "dev-registry-key"
        st.ensure_team_secret(p.admin, p.team, need["name"], value)


def find_module(p: People, name: str) -> dict[str, Any] | None:
    listed = st.items(st.data(p.builder("tools").get("/v1/tool-modules", params={"search": name, "pageSize": 50})))
    return next((m for m in listed if m["name"] == name), None)


def publish_module(p: People, module_id: str, what: str) -> None:
    """A module goes live through the workspace Security team's review, as any module does."""
    api = p.builder("tools")
    st.data(api.post(f"/v1/tool-modules/{module_id}/reviews", json={"note": f"From the {MANIFEST['title']} plugin."}))
    waiting = next(
        v for v in st.data(api.get(f"/v1/tool-modules/{module_id}"))["versions"] if v["status"] == "in_review"
    )
    decided = p.security("agents").post(
        f"/v1/publish-requests/{waiting['reviewId']}/decision",
        json={"decision": "approved", "reason": "Checked the plugin's declared hosts, operations and secrets."},
    )
    st.say("MADE" if decided.status_code < 300 else "FAIL", f"{what} publish", str(decided.status_code))


HTTP_OP_FIELDS = ("name", "description", "access", "method", "url", "headers", "body")


def ensure_tool_module(p: People) -> None:
    spec, _ = contribution("tool-module")
    ops = spec["operations"]
    for op in ops:
        REFS[f"@tool-module/{spec['name']}#{op['name']}"] = op["name"]
    api = p.builder("tools")
    found = find_module(p, spec["name"])
    if found is None:
        first = {k: op_v for k, op_v in ops[0].items() if k in HTTP_OP_FIELDS}
        body = {k: spec[k] for k in ("name", "displayName", "system", "type", "endpoint")} | {"http": first}
        found = st.data(api.post("/v1/tool-modules", json=body))
        for op in ops[1:]:
            st.data(
                api.post(
                    f"/v1/tool-modules/{found['id']}/operations", json={k: op[k] for k in HTTP_OP_FIELDS if k in op}
                )
            )
        st.say("MADE", f"tool module {spec['displayName']}", f"{found['id']}, {len(ops)} operations")
    if found.get("status") == "published":
        st.say("FOUND", f"tool module {spec['displayName']}", f"{found['id']} published")
    else:
        publish_module(p, str(found["id"]), f"tool module {spec['displayName']}")
    ensure_mocks(p, str(found["id"]), spec.get("mocks") or {})


def ensure_mocks(p: People, module_id: str, mocks: dict[str, list[dict[str, Any]]]) -> None:
    """Test-run answers per operation. Mocks are not module versions, so they need no review."""
    api = p.builder("tools")
    by_name = {o["name"]: o for o in st.data(api.get(f"/v1/tool-modules/{module_id}"))["operations"]}
    for op_name, wanted in mocks.items():
        route = f"/v1/tool-modules/{module_id}/operations/{by_name[op_name]['id']}/mocks"
        have = {m["name"] for m in st.items(st.data(api.get(route)))}
        for mock in wanted:
            if mock["name"] in have:
                st.say("FOUND", f"mock {op_name}: {mock['name']}")
                continue
            st.data(api.post(route, json={"environment": "test", **mock}))
            st.say("MADE", f"mock {op_name}: {mock['name']}")


def ensure_code_module(p: People) -> None:
    spec, path = contribution("code-module")
    fn = spec["function"]
    REFS[f"@code-module/{spec['name']}#{fn['name']}"] = fn["name"]
    found = find_module(p, spec["name"])
    if found is not None and found.get("status") == "published":
        st.say("FOUND", f"code module {spec['displayName']}", f"{found['id']} published")
        return
    code = dict(fn["code"])
    code["source"] = (path.parent / code["source"]).resolve().read_text()
    code["bindings"] = resolved(code.get("bindings") or [])
    body = {k: spec[k] for k in ("name", "displayName", "system", "type")} | {
        "endpoint": "",
        "function": {k: v for k, v in fn.items() if k != "code"} | {"code": code},
    }
    module = found or st.data(p.builder("tools").post("/v1/tool-modules", json=body))
    st.say("MADE" if found is None else "FOUND", f"code module {spec['displayName']}", str(module["id"]))
    publish_module(p, str(module["id"]), f"code module {spec['displayName']}")


def ensure_agent(p: People, model: str) -> None:
    spec, _ = contribution("agent")
    entry = next(c for c in MANIFEST["contributions"] if c["kind"] == "agent")
    api = p.builder("agents")
    listed = st.items(st.data(api.get("/v1/agents", params={"search": spec["name"], "pageSize": 50})))
    found = next((a for a in listed if a["name"] == spec["name"] and a.get("teamId") == p.team), None)
    if found is not None and st.data(api.get(f"/v1/agents/{found['id']}")).get("publishedVersion"):
        REFS[f"@agent/{entry['id']}"] = str(found["id"])
        st.say("FOUND", f"agent {spec['name']}", f"{found['id']} published")
        return
    if found is None:
        body = {k: spec[k] for k in ("name", "role", "channels", "instructions")} | {"model": model}
        found = st.data(api.post("/v1/agents", json=body))
        st.say("MADE", f"agent {spec['name']}", f"{found['id']} on model alias {model}")
    patched = st.data(
        api.patch(f"/v1/agents/{found['id']}", json={"memory": spec["memory"], "note": "From the plugin."})
    )
    review = st.data(api.post(f"/v1/agents/{found['id']}/publish-requests", json={"version": patched["version"]}))
    st.decide_publish(p.approver, review, f"agent {spec['name']}")
    REFS[f"@agent/{entry['id']}"] = str(found["id"])


def ensure_workflow(p: People) -> str:
    _, path = contribution("workflow")
    text = resolved(path.read_text())
    wid = yaml.safe_load(text)["id"]
    api = p.builder("agents")
    found = api.get(f"/v1/workflows/definitions/{wid}")
    if found.status_code == 200 and st.data(found).get("stage") == "live":
        st.say("FOUND", f"workflow {wid}", f"v{st.data(found)['version']} live")
        return wid
    made = st.data(api.post("/v1/workflows/definitions", json={"yaml": text}))
    st.say("MADE", f"workflow {wid}", f"v{made.get('version')}")
    asked = st.data(api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={"note": "From the plugin."}))
    st.decide_publish(p.approver, asked, f"workflow {wid}")
    return wid


def install(args: argparse.Namespace) -> int:
    p = People(args)
    try:
        ensure_egress(p)
        ensure_secrets(p)
        ensure_tool_module(p)
        ensure_code_module(p)
        ensure_agent(p, args.model)
        ensure_workflow(p)
    except st.Refused as e:
        st.say("FAIL", "install", str(e))
    print(f"\n{len(st.FAILED)} failed", flush=True)
    return len(st.FAILED)


# ── Try it ───────────────────────────────────────────────────────────────────────────────────────────────────────

SAMPLE_VENDOR = {
    "legalName": "Brightwater Logistics Ltd",
    "country": "CA",
    "registrationNumber": "RC-1048213",
    "annualSpend": 120000,
}


def show(label: str, value: Any) -> None:
    print(f"  {label}: {json.dumps(value, ensure_ascii=False)[:600]}", flush=True)


def try_run(args: argparse.Namespace) -> int:
    """A test run (tool calls answered by the module's mocks, the model by the stack's alias), the human review
    decided by the approver, and the run's end."""
    p = People(args)
    _, path = contribution("workflow")
    wid = yaml.safe_load(path.read_text())["id"]
    vendor = json.loads(args.vendor) if args.vendor else SAMPLE_VENDOR
    started = st.data(
        p.builder("agents").post("/v1/runs", json={"workflowId": wid, "mode": "test", "input": {"vendor": vendor}})
    )
    run_id = str(started["runId"])
    print(f"run {run_id} started ({wid} v{started['version']}, test mode)", flush=True)
    run = st.run_until(p.builder, run_id, {"waiting", "succeeded", "failed", "cancelled"})
    if run is None or run["status"] != "waiting":
        print(f"FAIL the run did not reach the human review: {json.dumps(run)[:1500]}")
        return 1
    print(f"run {run_id} is {run['status']}", flush=True)
    for step in run.get("steps") or []:
        if step.get("nodeId") in {"lookup", "score", "notes"}:
            show(f"{step['nodeId']} ({step.get('status')})", step.get("output"))
    review_id = f"{run_id}:review:1"
    st.decide(p.approver, review_id, {"decision": args.decision, "reason": "Checked the registry record and score."})
    print(f"review {review_id} decided by {p.approver.email}: {args.decision}", flush=True)
    run = st.run_until(p.builder, run_id, {"succeeded", "failed", "cancelled"})
    if run is None:
        print("FAIL the run did not end after the review")
        return 1
    print(f"run {run_id} ended {run['status']}, outcome {run.get('outcome')}", flush=True)
    return 0 if run["status"] == "succeeded" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["install", "run"])
    console = f"http://localhost:{os.environ.get('OPS_CONSOLE_PORT', '3016')}"
    run_dir = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run")
    ap.add_argument("--origin", default=console, help=f"the install's public address (default {console})")
    ap.add_argument("--admin-env", type=Path, default=run_dir / "dev-admin.env")
    ap.add_argument("--team", default="Customer Operations")
    ap.add_argument("--builder", default="jordan.ellis@harborpine.example")
    ap.add_argument("--approver", default="riley.chen@harborpine.example")
    # The sample team points bank-assist at the fake model on a local stack; never leave an agent on a real model here.
    ap.add_argument("--model", default="bank-assist", help="the team's model alias the agent answers on")
    ap.add_argument("--vendor", help="run: the vendor as JSON (default a clean Canadian supplier)")
    ap.add_argument("--decision", default="approve", choices=["approve", "reject"])
    args = ap.parse_args()
    return install(args) if args.command == "install" else try_run(args)


if __name__ == "__main__":
    sys.exit(main())
