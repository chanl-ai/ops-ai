"""`connection.identity`: the settings whose values tell one account of an app from another (a Salesforce org's
address). One test that a good declaration validates, then one per way it could show the wrong thing: a name that is no
setting, a secret shown under an account's name, and a list long enough to crowd the row."""

from __future__ import annotations

from pathlib import Path

from test_validate import MANIFEST, plugin, problems

from ops_plugin_sdk.validate import validate

HOSTS = "  token_hosts: [.my.desk.test]\n"
DECLARED = MANIFEST.replace(HOSTS, HOSTS + "  identity: [instance_url]\n")


def test_an_identity_naming_a_plain_setting_validates_and_loads(tmp_path: Path) -> None:
    root = plugin(tmp_path, DECLARED)
    assert problems(root) == []
    manifest, _ = validate(root)
    assert manifest is not None and manifest.connection.identity == ["instance_url"]


def test_an_identity_naming_no_setting_is_refused(tmp_path: Path) -> None:
    root = plugin(tmp_path, DECLARED.replace("identity: [instance_url]", "identity: [org_id]"))
    assert any("connection.identity" in p and "org_id" in p for p in problems(root))


def test_an_identity_naming_a_secret_is_refused(tmp_path: Path) -> None:
    secret = DECLARED.replace("identity: [instance_url]", "identity: [vault_key]").replace(
        "  api_version:", "  vault_key: { type: string, secret: true }\n  api_version:"
    )
    assert any("connection.identity" in p and "secret" in p for p in problems(plugin(tmp_path, secret)))


def test_an_identity_of_more_than_three_settings_is_refused(tmp_path: Path) -> None:
    many = DECLARED.replace("identity: [instance_url]", "identity: [instance_url, api_version, a, b]").replace(
        "  api_version:", "  a: { type: string }\n  b: { type: string }\n  api_version:"
    )
    assert any("connection.identity" in p and "three" in p for p in problems(plugin(tmp_path, many)))
