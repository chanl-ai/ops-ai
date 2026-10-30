"""What the /wf-builder skill runs (c-535): draw a workflow from what a developer wants, check it with the engine,
and create it only when they say so, on the profile they name.

    uv run --with-editable sdk/python python scripts/wf_builder.py <command> ...   (the SDK comes from sdk/python)

    wf_builder.py catalog --profile local
    wf_builder.py create --file goal.json [--create] --profile local
    wf_builder.py validate --file workflows/<id>.json --profile local
    wf_builder.py run <workflow id> --input key=value ... --wait --profile local

`create` takes a goal (`{"id", "goal", "example"}`: the seeded example to adapt) or a definition, writes
`workflows/<id>.json` beside the developer, has the engine validate it, and prints its steps and ports. Nothing is
created without `--create`; on a profile that is not local (named other than `local`, or not on this machine) the
workflow id must also be typed back. Every call goes through the Python SDK on the named profile (the ops CLI is not
built yet, c-527): the node catalog is read live from that profile, never from a copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "services" / "agents-service" / "seed" / "engine_workflows.json"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def profile_of(name: str) -> dict[str, Any]:
    """The named profile from the SDK's profile file (OPS_CONFIG, or ~/.config/ops-ai/config.json), with its name."""
    # The SDK is the developer's install, not this repo's environment, so the examples check and tests run without it.
    from ops_ai._config import config_path  # noqa: PLC0415

    saved = json.loads(config_path().read_text()) if config_path().is_file() else {}
    found = cast(dict[str, Any], (saved.get("profiles") or {}).get(name) or {})
    if not found:
        raise SystemExit(f"No profile named {name} in {config_path()}; pass --profile with one that exists")
    return {**found, "name": name}


def is_local(profile: dict[str, Any]) -> bool:
    host = urlparse(str(profile.get("baseUrl") or "")).hostname or ""
    return profile.get("name") == "local" and host in LOCAL_HOSTS


def may_create(profile: dict[str, Any], workflow_id: str, *, ask: Callable[[str], str] = input) -> bool:
    """A local profile creates at once; any other asks for the workflow id typed back, and creates on nothing else."""
    if is_local(profile):
        return True
    where = f"profile {profile.get('name') or '?'} ({profile.get('baseUrl') or '?'}), team {profile.get('team') or '?'}"
    try:
        typed = ask(f"Create {workflow_id} on {where}? Type the workflow id to confirm: ")
    except EOFError:
        return False
    return typed.strip() == workflow_id


def client(profile: str) -> Any:
    from ops_ai import OpsAI  # noqa: PLC0415 - the developer's SDK install, as in profile_of

    return OpsAI(profile=profile)


def adapted(goal: dict[str, Any]) -> dict[str, Any]:
    """The seeded example the goal names, as a new workflow: its id, a name from the id, and the goal as description."""
    example = str(goal.get("example") or "two_source_match")
    seeds = cast(list[dict[str, Any]], json.loads(SEEDS.read_text()))
    found = next((s for s in seeds if s.get("id") == example), None)
    if found is None:
        raise SystemExit(f"No seeded example {example}; the examples are {', '.join(str(s['id']) for s in seeds)}")
    wid = str(goal["id"])
    drawn = {k: v for k, v in found.items() if k != "teamId"}
    return drawn | {"id": wid, "name": wid.replace("_", " ").capitalize(), "description": str(goal.get("goal") or "")}


def labels(ops: Any) -> dict[str, str]:
    return {str(t["id"]): str(t.get("label") or t["id"]) for t in ops.raw.agents.workflows_node_types()}


def summary(definition: dict[str, Any], named: dict[str, str]) -> str:
    nodes = {str(n["id"]): n for n in definition.get("nodes") or []}
    lines = [f"{definition['id']}: {definition.get('name') or ''}", "Steps:"]
    lines += [f"  - {n.get('name') or i} ({named.get(str(n['type']), n['type'])})" for i, n in nodes.items()]
    lines.append("Ports:")
    for c in definition.get("connections") or []:
        src, dst = c["from"], c["to"]
        start, end = nodes[src["node"]].get("name") or src["node"], nodes[dst["node"]].get("name") or dst["node"]
        lines.append(f"  - {start} --{src['port']}--> {end}")
    return "\n".join(lines)


def validated(ops: Any, definition: dict[str, Any]) -> list[dict[str, Any]]:
    """The engine's checks that fail the definition (warnings are printed, not counted)."""
    answer = ops.raw.agents.workflows_validate_definition({"definition": definition})
    checks = cast(list[dict[str, Any]], answer.get("checks") or [])
    for c in checks:
        print(f"{c.get('level', 'error')}: {c.get('message')}", file=sys.stderr)
    return [c for c in checks if c.get("level", "error") == "error"]


def cmd_create(args: argparse.Namespace) -> int:
    given = cast(dict[str, Any], json.loads(Path(args.file).read_text()))
    definition = given if given.get("nodes") else adapted(given)
    out = Path("workflows") / f"{definition['id']}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(definition, indent=2) + "\n")
    ops = client(args.profile)
    print(summary(definition, labels(ops)))
    if validated(ops, definition):
        print(f"{out} does not pass the engine's checks; nothing was created.", file=sys.stderr)
        return 1
    print(f"Wrote {out}, validated clean.")
    if not args.create:
        print("Dry run: nothing was created. Add --create to create it.")
        return 0
    if not may_create(profile_of(args.profile), str(definition["id"])):
        print(f"{definition['id']} was not created: the workflow id was not typed back.", file=sys.stderr)
        return 1
    ops.raw.agents.workflows_create_definition({"definition": definition})
    print(f"Created {definition['id']} on profile {args.profile}.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    definition = cast(dict[str, Any], json.loads(Path(args.file).read_text()))
    failing = validated(client(args.profile), definition)
    print("Valid." if not failing else f"{len(failing)} check(s) fail.")
    return 1 if failing else 0


def cmd_catalog(args: argparse.Namespace) -> int:
    for t in client(args.profile).raw.agents.workflows_node_types():
        ports = ", ".join(str(p.get("name")) for p in t.get("outputs") or [])
        print(f"{t['id']} v{t.get('version')}: {t.get('label')} -> {ports}")
    return 0


def _conflicts(run: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for step in run.get("steps") or []:
        out = step.get("output") if isinstance(step, dict) else None
        for c in (out or {}).get("conflicts") or [] if isinstance(out, dict) else []:
            values = ", ".join(f"{v.get('source')} {v.get('value')}" for v in c.get("values") or [])
            found.append(f"{c.get('field')} ({values})")
    return found


def cmd_run(args: argparse.Namespace) -> int:
    ops = client(args.profile)
    values = dict(kv.split("=", 1) for kv in args.input or [])
    started = ops.runs.start(args.workflow, input=values, mode="test")
    run_id = str(started.get("runId") or started.get("id"))
    print(f"Started test run {run_id}.")
    if not args.wait:
        return 0
    run = ops.runs.wait(run_id, timeout=120)
    full = ops.raw.agents.workflows_get_engine_run(run_id)
    if run.get("status") == "waiting":
        waiting = cast(dict[str, Any], full.get("waiting") or {})
        payload = cast(dict[str, Any], waiting.get("payload") or {}) if isinstance(waiting.get("payload"), dict) else {}
        print(f"Waiting at Human review: {payload.get('title') or waiting.get('node') or ''}")
    else:
        print(f"Ended {run.get('status')}: {run.get('outcome') or ''}")
    for line in _conflicts(full):
        print(f"Disagreement: {line}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wf_builder.py", description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("catalog", "create", "validate", "run"):
        s = sub.add_parser(name)
        s.add_argument("--profile", required=True)
        if name in ("create", "validate"):
            s.add_argument("--file", required=True)
        if name == "create":
            s.add_argument("--create", action="store_true")
        if name == "run":
            s.add_argument("workflow")
            s.add_argument("--input", action="append")
            s.add_argument("--wait", action="store_true")
    args = p.parse_args(argv)
    return {"catalog": cmd_catalog, "create": cmd_create, "validate": cmd_validate, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
