"""The plugins a fresh install loads, by failure mode: a clone or image with an empty plugins folder loads no app and
no template pack, so the template gallery is empty; and an outside copy of a built-in plugin in the plugins folder (a
stale synced copy, a PLUGINS_DEV link to a working copy) makes the loader refuse the plugin in both places; and a team
that existed before built-in plugins started on keeps them off (its templates list, its tools do not run) while a team
platform-service reports as new starts with every built-in plugin on."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import TEAM_CREATED
from ops_plugin_sdk.loader import discover
from ops_service_kit.settings import Settings
from ops_tools.platform_events import team_created_handlers
from ops_tools.plugins.host import PluginHost
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.team_defaults import TeamDefaults

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


async def test_built_in_plugins_stay_off_for_an_existing_team_and_start_on_for_a_team_reported_new(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    settings = Settings(plugins_dir=tmp_path / "plugins", builtin_plugins_dir=BUILTIN)
    bindings = PluginBindings(engine)
    store = ModuleStore(engine)
    host = PluginHost.start(store, bindings, {}, settings.plugin_folders, builtin_dir=BUILTIN)
    salesforce = host.plugins["opsai.salesforce"]
    off = "Salesforce is off for this team; a team admin turns it on."
    # A team from before the change has no binding row: its built-in apps stay off until an admin turns them on.
    assert await host.off_reason(tenant, "team_old", salesforce) == off
    provision = team_created_handlers(store, TeamDefaults(engine), host)[TEAM_CREATED].act
    await provision(tenant, "team_new", {})
    assert await host.off_reason(tenant, "team_new", salesforce) is None
    assert await host.off_reason(tenant, "team_old", salesforce) == off
    # A repeated event leaves an admin's later choice alone.
    await bindings.put(tenant, "team_new", "opsai.salesforce", enabled=False, connection_id=None, settings={}, by="t")
    await provision(tenant, "team_new", {})
    assert await host.off_reason(tenant, "team_new", salesforce) == off
