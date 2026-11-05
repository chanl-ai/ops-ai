"""A setting's choices and typed host, a refused sign-in's messages, and the settings an app credential holds. One
test that a plugin declaring all of them validates, then one per way a declaration would let tools-service accept a
value nobody offered, send a sign-in to a host outside the system, show a refusal that tells nobody what to do, or
leave a credential holding a setting the plugin does not have."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_validate import plugin, problems

CHOICES = """
schema: ops-ai/plugin@2
id: demo.desk
title: Desk
version: 0.1.0
sdk: "1"
connection:
  kinds: [oauth2_auth_code]
  authorize_url: "{login_url}/{tenant}/authorize"
  token_url: "{login_url}/{tenant}/token"
  sign_in: [team]
  credential_settings: [tenant]
  sign_in_errors:
    - { error: invalid_client, description_contains: installed, say: "Install the app first.", who: admin }
    - { error: access_denied, say: "Access was not given in {app}.", who: person }
settings:
  login_url:
    type: string
    title: Where do you sign in?
    default: "https://login.desk.test/oauth2"
    choices:
      - { value: "https://login.desk.test/oauth2", label: login.desk.test, hint: Live accounts }
      - { value: "https://test.desk.test/oauth2", label: test.desk.test, hint: Test accounts, test_account: true }
    other:
      label: Your company's address
      placeholder: acme.my.desk.test
      value: "https://{host}/oauth2"
      hosts: [.my.desk.test]
      test_account_hosts: [.sandbox.my.desk.test]
  tenant: { type: string, title: Tenant }
  page_size: { type: integer, default: 50, choices: [{ value: 50, label: "50" }, { value: 200, label: "200" }] }
egress: ["{login_url}"]
endpoint: "{login_url}/api"
tools:
  - name: get_case
    access: read
    input: { id: { type: string } }
    request: { method: GET, path: "/cases/{id}" }
"""


def test_a_plugin_declaring_choices_errors_and_credential_settings_validates(tmp_path: Path) -> None:
    assert problems(plugin(tmp_path, CHOICES)) == []


def test_a_choice_outside_its_settings_type_is_refused(tmp_path: Path) -> None:
    bad = CHOICES.replace('{ value: 200, label: "200" }', '{ value: "two hundred", label: "200" }')
    found = problems(plugin(tmp_path, bad))
    assert any(p.startswith("settings.page_size:") and "not a integer" in p for p in found), found


def test_a_typed_host_with_no_suffixes_is_refused(tmp_path: Path) -> None:
    bad = CHOICES.replace("      hosts: [.my.desk.test]\n", "")
    found = problems(plugin(tmp_path, bad))
    assert any(p.startswith("settings.login_url:") and "(hosts)" in p for p in found), found


def test_a_typed_host_value_without_a_host_place_is_refused(tmp_path: Path) -> None:
    bad = CHOICES.replace('value: "https://{host}/oauth2"', 'value: "https://acme.my.desk.test/oauth2"')
    found = problems(plugin(tmp_path, bad))
    assert any(p.startswith("settings.login_url:") and "names {host} once" in p for p in found), found


def test_a_host_suffix_without_its_leading_dot_is_refused(tmp_path: Path) -> None:
    # Without the dot, `my.desk.test` would also accept `evilmy.desk.test`, a host outside the system.
    bad = CHOICES.replace("hosts: [.my.desk.test]", "hosts: [my.desk.test]")
    found = problems(plugin(tmp_path, bad))
    assert any(p.startswith("settings.login_url:") and "starts with a dot" in p for p in found), found


def test_an_unknown_credential_setting_is_refused(tmp_path: Path) -> None:
    bad = CHOICES.replace("credential_settings: [tenant]", "credential_settings: [tennant]")
    found = problems(plugin(tmp_path, bad))
    assert any(p.startswith("connection.credential_settings:") and "tennant names no setting" in p for p in found)


@pytest.mark.parametrize(
    ("old", "new", "says"),
    [
        (', say: "Install the app first."', "", "says nothing"),
        (", who: admin }", " }", "names nobody to act"),
    ],
)
def test_a_sign_in_error_that_tells_nobody_what_to_do_is_refused(tmp_path: Path, old: str, new: str, says: str) -> None:
    assert CHOICES.count(old) == 1, old
    found = problems(plugin(tmp_path, CHOICES.replace(old, new)))
    assert any(p.startswith("connection.sign_in_errors[0]:") and says in p for p in found), found
