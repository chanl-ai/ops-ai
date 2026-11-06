"""`ops plugin install|remove`, by failure mode: a plugin that fails validation lands in the install's
plugins folder anyway; an installed plugin is not where the services load from; an upgrade leaves the old version's
files behind; remove deletes the wrong folder, or says nothing when the plugin is not there."""

from __future__ import annotations

from pathlib import Path

from test_validate import MANIFEST, plugin

from ops_plugin_sdk.cli import main
from ops_plugin_sdk.loader import discover


def into(tmp_path: Path) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir()
    return folder


def test_a_plugin_that_fails_validation_is_not_copied(tmp_path: Path) -> None:
    root = plugin(tmp_path, MANIFEST.replace("kinds: [oauth2_auth_code]", "kinds: [saml_magic]"))
    folder = into(tmp_path)
    assert main(["plugin", "install", str(root), "--into", str(folder)]) == 1
    assert list(folder.iterdir()) == []


def test_an_installed_project_loads_from_the_plugins_folder(tmp_path: Path) -> None:
    project = tmp_path / "demo-desk"
    (project / "src").mkdir(parents=True)
    plugin(project / "src")
    folder = into(tmp_path)
    assert main(["plugin", "install", str(project), "--into", str(folder)]) == 0
    assert [p.name for p in folder.iterdir()] == ["demo_desk"]
    loaded = discover(found=[], folders=[str(p) for p in folder.iterdir()])
    assert [(x.name, x.ok, x.plugin.manifest.id if x.plugin else x.error) for x in loaded] == [
        ("demo_desk", True, "demo.desk")
    ]


def test_an_upgrade_replaces_the_old_copy(tmp_path: Path) -> None:
    root = plugin(tmp_path)
    folder = into(tmp_path)
    assert main(["plugin", "install", str(root), "--into", str(folder)]) == 0
    (folder / "demo_desk" / "left_over.py").write_text("x = 1\n")
    assert main(["plugin", "install", str(root), "--into", str(folder)]) == 0
    assert not (folder / "demo_desk" / "left_over.py").exists()
    assert (folder / "demo_desk" / "plugin.yaml").is_file()


def test_remove_takes_out_only_the_named_plugin(tmp_path: Path) -> None:
    root = plugin(tmp_path)
    folder = into(tmp_path)
    (folder / "other_desk").mkdir()
    assert main(["plugin", "install", str(root), "--into", str(folder)]) == 0
    assert main(["plugin", "remove", "demo.desk", "--into", str(folder)]) == 0
    assert [p.name for p in folder.iterdir()] == ["other_desk"]
    assert main(["plugin", "remove", "demo.desk", "--into", str(folder)]) == 1


def test_a_plugin_found_in_two_places_loads_from_neither_and_names_both(tmp_path: Path) -> None:
    # A stale copy in the plugins folder beside a developer's checkout: loading the first found would run whichever
    # copy happens to sort first, so neither runs and the failure says where each is.
    root = plugin(tmp_path)
    folder = into(tmp_path)
    assert main(["plugin", "install", str(root), "--into", str(folder)]) == 0
    loaded = discover(found=[], folders=[str(folder / "demo_desk"), str(root)])
    assert [x.ok for x in loaded] == [False, False]
    for x in loaded:
        assert x.error is not None
        assert "demo.desk is in two places" in x.error
        assert str((folder / "demo_desk").resolve()) in x.error and str(root.resolve()) in x.error
