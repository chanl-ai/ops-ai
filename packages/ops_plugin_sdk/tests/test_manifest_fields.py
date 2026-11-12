"""The manifest fields a system needs beyond a path and a query: headers, a form body, extra sign-in
parameters, how the client is sent on the token call, a lookup after sign-in and an amount limit. One test that a
plugin declaring all six validates, then one per way a declaration could send a secret, replace the sign-in, reach a
host the plugin does not list, or leave a limit silently off."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_validate import plugin, problems

from ops_plugin_sdk import NeedsReconnect
from ops_plugin_sdk.answers import answer_error
from ops_plugin_sdk.errors import Refused
from ops_plugin_sdk.paging import at, steps

FIELDS = """
schema: ops-ai/plugin@2
id: demo.desk
title: Desk
version: 0.1.0
sdk: "1"
connection:
  kinds: [oauth2_auth_code, api_key]
  api_key: { placement: header, name: X-Desk-Key }
  authorize_url: "https://login.desk.test/authorize"
  token_url: "https://login.desk.test/token"
  sign_in: [team]
  client_auth: basic
  authorize_params: { audience: "{audience}", prompt: consent }
  after_sign_in: { url: "https://login.desk.test/me/sites", read: "[0].url", setting: site_url }
  token_hosts: [.desk.test]
settings:
  site_url: { type: string, after_sign_in: true }
  audience: { type: string, default: api.desk.test }
  api_version: { type: string, default: "2" }
  vault_key: { type: string, secret: true }
egress: ["{site_url}", login.desk.test]
endpoint: "{site_url}/api"
headers: { X-Api-Version: "{api_version}" }
tools:
  - name: search
    access: read
    input: { q: { type: string, enum: [open, closed] } }
    headers: { ConsistencyLevel: eventual }
    request: { method: GET, path: /search }
  - name: post_message
    access: write
    input: { channel: { type: string }, text: { type: string } }
    request: { method: POST, path: /chat.postMessage, form: { channel: "{{channel}}", text: "{{text}}" } }
  - name: transfer
    access: write
    input: { amount: { type: number }, to: { type: string } }
    amount_max: 5000
    request: { method: POST, path: /transfers, body: '{"amount": {{amount}}, "to": {{to}}}' }
"""


def test_a_plugin_declaring_all_six_validates(tmp_path: Path) -> None:
    assert problems(plugin(tmp_path, FIELDS)) == []


@pytest.mark.parametrize(
    ("change", "field", "says"),
    [
        (("X-Api-Version:", "authorization:"), "headers.authorization", "carries the sign-in"),
        (("ConsistencyLevel:", "COOKIE:"), "tools.search.headers.COOKIE", "carries the sign-in"),
        (("X-Api-Version:", "x-desk-key:"), "headers.x-desk-key", "carries the sign-in"),
        (("ConsistencyLevel:", "Host:"), "tools.search.headers.Host", "carries the sign-in"),
        (('"{api_version}"', '"{{API_KEY}}"'), "headers.X-Api-Version", "holds {{"),
        (('"{api_version}"', '"{vault_key}"'), "headers.X-Api-Version", "a secret setting"),
        (("path: /search", 'path: "/search/{{API_KEY}}"'), "tools.search", "is a secret reference"),
        (('"{{text}}"', '"{{SLACK_TOKEN}}"'), "tools.post_message", "is a secret reference"),
        (('text: "{{text}}" }', 'text: "{{body}}" }'), "tools.post_message", "names no input"),
        (("method: POST, path: /chat", "method: GET, path: /chat"), "tools.post_message", "a GET sends no form"),
        ((", prompt: consent", ", state: mine"), "connection.authorize_params.state", "set by the platform"),
        ((", prompt: consent", ", redirect_uri: x"), "connection.authorize_params.redirect_uri", "set by the platform"),
        (('audience: "{audience}"', 'audience: "{vault_key}"'), "connection.authorize_params.audience", "secret"),
        (
            ('url: "https://login.desk.test/me/sites"', 'url: "https://evil.test/me"'),
            "connection.after_sign_in",
            "not one of the plugin's egress hosts",
        ),
        (("setting: site_url }", "setting: audience }"), "connection.after_sign_in", "marked after_sign_in"),
        (('read: "[0].url"', 'read: "[x"'), "connection.after_sign_in", "is not a path"),
        (("  token_hosts: [.desk.test]\n", ""), "connection.token_hosts", "host suffixes"),
        (("amount: { type: number }", "sum: { type: number }"), "tools.transfer", "a number input named amount"),
        (("amount: { type: number }", "amount: { type: string }"), "tools.transfer", "a number input named amount"),
    ],
)
def test_an_unsafe_declaration_is_refused_by_field(
    tmp_path: Path, change: tuple[str, str], field: str, says: str
) -> None:
    old, new = change
    assert FIELDS.count(old) == 1, old
    found = problems(plugin(tmp_path, FIELDS.replace(old, new)))
    assert any(p.startswith(f"{field}:") and says in p for p in found), found


def test_a_tool_with_a_json_body_and_a_form_is_refused(tmp_path: Path) -> None:
    both = FIELDS.replace('text: "{{text}}" } }', 'text: "{{text}}" }, body: "{}" }')
    assert any("a JSON body or a form, not both" in p for p in problems(plugin(tmp_path, both)))


def test_a_python_tool_cannot_carry_its_own_headers(tmp_path: Path) -> None:
    python = FIELDS.replace(
        "    request: { method: GET, path: /search }", "    function: demo_desk.kb:list_articles"
    ).replace("input: { q: { type: string, enum: [open, closed] } }", "input: {}")
    found = problems(plugin(tmp_path, python))
    assert any(p.startswith("tools.search.headers:") and "plugin's headers only" in p for p in found), found


def test_a_paged_tool_cannot_have_an_amount_limit(tmp_path: Path) -> None:
    paged = FIELDS.replace(
        '    request: { method: POST, path: /transfers, body: \'{"amount": {{amount}}, "to": {{to}}}\' }',
        "    request: { method: GET, path: /transfers, paging: { rule: link, next: next } }",
    ).replace("  - name: transfer\n    access: write", "  - name: transfer\n    access: read")
    assert any("a paged tool cannot have amount_max" in p for p in problems(plugin(tmp_path, paged)))


def test_client_auth_and_sign_in_parameters_need_an_oauth_plugin(tmp_path: Path) -> None:
    keyed = FIELDS.replace("kinds: [oauth2_auth_code, api_key]", "kinds: [api_key]")
    found = problems(plugin(tmp_path, keyed))
    assert any(p.startswith("connection.client_auth:") for p in found), found
    assert any(p.startswith("connection.authorize_params:") for p in found), found


def test_a_lookup_path_is_on_the_sign_in_host_and_that_host_must_be_listed(tmp_path: Path) -> None:
    on_login = FIELDS.replace('url: "https://login.desk.test/me/sites"', "url: /me/sites")
    assert problems(plugin(tmp_path / "listed", on_login)) == []
    unlisted = on_login.replace('egress: ["{site_url}", login.desk.test]', 'egress: ["{site_url}"]')
    found = problems(plugin(tmp_path / "unlisted", unlisted))
    assert any("login.desk.test, which is not one of the plugin's egress hosts" in p for p in found), found


def test_a_paging_rule_reads_fields_not_list_positions(tmp_path: Path) -> None:
    indexed = FIELDS.replace(
        "    request: { method: GET, path: /search }",
        '    request: { method: GET, path: /search, paging: { rule: link, next: "links[0]" } }',
    )
    assert any("not list positions" in p for p in problems(plugin(tmp_path, indexed)))


def test_a_lookup_path_reads_keys_and_list_positions() -> None:
    answer = {"accounts": [{"base_uri": "https://na3.docusign.test"}], "urls": {"custom_domain": "https://x"}}
    assert at(answer, ".accounts[0].base_uri") == "https://na3.docusign.test"
    assert at(answer, "urls.custom_domain") == "https://x"
    assert at([{"id": "cloud-7f3a"}], "[0].id") == "cloud-7f3a"
    assert at(answer, "accounts[3].base_uri") is None
    assert steps("[x") is None and steps("a[0]b") is None


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('{"amount": {{amount}}, "to": "{{to}}"}', "{{to}} sits inside quotes"),
        ('{"amount": {{amount}}, "to": {{to}}', "is not JSON once each {{input}} is written in"),
        ('{"amount": {{amount}}, "to": {{payee}}}', "{{payee}} in the body names no input"),
    ],
)
def test_a_json_body_that_would_send_broken_json_is_refused(tmp_path: Path, body: str, said: str) -> None:
    """A body's `{{input}}` is written as JSON with its own quotes, so one put inside quotes sends `""text""`."""
    bad = FIELDS.replace("""body: '{"amount": {{amount}}, "to": {{to}}}'""", f"body: '{body}'")
    assert bad != FIELDS
    assert any(said in p for p in problems(plugin(tmp_path, bad))), problems(plugin(tmp_path, bad))


def test_a_whole_object_body_still_validates(tmp_path: Path) -> None:
    whole = FIELDS.replace("""body: '{"amount": {{amount}}, "to": {{to}}}'""", 'body: "{{to}}"')
    assert problems(plugin(tmp_path, whole)) == []


# Slack answers 200 with `ok: false` and a code at `error`; GraphQL answers 200 with a list at `errors`.
RULE = {"path": "error", "app": "Desk", "sign_in_errors": [{"error": "invalid_auth", "say": "Connect {app} again."}]}


def test_an_error_when_path_that_does_not_parse_is_refused(tmp_path: Path) -> None:
    assert problems(plugin(tmp_path / "good", FIELDS + "error_when: error\n")) == []
    found = problems(plugin(tmp_path / "bad", FIELDS + 'error_when: "errors[x"\n'))
    assert any(p.startswith("error_when") for p in found), found


def test_an_error_inside_a_successful_answer_is_read_in_the_systems_words() -> None:
    slack = answer_error({"ok": False, "error": "channel_not_found"}, RULE)
    assert isinstance(slack, Refused) and str(slack) == "Desk refused the call: channel_not_found."
    graphql_answer = {"data": None, "errors": [{"message": "Could not resolve to a Repository."}]}
    graphql = answer_error(graphql_answer, {**RULE, "path": "errors"})
    assert isinstance(graphql, Refused) and "Could not resolve to a Repository." in str(graphql)


def test_an_error_code_the_plugin_names_for_sign_in_asks_to_connect_again() -> None:
    refused = answer_error({"ok": False, "error": "invalid_auth"}, RULE)
    assert isinstance(refused, NeedsReconnect) and str(refused) == "Connect Desk again."


@pytest.mark.parametrize("answer", [{"ok": True}, {"ok": True, "error": None}, {"errors": []}, "plain text", [1, 2]])
def test_an_answer_with_nothing_at_the_path_is_a_success(answer: object) -> None:
    assert answer_error(answer, RULE) is None
    assert answer_error(answer, {**RULE, "path": "errors"}) is None
