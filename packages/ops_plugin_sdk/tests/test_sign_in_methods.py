"""What `ops plugin validate` checks of a plugin's sign-in (c-588), one test per way it can be wrong and still look
installable: a plugin that lets each person sign in with a method that holds no person's token, which a team learns
only when it turns the plugin on; and an API key the plugin does not say how to send, which a team admin would have
to guess."""

from __future__ import annotations

from pathlib import Path

from test_validate import MANIFEST, plugin, problems

KEYED = MANIFEST.replace(
    "  kinds: [oauth2_auth_code]\n  sign_in: [team]",
    "  kinds: [api_key]\n  api_key: { placement: query, name: api_key }\n  sign_in: [team]",
)


def test_person_sign_in_needs_a_method_that_holds_a_persons_token(tmp_path: Path) -> None:
    bad = KEYED.replace("sign_in: [team]", "sign_in: [team, person]")
    found = problems(plugin(tmp_path, bad))
    assert any("connection.sign_in" in p and "person" in p and "oauth2_auth_code" in p for p in found), found


def test_an_api_key_plugin_says_how_its_key_is_sent(tmp_path: Path) -> None:
    bad = KEYED.replace("  api_key: { placement: query, name: api_key }\n", "")
    found = problems(plugin(tmp_path, bad))
    assert any("connection.api_key" in p for p in found), found


def test_an_api_key_plugin_that_says_how_validates(tmp_path: Path) -> None:
    assert problems(plugin(tmp_path, KEYED)) == []
