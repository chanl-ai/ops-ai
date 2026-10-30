"""The commit gate runs only the checks the staged paths can affect (c-566), by failure mode: a docs-only commit runs
the console's typecheck and tests anyway; a docs-only commit with a private path in it gets through once the full
scans are skipped; a console change no longer runs the console's typecheck; a staged test with a type error reaches
HEAD; a typed file that is clean fails because one module reads as two. Each case stages its change in a private index
over HEAD and runs scripts/verify-staged.sh on it, as the pre-commit hook does; the working tree is untouched."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_RAN = "\N{INFORMATION SOURCE} tests"  # node --test's summary line, printed by the console's verify


def gate(tmp_path: Path, changes: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """verify-staged.sh on HEAD plus `changes` (path to full content), each written as a blob into a private index."""
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "index")}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
    for path, content in changes.items():
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input=content, capture_output=True, text=True, check=True
        ).stdout.strip()
        entry = f"100644,{blob},{path}"
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", entry], cwd=ROOT, env=env, check=True)
    return subprocess.run(
        ["bash", "scripts/verify-staged.sh"], cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )


def at_head(path: str) -> str:
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def test_a_docs_only_commit_skips_the_console_but_still_refuses_a_private_path(tmp_path: Path) -> None:
    # Assembled, so this file passes the scan itself; no .md, so check-docs does not read it as an index entry.
    private = "." + "codeloop/specs/566"
    done = gate(tmp_path, {"docs/README.md": at_head("docs/README.md") + f"\nSee `{private}`.\n"})
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "check-public-paths: 1 private path" in out, out[-2000:]
    assert CONSOLE_RAN not in out, "a docs-only commit ran the console's tests"


def test_a_console_change_still_runs_the_console_typecheck(tmp_path: Path) -> None:
    done = gate(tmp_path, {"apps/console/src/lib/c566-gate-probe.ts": 'export const n: number = "not a number";\n'})
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "c566-gate-probe.ts" in out and "TS2322" in out, out[-2000:]


def test_a_staged_test_with_a_type_error_fails_the_commit(tmp_path: Path) -> None:
    # The error kb's test_tool_sources.py took to HEAD on 10-30: a private name imported from outside its module.
    probe = "services/kb-service/tests/test_c566_typed_probe.py"
    body = "from ops_kb.app import _tools_service\n\n\ndef test_probe() -> None:\n    assert _tools_service\n"
    done = gate(tmp_path, {probe: body})
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "reportPrivateUsage" in out and "test_c566_typed_probe.py" in out, out[-2000:]


def test_a_clean_typed_file_passes_with_its_imports_read_once(tmp_path: Path) -> None:
    # Imports a settings type from a package and passes it where a service expects it: read from two paths, the same
    # class was reported as two types.
    probe = "services/kb-service/tests/test_c566_typed_probe.py"
    body = (
        "from ops_kb.app import create_kb_app\nfrom ops_service_kit.settings import Settings\n\n\n"
        "def test_probe() -> None:\n    assert create_kb_app and Settings\n"
    )
    done = gate(tmp_path, {probe: body})
    out = done.stdout + done.stderr
    assert done.returncode == 0, out[-2000:]


def test_a_gate_still_runs_when_many_files_follow_its_match(tmp_path: Path) -> None:
    # A path a gate matches, then thousands more: `printf | grep -q` under pipefail stopped writing at the first match,
    # read the broken pipe as no match and skipped the gate. A changed dependencies page must still fail its check.
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "index")}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
    page = "docs/architecture/dependencies.md"
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input=at_head(page) + "\nA probe line.\n",
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    filler = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input="x\n", capture_output=True, text=True, check=True
    ).stdout.strip()
    rows = [f"100644 {blob}\t{page}"] + [f"100644 {filler}\tzz-c566-probe/file-{n:05}.txt" for n in range(6000)]
    subprocess.run(
        ["git", "update-index", "--index-info"], cwd=ROOT, env=env, input="\n".join(rows) + "\n", text=True, check=True
    )
    done = subprocess.run(
        ["bash", "scripts/verify-staged.sh"], cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "verify-staged: sbom" in out, out[-2000:]


def test_a_new_shared_setting_without_its_k8s_files_is_refused(tmp_path: Path) -> None:
    # A setting added to the compose file's x-settings, with deploy/k8s/base left as it was.
    compose = "deploy/compose/app.yaml"
    head = at_head(compose)
    changed = head.replace(
        "  OPS_ENVIRONMENT: production\n", "  OPS_ENVIRONMENT: production\n  OPS_C566_PROBE: 'on'\n", 1
    )
    assert changed != head
    done = gate(tmp_path, {compose: changed})
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "verify-staged: k8s" in out, out[-2000:]
