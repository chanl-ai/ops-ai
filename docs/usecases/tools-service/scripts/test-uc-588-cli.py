"""uc-588, cli layer: docs/usecases/tools-service/plugin-sign-in-methods.md, story S6 (steps 14-15). A developer runs
`ops plugin validate` on each test plugin in services/tools-service/tests/plugin_kinds, one per sign-in method, and on
two broken copies written to a temporary folder: one offering person sign-in with only an API key, which holds no
person's token, and one listing `api_key` without saying how the key is sent. No service and no model call."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from usecase_harness import check, finish

ROOT = Path(__file__).resolve().parents[4]
KINDS = ROOT / "services/tools-service/tests/plugin_kinds"


def validate(folder: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--quiet", "ops", "plugin", "validate", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# 14. Every test plugin validates, one per method.
results = {p.name: validate(p) for p in sorted(KINDS.glob("kinds_*"))}
check(
    "14 each test plugin, one per sign-in method, validates OK",
    len(results) == 8 and all(r.returncode == 0 and r.stdout.startswith("OK ") for r in results.values()),
    {name: (r.returncode, (r.stdout or r.stderr).strip()[:120]) for name, r in results.items()},
)

# 15. Two broken copies: person sign-in on a team-only method, and an API key the plugin does not say how to send.
with tempfile.TemporaryDirectory() as tmp:
    person = Path(tmp) / "uc588_person_key"
    shutil.copytree(KINDS / "kinds_header_key", person)
    manifest = (person / "plugin.yaml").read_text()
    (person / "plugin.yaml").write_text(manifest.replace("sign_in: [team]", "sign_in: [team, person]"))
    unsaid = Path(tmp) / "uc588_unsaid_key"
    shutil.copytree(KINDS / "kinds_header_key", unsaid)
    (unsaid / "plugin.yaml").write_text(manifest.replace("  api_key: { placement: header, name: X-Desk-Key }\n", ""))
    refused_person, refused_unsaid = validate(person), validate(unsaid)
check(
    "15 validate refuses person sign-in on an API key and an API key with no placement, naming the field",
    refused_person.returncode != 0
    and "connection.sign_in" in refused_person.stdout + refused_person.stderr
    and refused_unsaid.returncode != 0
    and "connection.api_key" in refused_unsaid.stdout + refused_unsaid.stderr,
    {"person": (refused_person.stdout + refused_person.stderr)[:300], "unsaid": refused_unsaid.stdout[:300]},
)

finish()
