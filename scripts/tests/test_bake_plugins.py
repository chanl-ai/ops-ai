"""Baking pinned plugins into an image, by failure mode: a pin that can move (a branch or tag) is built; a source that
is not a GitHub repository is fetched; a broken plugin reaches the image; and a pin's path escapes the tarball."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "images"))

from bake_plugins import PinRefused, bake, drift, tarball_url

REPO = "https://github.com/acme/ops-ai-plugins"
SHA = "e0e932b2655dada3e28e66a306424703513b4869"
PLUGIN = (
    Path(__file__).resolve().parents[2] / "services" / "tools-service" / "tests" / "plugin_kinds" / "kinds_header_key"
)


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

    done = bake([{"source": REPO, "ref": SHA, "path": "plugins/header_key"}], tmp_path / "plugins", fetch)
    assert done and done[0].startswith("test.header-key "), done
    assert (tmp_path / "plugins" / "header_key" / "plugin.yaml").is_file()
    assert fetched == [tarball_url(REPO, SHA)]


def test_a_broken_plugin_or_a_wrong_path_stops_the_build(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "plugin.yaml").write_text("id: not a manifest\n")
    with pytest.raises(PinRefused):
        bake([{"source": REPO, "ref": SHA, "path": "p"}], tmp_path / "out", lambda _: _tarball(broken, "p"))
    assert not (tmp_path / "out" / "broken").exists()
    for path in ("missing", "../../etc"):
        with pytest.raises(PinRefused, match="no folder"):
            bake([{"source": REPO, "ref": SHA, "path": path}], tmp_path / "out", lambda _: _tarball(PLUGIN, "p"))


def test_a_folder_that_differs_from_the_pins_is_reported(tmp_path: Path) -> None:
    pins = [{"source": REPO, "ref": SHA, "path": "plugins/header_key"}]

    def fetch(_: str) -> bytes:
        return _tarball(PLUGIN, "plugins/header_key")

    folder = tmp_path / "plugins"
    assert drift(pins, folder, fetch) == [f"missing {bake(pins, tmp_path / 'x', fetch)[0]}"]
    bake(pins, folder, fetch)
    assert drift(pins, folder, fetch) == []
    (folder / "stray").mkdir()
    assert drift(pins, folder, fetch) == ["unexpected stray unreadable"]
