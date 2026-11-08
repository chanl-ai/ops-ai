"""A plugin version's declarations, digest and diff, by failure mode: a changed tool the review does not list,
or an unchanged one it does; an input change it misses; a digest that changes when nothing a call sends changed, or
stays when something did; and declarations that do not read back as the tools they were taken from."""

from __future__ import annotations

from pathlib import Path

from test_manifest_fields import FIELDS
from test_validate import plugin

from ops_plugin_sdk.manifest import read
from ops_plugin_sdk.versions import declarations, diff, digest, tools_of


def manifest(tmp_path: Path, text: str = FIELDS):
    return read(plugin(tmp_path, text) / "plugin.yaml")


NEXT = (
    FIELDS.replace("version: 0.1.0", "version: 0.2.0")
    # search's status list grows; transfer's limit rises; post_message goes; a new tool arrives.
    .replace("enum: [open, closed]", "enum: [open, closed, pending]")
    .replace("amount_max: 5000", "amount_max: 9000")
    .replace(
        "  - name: post_message\n    access: write\n    input: { channel: { type: string }, text: { type: string } }\n"
        '    request: { method: POST, path: /chat.postMessage, form: { channel: "{{channel}}", text: "{{text}}" } }\n',
        "  - name: close_case\n    access: write\n    input: { id: { type: string }, reason: { type: string } }\n"
        "    request: { method: POST, path: /cases/close }\n",
    )
)


def test_the_review_lists_each_new_changed_and_removed_tool_and_only_those(tmp_path: Path) -> None:
    old, new = declarations(manifest(tmp_path / "a")), declarations(manifest(tmp_path / "b", NEXT))
    found = {t["name"]: t for t in diff(old, new)["tools"]}
    assert set(found) == {"search", "transfer", "post_message", "close_case"}, found
    assert found["search"]["change"] == "changed" and found["search"]["inputs"]["changed"] == ["q"]
    assert found["transfer"]["changed"] == ["amount_max"] and found["transfer"]["inputs"] == {
        "added": [], "removed": [], "changed": []
    }  # fmt: skip
    assert found["post_message"]["change"] == "removed"
    assert found["close_case"]["change"] == "new" and found["close_case"]["inputs"]["added"] == ["id", "reason"]
    assert diff(old, old) == {"headers": False, "tools": []}


def test_the_digest_follows_what_calls_send_not_the_version_number(tmp_path: Path) -> None:
    base = declarations(manifest(tmp_path / "a"))
    renumbered = declarations(manifest(tmp_path / "b", FIELDS.replace("version: 0.1.0", "version: 0.1.1")))
    header = declarations(manifest(tmp_path / "c", FIELDS.replace('"{api_version}" }', '"{api_version}-x" }')))
    assert digest(base) == digest(renumbered)
    assert digest(base) != digest(header) and diff(base, header)["headers"] is True


def test_declarations_read_back_as_the_tools_they_were_taken_from(tmp_path: Path) -> None:
    m = manifest(tmp_path)
    assert tools_of(declarations(m)) == {t.name: t for t in m.tools}


def test_a_release_that_changes_only_a_skill_has_a_new_digest(tmp_path: Path) -> None:
    # 0.3.1 of a plugin changed only a skill's text, so its digest equalled 0.3.0's and no team was offered the update.
    text = FIELDS + "templates:\n  - { kind: skill, id: s1, version: 1, path: templates/skills/s1.yaml }\n"
    digests: list[str] = []
    for name, body in (
        ("a", "instructions: six queries\n"),
        ("b", "instructions: six queries\n"),
        ("c", "instructions: one query\n"),
    ):
        root = plugin(tmp_path / name, text)
        (root / "templates" / "skills").mkdir(parents=True)
        (root / "templates" / "skills" / "s1.yaml").write_text(body)
        digests.append(digest(declarations(read(root / "plugin.yaml"), root)))
    assert digests[0] == digests[1] != digests[2], digests
