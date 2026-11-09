"""Puts the plugins an image ships with into its plugins folder, each at the exact commit `deploy/plugins.json` pins.

    python deploy/images/bake_plugins.py [--pins deploy/plugins.json] --into /app/plugins

Each pin names a GitHub repository, a full 40-character commit, the plugin's folder in it and that folder's sha256
digest. The commit is fetched as a tarball, so the image needs no git; the folder is checked against the digest before
anything is installed, so a download that differs from what was pinned (a swapped archive, a compromised mirror) stops
the build; then the plugin is validated and copied as `opsai plugin install` does, and a plugin with problems stops the
build too. A branch or tag is refused because either can move, and an image must hold the same plugin every time it is
built from the same commit. `scripts/plugins_bump.py` writes the commit and the digest together. Exit 0 done, 1
refused."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ops_plugin_sdk.install import install, installed
from ops_plugin_sdk.manifest import ManifestError, read

COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
GITHUB = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
FETCH_TIMEOUT_S = 60


class PinRefused(ValueError):
    pass


def tarball_url(source: str, ref: str) -> str:
    """Where GitHub serves `source` at `ref` as a tarball; PinRefused for anything but a GitHub repo and a full
    commit."""
    m = GITHUB.match(source)
    if not m:
        raise PinRefused(f"{source} is not a GitHub repository address (https://github.com/<owner>/<repo>)")
    if not COMMIT.match(ref):
        raise PinRefused(f"{source} is pinned to {ref!r}; pin a full 40-character commit, which cannot move")
    return f"https://codeload.github.com/{m.group(1)}/{m.group(2)}/tar.gz/{ref}"


def _download(url: str) -> bytes:
    try:
        r = httpx.get(url, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise PinRefused(f"{url} could not be fetched ({type(e).__name__}: {e})") from e
    return r.content


def _extract(archive: bytes, into: Path) -> Path:
    """The archive's one top folder, unpacked under `into`; members outside it are refused by the data filter."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as t:
        t.extractall(into, filter="data")
    tops = [p for p in into.iterdir() if p.is_dir()]
    if len(tops) != 1:
        raise PinRefused("the tarball does not hold one top folder")
    return tops[0]


def folder_digest(folder: Path) -> str:
    """The sha256 of a plugin folder's content: each file's path inside it and the sha256 of its bytes, in path order,
    so the same files give the same digest however the archive around them was compressed."""
    whole = hashlib.sha256()
    for item in sorted(p for p in folder.rglob("*") if p.is_symlink() or not p.is_dir()):
        rel = item.relative_to(folder).as_posix()
        body = f"link:{item.readlink()}".encode() if item.is_symlink() else item.read_bytes()
        whole.update(rel.encode() + b"\0" + hashlib.sha256(body).digest())
    return whole.hexdigest()


def pinned_folder(pin: dict[str, Any], tmp: Path, fetch: Callable[[str], bytes] = _download) -> Path:
    """The pin's plugin folder, unpacked under `tmp` from the commit's tarball; PinRefused when it is missing."""
    source, ref, path = str(pin.get("source", "")), str(pin.get("ref", "")), str(pin.get("path", ""))
    top = _extract(fetch(tarball_url(source, ref)), tmp)
    folder = (top / path).resolve()
    if not folder.is_relative_to(top.resolve()) or not folder.is_dir():
        raise PinRefused(f"{source}@{ref[:12]} has no folder {path!r}")
    # The digest reads only files, while the install's copy follows a link: a link anywhere in the folder is refused.
    if links := [p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_symlink()]:
        raise PinRefused(f"{source}@{ref[:12]} {path} holds a symbolic link ({', '.join(sorted(links))})")
    return folder


def bake(pins: list[dict[str, Any]], into: Path, fetch: Callable[[str], bytes] = _download) -> list[str]:
    """Installs every pin into `into`; the ids and versions installed. Raises PinRefused on the first problem."""
    done: list[str] = []
    for pin in pins:
        source, ref, path = str(pin.get("source", "")), str(pin.get("ref", "")), str(pin.get("path", ""))
        want = str(pin.get("sha256", ""))
        with tempfile.TemporaryDirectory() as tmp:
            folder = pinned_folder(pin, Path(tmp), fetch)
            if not DIGEST.match(want):
                raise PinRefused(f"{source}@{ref[:12]} {path} pins no sha256 digest; run scripts/plugins_bump.py")
            if (got := folder_digest(folder)) != want:
                raise PinRefused(
                    f"{source}@{ref[:12]} {path}: the download's digest {got[:12]} is not the pinned {want[:12]}"
                )
            installed, problems = install(folder, into)
            if installed is None:
                raise PinRefused(f"{source}@{ref[:12]} {path}: " + "; ".join(str(p) for p in problems))
            done.append(f"{installed.id} {installed.version}")
    return done


def listed(folder: Path) -> list[str]:
    """`id version` for every plugin in `folder`, sorted."""
    out = []
    for pid, path in installed(folder).items():
        try:
            out.append(f"{pid} {read(path / 'plugin.yaml').version}")
        except ManifestError:
            out.append(f"{pid} unreadable")
    return sorted(out)


def drift(pins: list[dict[str, Any]], folder: Path, fetch: Callable[[str], bytes] = _download) -> list[str]:
    """Differences between what `pins` install and what `folder` holds, as `missing ...` and `unexpected ...` lines;
    empty when the two match by id and version."""
    with tempfile.TemporaryDirectory() as tmp:
        want = sorted(bake(pins, Path(tmp), fetch))
    have = listed(folder)
    return [f"missing {x}" for x in want if x not in have] + [f"unexpected {x}" for x in have if x not in want]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Put the pinned plugins into an image's plugins folder.")
    parser.add_argument("--pins", type=Path, default=Path(__file__).resolve().parents[1] / "plugins.json")
    parser.add_argument("--into", type=Path)
    parser.add_argument("--check", type=Path, help="fail unless this folder holds exactly the pinned plugins")
    args = parser.parse_args(argv)
    pins = json.loads(args.pins.read_text())["plugins"]
    if args.check is not None:
        if not str(args.check):
            sys.stderr.write("bake_plugins: --check needs a folder (is OPS_PLUGINS_DIR unset?)\n")
            return 1
        try:
            lines = drift(pins, args.check)
        except PinRefused as e:
            sys.stderr.write(f"bake_plugins: {e}\n")
            return 1
        for line in lines:
            sys.stdout.write(f"DRIFT {line}\n")
        if not lines:
            sys.stdout.write(f"ok plugins: {', '.join(listed(args.check)) or 'none'}\n")
        return 1 if lines else 0
    if args.into is None:
        parser.error("--into or --check is required")
    try:
        for line in bake(pins, args.into):
            sys.stdout.write(f"baked {line}\n")
    except PinRefused as e:
        sys.stderr.write(f"bake_plugins: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
