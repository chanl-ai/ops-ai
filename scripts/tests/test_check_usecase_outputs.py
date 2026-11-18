"""check_usecase_outputs.py, by failure mode: a UI use case saved screenshots into tracked docs/, so every run left
the tree dirty with rewritten images, and a script wrote under another case's id so two cases shared one folder."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = "docs/usecases/console/scripts"
ROOTED = "const SHOTS = evidenceDir('227', 'screens');\nmkdirSync(SHOTS, { recursive: true });\n"
ROOTED += "await page.screenshot({ path: join(SHOTS, 'a.png') });\n"
TRACKED = "const SHOTS = join(ROOT, 'docs/console/proposed/files');\nmkdirSync(SHOTS, { recursive: true });\n"
TRACKED += "await page.screenshot({ path: join(SHOTS, 'a.png') });\n"
OTHER_ID = ROOTED.replace("'227'", "'261'")
PY_TEMP = "folder = Path(tempfile.mkdtemp())\n(folder / 'a.txt').write_text('x')\n"
PY_CHECKOUT = "folder = ROOT / 'examples'\n(folder / 'a.txt').write_text('x')\n"


def run(tmp: Path, body: str, name: str = "test-uc-227-ui.mjs") -> tuple[int, str]:
    path = tmp / SCRIPTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_usecase_outputs.py"), "--root", str(tmp)],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout


def test_screenshots_into_a_tracked_docs_folder_fail(tmp_path: Path) -> None:
    code, out = run(tmp_path, TRACKED)
    assert code == 1 and "test-uc-227-ui.mjs" in out and "screenshot writes to" in out, out


def test_a_script_writing_under_another_cases_id_fails(tmp_path: Path) -> None:
    code, out = run(tmp_path, OTHER_ID)
    assert code == 1 and "its own id, 227" in out, out


def test_python_writes_pass_in_a_temp_dir_and_fail_in_the_checkout(tmp_path: Path) -> None:
    assert run(tmp_path, PY_TEMP, "test-uc-227-api.py")[0] == 0
    code, out = run(tmp_path, PY_CHECKOUT, "test-uc-227-api.py")
    assert code == 1 and "write_text writes to" in out, out


def test_a_script_on_the_evidence_root_passes(tmp_path: Path) -> None:
    assert run(tmp_path, ROOTED)[0] == 0
