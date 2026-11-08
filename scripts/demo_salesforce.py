"""Sets the local stack up for the Salesforce plugin demo (`make demo-salesforce`), from scratch or again.

    make demo-salesforce              fake Salesforce (docs/usecases/lib/fake_salesforce.py) on this machine
    make demo-salesforce SF=real      your own Salesforce org; Ops AI's connected app is install config, so .env names
                                      it: OPS_PLUGIN_CLIENTS='{"opsai.salesforce":{"id":"...","secret":"..."}}'
    make demo-salesforce RESET=1      also removes the team's Salesforce connection and template copies, so the
                                      Connect dialog and the template install start again from nothing

What it does, each step a no-op when already done: the plugins repo cloned at PLUGIN_REF (.run/plugins/ops-ai-plugins)
and the Salesforce plugin installed from it into the stack's plugins folder with `ops plugin install`; the fake
Salesforce kept running in the background, which the stack trusts and resolves while it runs (scripts/stack.sh);
tools, agents, the worker, kb and documents restarted when the plugin or the fake changed; the demo's model alias
`salesforce-demo` on its own connection to the fake model, so the case helper's chat turns never reach a real provider;
the plugin's hosts listed for egress.

The team admin's steps (connect in the dialog, add the templates, publish) are the demo itself and are left to the
walk (scripts/demo-salesforce/walk.mjs) or a person. No key, secret or password is printed.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / os.environ.get("OPS_RUN_DIR", ".run")
# The team the demo runs in (DEMO_TEAM), and its people. The default is the dev seed's Operations team, whose people
# the console's "Sign in as a demo person" offers with no password typed; the sample team (make sample-team) also works.
TEAMS: dict[str, dict[str, str]] = {
    "Operations": {
        "lead": "p.shah@harborpine.example",
        "builder": "j.richardson@harborpine.example",
        "approver": "m.okafor@harborpine.example",
    },
    "Customer Operations": {
        "lead": "alex.morgan@harborpine.example",
        "builder": "jordan.ellis@harborpine.example",
        "approver": "riley.chen@harborpine.example",
    },
    # A first team (make sample-teams): its people sign in with the dev seed's password.
    "Wealth Advisory": {
        "lead": "helena.brooks@harborpine.example",
        "builder": "omar.haddad@harborpine.example",
        "approver": "helena.brooks@harborpine.example",
    },
}
# Teams whose people sign in with the dev seed's password rather than the sample team's generated one.
SEED_PASSWORD_TEAMS = ("Operations", "Wealth Advisory")
TEAM_NAME = os.environ.get("DEMO_TEAM") or "Operations"
PEOPLE = TEAMS[TEAM_NAME]
LEAD, APPROVER = PEOPLE["lead"], PEOPLE["approver"]
PLUGIN = "opsai.salesforce"
PLUGIN_REPO = "https://github.com/chanl-ai/ops-ai-plugins.git"
PLUGIN_REF = os.environ.get("PLUGIN_REF") or "feat/salesforce-triage-workflow"
PLUGIN_CLONE = RUN / "plugins" / "ops-ai-plugins"
PLUGIN_DIR = PLUGIN_CLONE / "plugins" / "salesforce" / "src" / "ops_plugin_salesforce"
# The install's one plugins folder, which the stack's services load from (scripts/stack.sh).
PLUGINS = Path(os.environ.get("OPS_PLUGINS_DIR") or Path(os.environ.get("STACK_HOME") or ROOT) / "plugins")
FAKE_DIR = RUN / "fake-salesforce"
REAL_ENV = Path.home() / ".config" / "ops-ai" / "salesforce.env"
# Every service that reads the plugins switch: tools-service loads plugins, agents-service and documents-service list
# their templates, kb-service reads their knowledge sources, and the worker runs workflow steps that call their tools.
PLUGIN_SERVICES = ("tools", "agents", "worker", "kb", "documents")
DEMO_ALIAS = "salesforce-demo"
DEMO_PROVIDER = "salesforce-demo-fake"


def port(name: str, default: int) -> int:
    return int(os.environ.get(f"OPS_{name}_PORT") or default)


PLATFORM = f"http://127.0.0.1:{port('PLATFORM', 8710)}"
TOOLS = f"http://127.0.0.1:{port('TOOLS', 8720)}"
AGENTS = f"http://127.0.0.1:{port('AGENTS', 8700)}"
MODELS = f"http://127.0.0.1:{port('MODELS', 8730)}"
FAKE_MODEL = os.environ.get("OPS_MODELS_FAKE_OPENAI_URL") or f"http://127.0.0.1:{port('FAKE_OPENAI', 8746)}/v1"
CONSOLE = f"http://localhost:{port('CONSOLE', 3016)}"


def say(status: str, what: str) -> None:
    print(f"  {status:<5} {what}", flush=True)


def read_env(path: Path) -> dict[str, str]:
    """KEY=value lines; values are kept in memory only, never printed."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m[1]] = m[2].strip().strip('"').strip("'")
    return out


def data(r: httpx.Response, what: str, ok: tuple[int, ...] = (200, 201)) -> Any:
    if r.status_code not in ok:
        raise SystemExit(
            f"FAIL  {what}: {r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}"
        )
    return r.json().get("data") if r.content else None


# ── console, plugin folder ──


def plugin_folder() -> bool:
    """Clones the plugins repo once and installs the Salesforce plugin from it; True when the installed copy changed."""
    if not PLUGIN_CLONE.exists():
        PLUGIN_CLONE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", PLUGIN_REPO, str(PLUGIN_CLONE)], check=True)
        subprocess.run(["git", "-C", str(PLUGIN_CLONE), "checkout", "-q", PLUGIN_REF], check=True)
        say("MADE", f"plugins repo cloned at {PLUGIN_REF}")
    head = subprocess.run(
        ["git", "-C", str(PLUGIN_CLONE), "log", "-1", "--format=%h %s"], capture_output=True, text=True, check=False
    )
    checked = subprocess.run(
        [
            "uv",
            "run",
            "--quiet",
            "ops",
            "plugin",
            "validate",
            str(PLUGIN_DIR.parents[1]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    line = (checked.stdout.strip() or checked.stderr.strip()).splitlines()[-1:] or ["(no output)"]
    if checked.returncode != 0:
        raise SystemExit(f"FAIL  ops plugin validate: {line[0]}")
    say("OK", f"plugin {head.stdout.strip()}; ops plugin validate: {line[0]}")
    if same_tree(PLUGIN_DIR, PLUGINS / PLUGIN_DIR.name):
        say("FOUND", f"plugin installed in {PLUGINS}")
        return False
    done = subprocess.run(
        ["uv", "run", "--quiet", "ops", "plugin", "install", str(PLUGIN_DIR.parents[1]), "--into", str(PLUGINS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"FAIL  ops plugin install: {(done.stdout + done.stderr).strip()[-300:]}")
    say("MADE", f"plugin installed in {PLUGINS}")
    return True


def same_tree(a: Path, b: Path) -> bool:
    """Whether folder `b` holds exactly the files of `a`, caches aside."""

    def files(root: Path) -> dict[str, bytes]:
        return {
            str(f.relative_to(root)): f.read_bytes()
            for f in root.rglob("*")
            if f.is_file() and "__pycache__" not in f.parts
        }

    return b.is_dir() and files(a) == files(b)


# ── the fake Salesforce ──


def fake_info() -> dict[str, Any] | None:
    """The running fake's printed settings, or None when it is not running or does not answer."""
    path = FAKE_DIR / "info.json"
    if not path.exists() or not path.read_text().strip():
        return None
    info: dict[str, Any] = json.loads(path.read_text().splitlines()[0])
    try:
        os.kill(int(info["owner"]), 0)
        url = urlsplit(str(info["control"]))
        got = httpx.get(str(info["control"]), headers={"Host": "login.salesforce.test"}, verify=False, timeout=5)
        if got.status_code != 200 or not url.hostname:
            return None
    except (OSError, httpx.HTTPError):
        return None
    return info


def fake_salesforce() -> tuple[dict[str, Any], bool]:
    """The running fake, and True when it was started here (tools-service then restarts to trust and resolve it)."""
    if (info := fake_info()) is not None:
        say("FOUND", f"fake Salesforce running (pid {info['owner']})")
        return info, False
    stop_fake()
    FAKE_DIR.mkdir(parents=True, exist_ok=True)
    out, log = FAKE_DIR / "info.json", ROOT / ".logs" / "fake-salesforce.log"
    log.parent.mkdir(exist_ok=True)
    script = ROOT / "docs" / "usecases" / "lib" / "fake_salesforce.py"
    # The fake serves until its stdin closes; a pipe from `tail -f /dev/null` keeps it open after this script ends.
    command = f"tail -f /dev/null | exec uv run --quiet --directory services/agents-service python {script}"
    with out.open("w") as o, log.open("a") as e:
        subprocess.Popen(["sh", "-c", command], cwd=ROOT, stdout=o, stderr=e, start_new_session=True)
    for _ in range(120):
        if (info := fake_info()) is not None:
            shutil.copyfile(info["ca"], FAKE_DIR / "ca.pem")
            say("MADE", f"fake Salesforce started (pid {info['owner']}, log .logs/fake-salesforce.log)")
            return info, True
        time.sleep(1)
    raise SystemExit("FAIL  the fake Salesforce did not start; see .logs/fake-salesforce.log (is Docker running?)")


def stop_fake() -> None:
    path = FAKE_DIR / "info.json"
    if path.exists() and path.read_text().strip():
        owner = int(json.loads(path.read_text().splitlines()[0])["owner"])
        with contextlib.suppress(OSError):
            os.kill(owner, signal.SIGTERM)


# ── restarts ──


def fake_model_stale() -> bool:
    """The fake model reads its rules once at start: started before the rules last changed, it lacks the demo's."""
    pidfile, rules = RUN / "fakeai.pid", ROOT / "services/models-service/seed/demo-fake-openai/script.json"
    return not pidfile.exists() or pidfile.stat().st_mtime < rules.stat().st_mtime


def restart(plugin_changed: bool, fake_started: bool) -> None:
    stale = list(PLUGIN_SERVICES) if plugin_changed else ["tools"] if fake_started else []
    stale += ["fakeai"] if fake_model_stale() else []
    if not stale:
        say("FOUND", "plugin services running with the installed plugin and the fake")
        return
    for service in stale:
        done = subprocess.run(
            ["make", "-s", "restart", f"SVC={service}"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise SystemExit(f"FAIL  make restart SVC={service}: {(done.stdout + done.stderr)[-400:]}")
        say("MADE", f"restarted {service}")


# ── accounts ──


def sign_in(email: str, password: str) -> str:
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=20)
    return str(data(r, f"sign in as {email}")["token"])


def team_id(token: str) -> str:
    teams = data(httpx.get(f"{PLATFORM}/v1/teams", headers={"Authorization": f"Bearer {token}"}, timeout=20), "teams")
    found = next((t for t in teams if t.get("name") == TEAM_NAME), None)
    if found is None:
        raise SystemExit(f"FAIL  no team named {TEAM_NAME}; run `make sample-team` first")
    return str(found["id"])


def password() -> str:
    """The demo people's password: the dev seed's for its people, the sample team's from .run/demo.env."""
    return "northfield-demo" if TEAM_NAME in SEED_PASSWORD_TEAMS else read_env(RUN / "demo.env")["OPS_DEMO_PASSWORD"]


def how_to_sign_in() -> str:
    if TEAM_NAME in SEED_PASSWORD_TEAMS:
        return "the dev seed's password, northfield-demo"
    return "password OPS_DEMO_PASSWORD in .run/demo.env"


def heads(token: str, team: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **({"X-Team-Id": team} if team else {})}


def egress(admin: str, team: str, hosts: list[str], ranges: list[str]) -> None:
    h = heads(admin, team)
    for host in hosts:
        r = httpx.post(
            f"{TOOLS}/v1/egress/hosts", headers=h, json={"value": host, "note": "Salesforce demo"}, timeout=20
        )
        data(r, f"egress host {host}", ok=(200, 201, 409))
    for cidr in ranges:
        r = httpx.post(
            f"{TOOLS}/v1/egress/ranges", headers=h, json={"value": cidr, "note": "Salesforce demo"}, timeout=20
        )
        data(r, f"egress range {cidr}", ok=(200, 201, 409))
    say("OK", f"egress lists {', '.join(hosts + ranges)}")


# ── the demo's model alias ──


def model_alias() -> None:
    """`salesforce-demo` on a connection of its own to the fake model: the case helper's turns follow the fake's
    Salesforce rules (services/models-service/seed/demo-fake-openai/script.json) and never reach a real provider, while
    the stack's other aliases stay where they are."""
    from ops_identity import mint_service_token  # noqa: PLC0415
    from ops_identity.service_keys import dev_service_signer  # noqa: PLC0415

    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    with httpx.Client(base_url=MODELS, headers={"Authorization": f"Bearer {token}"}, timeout=20) as m:
        providers = data(m.get("/v1/models/providers"), "model providers")
        found = next((p for p in providers if p["name"] == DEMO_PROVIDER), None)
        if found is None:
            body = {"name": DEMO_PROVIDER, "type": "openai-compatible", "baseUrl": FAKE_MODEL}
            found = data(m.post("/v1/models/providers", json=body), "fake model connection")
            say("MADE", f"model connection {DEMO_PROVIDER} to the fake model")
        if m.get(f"/v1/models/aliases/{DEMO_ALIAS}/versions").status_code == 404:
            chat = data(m.get("/v1/models/aliases/default/versions"), "default alias")[-1]
            body = {"name": DEMO_ALIAS, "kind": "chat", "providerId": found["id"], "modelId": DEMO_ALIAS}
            body |= {"clearedSensitivity": chat["clearedSensitivity"], "inputPerMillion": "0", "outputPerMillion": "0"}
            data(m.post("/v1/models/aliases", json=body), "demo alias")
            say("MADE", f"model alias {DEMO_ALIAS} on the fake model")
        else:
            say("FOUND", f"model alias {DEMO_ALIAS} on the fake model")


# ── reset ──


def reset(lead: str, team: str) -> None:
    """Removes what the team admin's steps made: the template copies and the team's Salesforce connection."""
    h = heads(lead, team)
    # The copies by the names the plugin's templates give them, so the next install makes them again.
    agents = httpx.get(f"{AGENTS}/v1/agents", params={"pageSize": 200}, headers=h, timeout=20).json().get("data") or {}
    for a in agents.get("data", agents) if isinstance(agents, dict) else agents:
        if a.get("name") == "Case helper":
            httpx.delete(f"{AGENTS}/v1/agents/{a['id']}", headers=h, timeout=20)
    flows = httpx.get(f"{AGENTS}/v1/workflows/definitions", params={"pageSize": 200}, headers=h, timeout=20)
    rows = flows.json().get("data") or {}
    for f in rows.get("data", []) if isinstance(rows, dict) else rows:
        if f.get("name") == "Triage a Salesforce case":
            httpx.delete(
                f"{AGENTS}/v1/workflows/definitions/{f.get('workflowId') or f.get('id')}", headers=h, timeout=20
            )
    cards = httpx.get(f"{TOOLS}/v1/systems", headers=h, timeout=20)
    card = (
        next((c for c in (cards.json().get("data") or []) if c.get("pluginId") == PLUGIN), None)
        if cards.status_code == 200
        else None
    )
    if card and card.get("connectionId"):
        httpx.delete(f"{TOOLS}/v1/connections/{card['connectionId']}", headers=h, timeout=20)
    httpx.put(f"{TOOLS}/v1/plugins/{PLUGIN}/team", headers=h, json={"enabled": False}, timeout=20)
    say("MADE", "reset: the team's Salesforce connection and template copies removed")


# ── story 3: the team admin adds the plugin's agent and workflow as team copies, through the Python SDK ──

SOURCE = f"plugin:{PLUGIN}"


def add_templates() -> int:
    """`make demo-salesforce-templates`: what the Connect dialog's "Add to team" step will do once it is built. Lists
    the templates Salesforce brings to the team, installs the case helper (on the demo's model alias) and the triage
    workflow as the team's own drafts, and asks to publish both; a request that waits for a second person is approved
    by the team's approver, as Reviews would."""
    from ops_ai import OpsAI  # noqa: PLC0415

    secret = password()
    admin_env = read_env(RUN / "dev-admin.env")
    team = team_id(sign_in(admin_env["OPS_BOOTSTRAP_ADMIN_EMAIL"], admin_env["OPS_BOOTSTRAP_ADMIN_PASSWORD"]))
    conn: dict[str, Any] = {"base_url": "http://127.0.0.1", "services": {"platform": PLATFORM, "agents": AGENTS}}
    ops = OpsAI.sign_in(LEAD, secret, team=team, **conn)
    approver = OpsAI.sign_in(APPROVER, secret, team=team, **conn)
    # The triage workflow drafts its reply in an AI step, which a team turns on in its workflow settings first.
    lead = heads(sign_in(LEAD, secret), team)
    steps = data(httpx.get(f"{PLATFORM}/v1/policies/aiSteps", headers=lead, timeout=20), "AI steps setting")
    if (steps.get("value") or {}).get(team) is not True:
        data(
            httpx.put(f"{PLATFORM}/v1/policies/aiSteps", headers=lead, json={"value": True}, timeout=20), "AI steps on"
        )
        say("MADE", "AI steps in workflows on for the team")
    print(f"As {LEAD} in {TEAM_NAME}, through the Python SDK (ops_ai):")
    listed = [t for t in ops.raw.agents.templates_list_templates() if t["source"] == SOURCE]
    if not listed:
        raise SystemExit("FAIL  Salesforce brings no templates to the team: connect it for the team first (story 2)")
    for t in listed:
        print(f"  {t['kind']:<8} {t['title']} (v{t['version']}), copies held: {t['installed']['copies']}")
    made: dict[str, str] = {}
    for t in listed:
        body: dict[str, Any] = {"modelAlias": DEMO_ALIAS} if t["kind"] == "agent" else {}
        got = install(ops, t["id"], body)
        made[t["kind"]] = got["copy"]["recordId"]
        left = ", ".join(f"{k} {v}" for n in got["needs"] for k, v in n.items())
        say(
            "MADE" if got["created"] else "FOUND",
            f"{t['title']} as the team's {t['kind']} {got['copy']['recordId']}"
            + (f" (left to bind: {left})" if left else ""),
        )
    agent = ops.raw.agents.agents_get_agent(made["agent"]) if "agent" in made else None
    if agent and (agent.get("memory") or {}).get("enabled", True):
        # The stack's memory alias is a real model; the demo's chat stays on the fake one.
        agent = ops.raw.agents.agents_update_agent(made["agent"], {"memory": {"enabled": False}})
        say("MADE", "Case helper's memory off, so the demo's chat makes no real model call")
    if agent and agent.get("publishedVersion") != agent.get("version"):
        review = ops.raw.agents.agents_request_publish(
            made["agent"], {"version": agent["version"], "note": "Salesforce demo"}
        )
        publish_decided(approver, review, "Case helper")
    if "workflow" in made:
        try:
            review = ops.raw.agents.workflows_request_definition_publish(made["workflow"], {"note": "Salesforce demo"})  # pyright: ignore[reportArgumentType]
            publish_decided(approver, review, "Triage a Salesforce case")
        except Exception as e:  # a version already live answers 409, which is the state wanted
            live = "not_a_draft" in str(e)
            say("FOUND", "Triage a Salesforce case already live" if live else f"Triage a Salesforce case: {e}")
    return 0


def install(ops: Any, template_id: str, body: dict[str, Any]) -> Any:
    """agents-service keeps the tools a team may grant for 30 s, so right after the team turns Salesforce on its tools
    are unknown to it for that long; the install is tried again until they are offered."""
    from ops_ai.errors import BadRequest  # noqa: PLC0415

    for attempt in range(45):
        try:
            return ops.raw.agents.resources_copy_resource(f"{SOURCE}:{template_id}", body)
        except BadRequest as e:
            if "unknown_tool" not in str(e) or attempt == 44:
                raise
            time.sleep(1)
    raise AssertionError("unreachable")


def publish_decided(approver: Any, review: dict[str, Any], name: str) -> None:
    if review.get("status") == "pending":
        approver.raw.agents.reviews_decide_publish_request(review["id"], {"decision": "approved"})
        say("MADE", f"{name} published (approved by {APPROVER})")
    else:
        say("MADE", f"{name} published ({review.get('status')})")


def main() -> int:
    if sys.argv[1:] == ["templates"]:
        return add_templates()
    mode = (os.environ.get("SF") or "fake").lower()
    print(f"Salesforce demo setup ({mode}) on {CONSOLE}")
    plugin_changed = plugin_folder()
    info, fake_started = fake_salesforce() if mode == "fake" else (fake_info(), False)
    if mode == "real":
        real = read_env(REAL_ENV)
        missing = [k for k in ("SF_LOGIN", "SF_CLIENT_ID", "SF_CLIENT_SECRET") if not real.get(k)]
        if missing:
            raise SystemExit(f"FAIL  {REAL_ENV} has no value for {', '.join(missing)}")
        # Ops AI's own app for the plugin is install config, read by tools-service from .env at start.
        clients = os.environ.get("OPS_PLUGIN_CLIENTS") or ""
        if PLUGIN not in clients:
            raise SystemExit(
                f"FAIL  .env names no OPS_PLUGIN_CLIENTS for {PLUGIN}; add "
                'OPS_PLUGIN_CLIENTS=\'{"opsai.salesforce":{"id":"<SF_CLIENT_ID>","secret":"<SF_CLIENT_SECRET>"}}\' '
                f"with the values in {REAL_ENV}, then make restart SVC=tools"
            )
    restart(plugin_changed, fake_started)
    model_alias()
    admin_env = read_env(RUN / "dev-admin.env")
    admin = sign_in(admin_env["OPS_BOOTSTRAP_ADMIN_EMAIL"], admin_env["OPS_BOOTSTRAP_ADMIN_PASSWORD"])
    team = team_id(admin)
    # SF=real lists nothing: the plugin's own hosts (its sign-in and instance) pass for its own requests.
    if mode != "real" and info is not None:
        egress(admin, team, list(info["hosts"]), [str(info["range"])])
    if os.environ.get("RESET") == "1":
        lead = sign_in(LEAD, password())
        reset(lead, team)
    if mode == "real":
        print(
            f"Next: sign in as {LEAD} ({how_to_sign_in()}), open {CONSOLE}/integrations, press Connect on Salesforce "
            "and keep Ops AI's app; Salesforce asks you to sign in and Allow. Its connected app must list "
            f"{CONSOLE}/connections/connect as a callback."
        )
    print(f"Ready: {CONSOLE}/integrations as {LEAD} ({how_to_sign_in()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
