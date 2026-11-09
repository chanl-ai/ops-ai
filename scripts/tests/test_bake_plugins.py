"""Baking pinned plugins into an image, by failure mode: a pin that can move (a branch or tag) is built; a source that
is not a GitHub repository is fetched; a broken plugin reaches the image; a pin's path escapes the tarball; and a
download that differs from the pinned digest, or a pin with no digest, is baked."""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "images"))

from bake_plugins import PinRefused, bake, drift, folder_digest, tarball_url

REPO = "https://github.com/acme/ops-ai-plugins"
SHA = "e0e932b2655dada3e28e66a306424703513b4869"
PLUGIN = (
    Path(__file__).resolve().parents[2] / "services" / "tools-service" / "tests" / "plugin_kinds" / "kinds_header_key"
)
PINNED = folder_digest(PLUGIN)


def _tarball(folder: Path, as_path: str) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        t.add(folder, arcname=f"ops-ai-plugins-{SHA}/{as_path}")
    return out.getvalue()


def test_only_a_full_commit_on_github_is_fetched() -> None:
    assert tarball_url(REPO, SHA) == f"https://codeload.github.com/acme/ops-ai-plugins/tar.gz/{SHA}"
    for ref in ("main", "v1.2.0", SHA[:12]):
        with pytest.raises(PinRefused, match="40-character"):
            tarball_url(REPO, ref)
    for source in ("https://gitlab.com/acme/plugins", "http://github.com/acme/plugins", "file:///tmp/plugins"):
        with pytest.raises(PinRefused, match="GitHub"):
            tarball_url(source, SHA)


def test_a_pinned_plugin_is_validated_and_installed(tmp_path: Path) -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _tarball(PLUGIN, "plugins/header_key")

    done = bake(
        [{"source": REPO, "ref": SHA, "path": "plugins/header_key", "sha256": PINNED}], tmp_path / "plugins", fetch
    )
    assert done and done[0].startswith("test.header-key "), done
    assert (tmp_path / "plugins" / "header_key" / "plugin.yaml").is_file()
    assert fetched == [tarball_url(REPO, SHA)]


def test_a_broken_plugin_or_a_wrong_path_stops_the_build(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "plugin.yaml").write_text("id: not a manifest\n")
    with pytest.raises(PinRefused):
        bake(
            [{"source": REPO, "ref": SHA, "path": "p", "sha256": folder_digest(broken)}],
            tmp_path / "out",
            lambda _: _tarball(broken, "p"),
        )
    assert not (tmp_path / "out" / "broken").exists()
    for path in ("missing", "../../etc"):
        with pytest.raises(PinRefused, match="no folder"):
            bake(
                [{"source": REPO, "ref": SHA, "path": path, "sha256": PINNED}],
                tmp_path / "out",
                lambda _: _tarball(PLUGIN, "p"),
            )


def test_a_folder_that_differs_from_the_pins_is_reported(tmp_path: Path) -> None:
    pins = [{"source": REPO, "ref": SHA, "path": "plugins/header_key", "sha256": PINNED}]

    def fetch(_: str) -> bytes:
        return _tarball(PLUGIN, "plugins/header_key")

    folder = tmp_path / "plugins"
    assert drift(pins, folder, fetch) == [f"missing {bake(pins, tmp_path / 'x', fetch)[0]}"]
    bake(pins, folder, fetch)
    assert drift(pins, folder, fetch) == []
    (folder / "stray").mkdir()
    assert drift(pins, folder, fetch) == ["unexpected stray unreadable"]


def test_a_tarball_whose_plugin_differs_from_the_pinned_digest_is_refused(tmp_path: Path) -> None:
    # The commit pins what was reviewed; the digest pins the bytes, so a swapped or altered download is never baked.
    pin = {"source": REPO, "ref": SHA, "path": "plugins/header_key", "sha256": "0" * 64}
    with pytest.raises(PinRefused, match="digest"):
        bake([pin], tmp_path / "plugins", lambda _: _tarball(PLUGIN, "plugins/header_key"))
    assert not (tmp_path / "plugins" / "header_key").exists()
    del pin["sha256"]
    with pytest.raises(PinRefused, match="no sha256"):
        bake([pin], tmp_path / "plugins", lambda _: _tarball(PLUGIN, "plugins/header_key"))


def test_a_tarball_whose_plugin_holds_a_symlink_is_refused(tmp_path: Path) -> None:
    # The digest reads files, and a linked folder's files are copied by the install: a link is refused outright.
    folder = tmp_path / "plugin"
    shutil.copytree(PLUGIN, folder)
    (tmp_path / "evil").mkdir()
    (tmp_path / "evil" / "tool.py").write_text("print('not reviewed')\n")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as t:
        t.add(folder, arcname=f"ops-ai-plugins-{SHA}/plugins/header_key")
        t.add(tmp_path / "evil", arcname=f"ops-ai-plugins-{SHA}/evil")
        link = tarfile.TarInfo(f"ops-ai-plugins-{SHA}/plugins/header_key/extra")
        link.type, link.linkname = tarfile.SYMTYPE, "../../evil"
        t.addfile(link)
    pin = {"source": REPO, "ref": SHA, "path": "plugins/header_key", "sha256": PINNED}
    with pytest.raises(PinRefused, match="link"):
        bake([pin], tmp_path / "plugins", lambda _: out.getvalue())
    assert not (tmp_path / "plugins" / "header_key").exists()
