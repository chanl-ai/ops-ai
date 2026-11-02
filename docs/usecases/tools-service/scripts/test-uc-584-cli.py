"""uc-584, cli layer: docs/usecases/tools-service/plugin-manifest-fields.md, story S5 (steps 13-18). A developer runs
`ops plugin validate` on copies of the test plugins in services/tools-service/tests/plugin_fields, each changed one way
that would send a secret, replace the sign-in, reach a host the plugin does not list or leave a limit unread, and is
told the field each time. Nothing starts; no model call."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from usecase_harness import check, finish

ROOT = Path(__file__).resolve().parents[4]
FIELDS = ROOT / "services/tools-service/tests/plugin_fields"


def validate(folder: Path) -> subprocess.CompletedProcess[str]:
    argv = ["uv", "run", "--quiet", "ops", "plugin", "validate", str(folder)]
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)


def broken(tmp: Path, plugin: str, name: str, old: str, new: str) -> Path:
    """A copy of a test plugin with one change to its manifest; the change must apply exactly once."""
    folder = tmp / name / plugin
    shutil.copytree(FIELDS / plugin, folder, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = folder / "plugin.yaml"
    text = manifest.read_text()
    assert text.count(old) == 1, f"{name}: the change {old!r} is not in the manifest once"
    manifest.write_text(text.replace(old, new))
    return folder


with tempfile.TemporaryDirectory(prefix="uc584-") as t:
    tmp = Path(t)
    good = [validate(FIELDS / p) for p in ("fields_desk", "fields_sites", "fields_zoom")]
    check(
        "13 the three test plugins as they are validate",
        all(r.returncode == 0 and r.stdout.startswith("OK test.fields") for r in good),
        [(r.stdout[-200:], r.stderr[-200:]) for r in good],
    )
    cases = [
        ("14 a plugin header named Authorization is refused as carrying the sign-in", "fields_desk", "auth",
         "headers: { X-Api-Version:", "headers: { Authorization:", "headers.Authorization: carries the sign-in"),
        ("15 a header holding {{API_KEY}} is refused", "fields_desk", "secret",
         '"{api_version}" }', '"{{API_KEY}}" }', "holds {{"),
        ("16a a state sign-in parameter is refused", "fields_sites", "state",
         "prompt: consent }", "prompt: consent, state: mine }", "authorize_params.state: is set by the platform"),
        ("16b a lookup that reaches evil.test is refused", "fields_sites", "lookup",
         'url: "{base_url}/sites/accessible"', 'url: "https://evil.test/sites"',
         "not one of the plugin's egress hosts"),
        ("17 a limit on a transfer whose amount is called sum is refused", "fields_desk", "amount",
         "input: { amount: { type: number }, to:", "input: { sum: { type: number }, to:",
         "a number input named amount"),
        ("18 a form tool that also has a JSON body is refused", "fields_desk", "both",
         "      path: /chat.postMessage\n", '      path: /chat.postMessage\n      body: "{}"\n',
         "a JSON body or a form, not both"),
    ]  # fmt: skip
    for name, plugin, slug, old, new, says in cases:
        r = validate(broken(tmp, plugin, slug, old, new))
        check(name, r.returncode == 1 and says in r.stdout + r.stderr, {"out": r.stdout[-400:], "err": r.stderr[-300:]})

finish()
