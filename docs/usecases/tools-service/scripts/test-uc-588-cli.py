"""uc-588, cli layer: docs/usecases/tools-service/plugin-sign-in-methods.md, story S6 (steps 14-15). A developer runs
`opsai plugin validate` on each test plugin in services/tools-service/tests/plugin_kinds, one per sign-in method, and on
two broken copies written to a temporary folder: one offering person sign-in with only an API key, which holds no
person's token, and one listing `api_key` without saying how the key is sent. No service and no model call."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from apps_walk import apps_stack, ops_cli, target
from usecase_harness import check, finish

ROOT = Path(__file__).resolve().parents[4]
KINDS = ROOT / "services/tools-service/tests/plugin_kinds"


def validate(folder: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--quiet", "opsai", "plugin", "validate", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# 14. Every test plugin validates, one per method.
results = {p.name: validate(p) for p in sorted(KINDS.glob("kinds_*"))}
check(
    "14 each test plugin, one per sign-in method, validates OK",
    len(results) == 9 and all(r.returncode == 0 and r.stdout.startswith("OK ") for r in results.values()),
    {name: (r.returncode, (r.stdout or r.stderr).strip()[:120]) for name, r in results.items()},
)

# 15. Person sign-in is accepted on an API key and refused only on a method that holds no person's credential
# (client credentials); an API key the plugin does not say how to send is refused.
with tempfile.TemporaryDirectory() as tmp:
    person = Path(tmp) / "uc588_person_key"
    shutil.copytree(KINDS / "kinds_header_key", person)
    manifest = (person / "plugin.yaml").read_text()
    (person / "plugin.yaml").write_text(manifest.replace("sign_in: [team]", "sign_in: [team, person]"))
    service = Path(tmp) / "uc588_person_client"
    shutil.copytree(KINDS / "kinds_client", service)
    client = (service / "plugin.yaml").read_text()
    (service / "plugin.yaml").write_text(client.replace("sign_in: [team]", "sign_in: [team, person]"))
    unsaid = Path(tmp) / "uc588_unsaid_key"
    shutil.copytree(KINDS / "kinds_header_key", unsaid)
    (unsaid / "plugin.yaml").write_text(manifest.replace("  api_key: { placement: header, name: X-Desk-Key }\n", ""))
    person_key, refused_service, refused_unsaid = validate(person), validate(service), validate(unsaid)
check(
    "15 validate accepts person sign-in on an API key, and refuses it on client credentials and an API key with no "
    "placement, naming the field",
    person_key.returncode == 0
    and refused_service.returncode != 0
    and "connection.sign_in" in refused_service.stdout + refused_service.stderr
    and refused_unsaid.returncode != 0
    and "connection.api_key" in refused_unsaid.stdout + refused_unsaid.stderr,
    {
        "person_key": (person_key.stdout + person_key.stderr)[:300],
        "service": (refused_service.stdout + refused_service.stderr)[:300],
        "unsaid": refused_unsaid.stdout[:300],
    },
)

# 35 (group C). A person gives, lists and removes their own key with `ops accounts`, signed in as their dev role
# the way `make api` signs in, on the Apps stack (docs/usecases/lib/apps_walk.py); the key goes on standard input.
with apps_stack() as w:
    account = w.turn_on("admin", "test.person-key", signIn="person")
    key = w.m["person_keys"]["james"]
    gave, gave_out = ops_cli("builder", "accounts", "key", "plugin:test.person-key", "--key", "-", stdin=key)
    listed_code, listed = ops_cli("builder", "accounts", "list")
    removed, removed_out = ops_cli("builder", "accounts", "remove", "plugin:test.person-key")
    row = next((r for r in listed if r.get("connectionId") == account), {}) if isinstance(listed, list) else {}
    check(
        "35 `ops accounts key` takes James's key on standard input, `ops accounts list` reads it connected, `ops "
        "accounts remove` exits 0, and the key is in no output",
        account != "con_missing"
        and gave == 0
        and listed_code == 0
        and row.get("connected") is True
        and removed == 0
        and key not in str(gave_out) + str(listed) + str(removed_out),
        (target("L2"), {"key": (gave, gave_out), "list": (listed_code, listed), "remove": (removed, removed_out)}),
    )

finish()
