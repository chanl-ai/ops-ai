"""`make version`, `update-url`, `update-download` and `update-from-diff` (scripts/update_from_diff.sh) on a scratch
copy of a repository two commits behind, by failure mode: a diff that starts at another version is applied anyway; a
folder without .git cannot update; a binary file stops the update or goes missing silently; the install's .env and .data
are changed; a bad FILE, an empty download or a moving TO is accepted; VERSION is wrong after a refusal."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "update_from_diff.sh"
REPO = Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run(root: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "OPS_ROOT": str(root), **env},
        check=False,
    )


@dataclass
class World:
    tmp: Path
    c1: str
    c2: str
    c3: str
    upstream: Path

    def diff(self, a: str, b: str) -> Path:
        out = self.tmp / f"{a[:7]}-{b[:7]}.diff"
        out.write_text(git(self.upstream, "diff", a, b) + "\n")
        return out

    def install(self, name: str, with_git: bool) -> Path:
        """A copy of the installed release c1, plus the customer's own .env and .data."""
        dest = self.tmp / name
        if with_git:
            subprocess.run(["git", "clone", "-q", str(self.upstream), str(dest)], check=True, capture_output=True)
            git(dest, "checkout", "-q", self.c1)
        else:
            dest.mkdir()
            archive = subprocess.run(
                ["git", "-C", str(self.upstream), "archive", self.c1], check=True, capture_output=True
            ).stdout
            subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
        (dest / ".env").write_text("SECRET=mine\n")
        (dest / ".data").mkdir()
        (dest / ".data" / "db").write_bytes(b"\x00rows")
        return dest


@pytest.fixture
def world(tmp_path: Path) -> World:
    up = tmp_path / "upstream"
    up.mkdir()
    subprocess.run(["git", "init", "-q", str(up)], check=True)
    (up / "app.txt").write_text("one\ntwo\nthree\n")
    (up / "old.txt").write_text("going away\n")
    (up / "logo.bin").write_bytes(b"\x00\x01\x02binary-v1")
    git(up, "add", ".")
    git(up, "commit", "-q", "-m", "c1")
    c1 = git(up, "rev-parse", "HEAD")
    (up / "app.txt").write_text("one\ntwo changed\nthree\n")
    (up / "added.txt").write_text("new file\n")
    git(up, "add", ".")
    git(up, "commit", "-q", "-m", "c2")
    c2 = git(up, "rev-parse", "HEAD")
    (up / "logo.bin").write_bytes(b"\x00\x01\x02binary-v2")
    (up / "old.txt").unlink()
    (up / "app.txt").write_text("one\ntwo changed\nthree\nfour\n")
    git(up, "add", "-A")
    git(up, "commit", "-q", "-m", "c3")
    c3 = git(up, "rev-parse", "HEAD")
    return World(tmp_path, c1, c2, c3, up)


def check_updated(root: Path, w: World, out: str) -> None:
    assert (root / "app.txt").read_text() == "one\ntwo changed\nthree\nfour\n"
    assert (root / "added.txt").read_text() == "new file\n"
    assert not (root / "old.txt").exists()
    assert (root / "VERSION").read_text().strip() == w.c3
    assert (root / ".env").read_text() == "SECRET=mine\n"
    assert (root / ".data" / "db").read_bytes() == b"\x00rows"
    # The binary change cannot ride in a text diff: the file stays as installed and is named with where to get it.
    assert (root / "logo.bin").read_bytes() == b"\x00\x01\x02binary-v1"
    assert "logo.bin" in out and "github.com/chanl-ai/ops-ai" in out, out


def test_a_git_folder_updates_from_the_diff_and_keeps_its_env_and_data(world: World) -> None:
    root = world.install("git-install", with_git=True)
    (root / "VERSION").write_text(world.c1 + "\n")
    run_ = run(root, "apply", str(world.diff(world.c1, world.c3)), world.c3)
    assert run_.returncode == 0, run_.stderr
    check_updated(root, world, run_.stdout)


def test_a_folder_without_git_updates_with_patch_and_stays_without_git(world: World) -> None:
    root = world.install("zip-install", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    run_ = run(root, "apply", str(world.diff(world.c1, world.c3)), world.c3)
    assert run_.returncode == 0, run_.stderr
    check_updated(root, world, run_.stdout)
    assert not (root / ".git").exists()


def test_a_diff_that_starts_at_another_version_is_refused_and_changes_nothing(world: World) -> None:
    root = world.install("wrong-start", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    run_ = run(root, "apply", str(world.diff(world.c2, world.c3)), world.c3)
    assert run_.returncode != 0
    assert "app.txt" in run_.stderr, run_.stderr
    assert (root / "app.txt").read_text() == "one\ntwo\nthree\n"
    assert (root / "VERSION").read_text().strip() == world.c1


@pytest.mark.parametrize("case", ["missing", "empty", "no-to", "moving-to"])
def test_a_bad_file_or_target_is_refused_in_one_line(world: World, tmp_path: Path, case: str) -> None:
    root = world.install(f"bad-{case}", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    good = world.diff(world.c1, world.c3)
    empty = tmp_path / "empty.diff"
    empty.write_text("")
    args = {
        "missing": ["apply", str(tmp_path / "nope.diff"), world.c3],
        "empty": ["apply", str(empty), world.c3],
        "no-to": ["apply", str(good)],
        "moving-to": ["apply", str(good), "main"],
    }[case]
    # No releases page to read, so a missing TO has nothing to default to.
    run_ = run(root, *args, UPDATE_BASE_URL=f"file://{tmp_path}/no-site")
    assert run_.returncode != 0 and len(run_.stderr.strip().splitlines()) == 1, run_.stderr
    assert (root / "app.txt").read_text() == "one\ntwo\nthree\n"


def test_version_is_recorded_from_git_or_set_by_hand_and_a_bare_folder_says_how(world: World) -> None:
    bare = world.install("bare", with_git=False)
    refused = run(bare, "version")
    assert refused.returncode != 0 and "SET=" in refused.stderr, refused.stderr
    assert run(bare, "version", world.c1).stdout.strip() == world.c1
    assert (bare / "VERSION").read_text().strip() == world.c1
    cloned = world.install("cloned", with_git=True)
    assert run(cloned, "version").stdout.strip() == world.c1
    assert (cloned / "VERSION").read_text().strip() == world.c1


def test_update_url_names_the_compare_page_from_the_installed_version(world: World) -> None:
    root = world.install("url", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    out = run(root, "url", "v2026-11-12.1").stdout.strip()
    assert out.startswith(f"https://github.com/chanl-ai/ops-ai/compare/{world.c1}...v2026-11-12.1"), out
    assert out.splitlines()[0].endswith(".diff") or ".diff" in out


def test_update_url_in_a_git_checkout_without_version_starts_at_head(world: World) -> None:
    root = world.install("url-head", with_git=True)
    out = run(root, "url", world.c3).stdout.splitlines()[0]
    assert f"/compare/{world.c1}...{world.c3}" in out, out
    bare = world.install("url-nothing", with_git=False)
    refused = run(bare, "url", world.c3)
    assert refused.returncode != 0 and "compare" not in refused.stdout, refused.stdout


def test_a_missing_target_is_the_latest_release_and_says_which(world: World) -> None:
    root = world.install("latest", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    site = world.tmp / "site2"
    (site / "compare").mkdir(parents=True)
    (site / "releases.atom").write_text(
        '<feed><entry><link href="https://x/releases/tag/v2026-11-12.2"/></entry>'
        '<entry><link href="https://x/releases/tag/v2026-11-12.1"/></entry></feed>'
    )
    (site / "compare" / f"{world.c1}...v2026-11-12.2.diff").write_text(
        git(world.upstream, "diff", world.c1, world.c3) + "\n"
    )
    env = {"UPDATE_BASE_URL": f"file://{site}"}
    url = run(root, "url", **env)
    assert "...v2026-11-12.2.diff" in url.stdout and "v2026-11-12.2" in url.stdout.splitlines()[0], url.stdout
    assert "latest release v2026-11-12.2" in url.stderr
    down = run(root, "download", **env)
    assert down.returncode == 0 and "latest release v2026-11-12.2" in down.stderr, down.stderr
    assert list((root / ".run" / "updates").glob("*v2026-11-12.2.diff"))


def test_update_download_saves_a_checked_diff_and_refuses_an_empty_or_misplaced_one(world: World) -> None:
    root = world.install("download", with_git=False)
    (root / "VERSION").write_text(world.c1 + "\n")
    site = world.tmp / "site"
    (site / "compare").mkdir(parents=True)
    env = {"UPDATE_BASE_URL": f"file://{site}"}
    page = site / "compare" / f"{world.c1}...{world.c3}.diff"

    page.write_text(git(world.upstream, "diff", world.c1, world.c3) + "\n")
    ok = run(root, "download", world.c3, **env)
    assert ok.returncode == 0, ok.stderr
    saved = list((root / ".run" / "updates").glob("*.diff"))
    assert len(saved) == 1 and saved[0].read_text() == page.read_text()

    shutil.rmtree(root / ".run")
    page.write_text("")
    empty = run(root, "download", world.c3, **env)
    assert empty.returncode != 0 and not list((root / ".run").rglob("*.diff"))

    page.write_text(git(world.upstream, "diff", world.c2, world.c3) + "\n")
    misplaced = run(root, "download", world.c3, **env)
    assert misplaced.returncode != 0 and "app.txt" in misplaced.stderr
    assert not list((root / ".run").rglob("*.diff"))


def test_the_make_targets_exist_and_call_the_script() -> None:
    out = subprocess.run(
        ["make", "-n", "update-url", "update-download", "update-from-diff", "version", "TO=x", "FILE=y"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("update_from_diff.sh") == 4, out.stdout
