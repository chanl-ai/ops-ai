"""uc-581, cli layer: docs/usecases/tools-service/agents-query-salesforce-many-ways.md, story S5 (steps 18-21). A
developer runs `ops plugin validate` on copies of the Salesforce plugin from the ops-ai-plugins repository beside
ops-ai, each changed one way that would let a model's value change a query or leave a listing unable to page, and is
told the field each time. Nothing starts; no model call."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from usecase_harness import check, finish

ROOT = Path(__file__).resolve().parents[4]
PLUGIN = ROOT.parent / "ops-ai-plugins" / "plugins" / "salesforce" / "src" / "ops_plugin_salesforce"
# find_cases' status input, as the manifest writes it, and the same input with its list taken away.
FIND = "    description: Cases in a status changed after a time, oldest change first, a page at a time\n"
FIND += "    access: read\n    input:\n"
STATUS = '      status: { type: string, enum: [New, Working, Escalated, Closed], description: "The cases\' status" }'
UNCHECKED = '      status: { type: string, description: "The cases\' status" }'


def validate(folder: Path) -> subprocess.CompletedProcess[str]:
    argv = ["uv", "run", "--quiet", "ops", "plugin", "validate", str(folder)]
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)


def broken(tmp: Path, name: str, old: str, new: str) -> Path:
    """A copy of the plugin with one change to its manifest; the change must apply exactly once."""
    folder = tmp / name / "ops_plugin_salesforce"
    shutil.copytree(PLUGIN, folder, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = folder / "plugin.yaml"
    text = manifest.read_text()
    assert text.count(old) == 1, f"{name}: the change {old!r} is not in the manifest once"
    manifest.write_text(text.replace(old, new))
    return folder


with tempfile.TemporaryDirectory(prefix="uc581-") as t:
    tmp = Path(t)
    good = validate(PLUGIN)
    check(
        "the Salesforce plugin as it is validates",
        good.returncode == 0 and "OK opsai.salesforce" in good.stdout,
        {"out": good.stdout[-300:], "err": good.stderr[-300:]},
    )
    cases = [
        (
            "18 a link paging rule that names no answer field is refused",
            broken(
                tmp,
                "no-next",
                "      paging: { rule: link, next: nextRecordsUrl }\n  - name: find_cases_with_deleted",
                "      paging: { rule: link }\n  - name: find_cases_with_deleted",
            ),
            "a link rule names the answer field",
        ),
        (
            "19 a query input with no list or format is refused, naming it",
            broken(tmp, "unchecked", f"title: Find cases\n{FIND}{STATUS}", f"title: Find cases\n{FIND}{UNCHECKED}"),
            "status is used in a query and needs an enum or a format",
        ),
        (
            "20 a search term with only a pattern is refused",
            broken(
                tmp,
                "pattern-only",
                '    input: { term: { type: string, format: sosl_term, description: "The word or phrase to find" } }',
                '    input: { term: { type: string, pattern: "^[a-z]+$", description: "The word or phrase to find" } }',
            ),
            "term has only a pattern, which is for path segments",
        ),
        (
            "21 an input nested four levels deep is refused",
            broken(
                tmp,
                "too-deep",
                '    input: { object: { type: string, description: "The object, such as Case" } }\n'
                '    request: { method: GET, path: "/sobjects/{object}/describe" }',
                '    input:\n      object: { type: string, description: "The object, such as Case" }\n'
                "      deep: { type: object, required: false, properties: { a: { type: object, properties: { b: "
                "{ type: object, properties: { c: { type: object, properties: { d: { type: string } } } } } } } } }\n"
                '    request: { method: GET, path: "/sobjects/{object}/describe" }',
            ),
            "deep nests past three levels",
        ),
    ]
    for name, folder, said in cases:
        got = validate(folder)
        check(name, got.returncode != 0 and said in got.stdout + got.stderr, {"out": got.stdout[-500:]})

finish()
