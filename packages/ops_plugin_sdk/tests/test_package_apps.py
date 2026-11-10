"""A package app: a plugin that runs inside another app (a loan package installed in a Salesforce org) and has no
accounts of its own. One test that a good declaration validates and loads, then one per way it could be wrong and still
look installable: a sign-in of its own beside `runs_on`, `requires` with nothing to run on, a plugin running on itself,
and a package check that names no object."""

from __future__ import annotations

from pathlib import Path

from test_validate import plugin, problems

from ops_plugin_sdk.validate import validate

PACKAGE = """
schema: ops-ai/plugin@2
id: demo.loans
title: Loan desk
version: 0.1.0
sdk: "1"
connection:
  kinds: [none]
  sign_in: [team]
  runs_on: demo.desk
  requires: [LNDK__Loan__c]
  requires_check: "/api/v1/objects/{name}"
egress: ["{instance_url}"]
endpoint: "{instance_url}/api/v1"
tools:
  - name: get_loan
    access: read
    input: { id: { type: string } }
    request: { method: GET, path: "/loans/{id}" }
"""


def test_a_package_naming_the_app_it_runs_on_validates_and_loads(tmp_path: Path) -> None:
    root = plugin(tmp_path, PACKAGE)
    assert problems(root) == []
    manifest, _ = validate(root)
    assert manifest is not None
    c = manifest.connection
    assert (c.runs_on, c.requires, c.requires_check) == ("demo.desk", ["LNDK__Loan__c"], "/api/v1/objects/{name}")


def test_a_package_with_a_sign_in_of_its_own_is_refused(tmp_path: Path) -> None:
    own = PACKAGE.replace("kinds: [none]", "kinds: [oauth2_auth_code]")
    assert any("connection.runs_on" in p and "none" in p for p in problems(plugin(tmp_path, own)))


def test_requires_with_nothing_to_run_on_is_refused(tmp_path: Path) -> None:
    alone = PACKAGE.replace("  runs_on: demo.desk\n", "")
    assert any("connection.requires" in p and "runs_on" in p for p in problems(plugin(tmp_path, alone)))


def test_a_plugin_running_on_itself_is_refused(tmp_path: Path) -> None:
    itself = PACKAGE.replace("runs_on: demo.desk", "runs_on: demo.loans")
    assert any("connection.runs_on" in p and "itself" in p for p in problems(plugin(tmp_path, itself)))


def test_a_package_check_naming_no_object_is_refused(tmp_path: Path) -> None:
    blind = PACKAGE.replace("/api/v1/objects/{name}", "/api/v1/objects")
    assert any("connection.requires_check" in p and "{name}" in p for p in problems(plugin(tmp_path, blind)))
