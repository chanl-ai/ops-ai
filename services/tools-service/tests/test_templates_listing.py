"""The plugins a fresh install loads, by failure mode: a clone or image with an empty plugins folder loads no app and
no template pack, so the template gallery is empty; and an outside copy of a built-in plugin in the plugins folder (a
stale synced copy, a PLUGINS_DEV link to a working copy) makes the loader refuse the plugin in both places."""

from __future__ import annotations

import shutil
from pathlib import Path

from ops_plugin_sdk.loader import discover
from ops_service_kit.settings import Settings

BUILTIN = Path(__file__).resolve().parents[3] / "builtin-plugins"
SHIPPED = {
    "opsai.confluence",
    "opsai.core",
    "opsai.github",
    "opsai.salesforce",
    "opsai.sharepoint",
    "opsai.starters",
    "opsai.web",
}


def loaded_ids(settings: Settings) -> tuple[dict[str, str], list[str]]:
    found = discover(found=[], folders=settings.plugin_folders)
    ok = {i.plugin.manifest.id: str(i.plugin.root) for i in found if i.plugin is not None}
    return ok, [f"{i.name}: {i.error}" for i in found if i.plugin is None]


def test_an_empty_plugins_folder_still_loads_every_built_in_plugin_with_its_templates(tmp_path: Path) -> None:
    ok, failed = loaded_ids(Settings(plugins_dir=tmp_path / "plugins", builtin_plugins_dir=BUILTIN))
    assert failed == []
    assert set(ok) == SHIPPED
    found = discover(found=[], folders=[ok["opsai.starters"]])
    assert found[0].plugin is not None and found[0].plugin.manifest.templates
    assert (BUILTIN / "ops_plugin_starters" / "THIRD_PARTY_NOTICES.txt").is_file()


def test_an_outside_copy_of_a_built_in_plugin_replaces_it_instead_of_disabling_both(tmp_path: Path) -> None:
    outside = tmp_path / "plugins"
    # A PLUGINS_DEV link is the plugin's whole project, src/<package>, under the project's own folder name.
    shutil.copytree(BUILTIN / "ops_plugin_core", outside / "core" / "src" / "ops_plugin_core")
    settings = Settings(plugins_dir=outside, builtin_plugins_dir=BUILTIN)
    ok, failed = loaded_ids(settings)
    assert failed == []
    assert set(ok) == SHIPPED
    assert str(outside / "core") in settings.plugin_folders
    assert str(BUILTIN / "ops_plugin_core") not in settings.plugin_folders
