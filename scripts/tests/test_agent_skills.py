"""The developer skills' generator (c-554), one test per failure mode: a generated file edited by hand, a skill named
like a process skill, a page with no proof block, and an instructions file grown past what Copilot reads."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_skills

PAGE = """# ops-demo: a demo skill

Status: current.

skill: ops-demo
description: A demo. Use when testing the generator.
targets: make health

## Steps

1. `make health`.

## Proof

```bash proof
make health
```
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with one skill page, AGENTS.md and CLAUDE.md, and the generator pointed at it."""
    (tmp_path / "docs/guide/skills").mkdir(parents=True)
    (tmp_path / "docs/guide/skills/ops-demo.md").write_text(PAGE)
    (tmp_path / "AGENTS.md").write_text("# Rules\n\n| Rule | Detail |\n|---|---|\n| Verify | Run it |\n")
    (tmp_path / "CLAUDE.md").write_text("# C\n\n## Four rules every change follows\n\nOne of each thing.\n\n## Next\n")
    # The generated skills' folder, at the same place under tmp_path as in the repository.
    skills_dir = tmp_path / agent_skills.CLAUDE_SKILLS.relative_to(agent_skills.ROOT)
    (skills_dir / "spec").mkdir(parents=True)
    monkeypatch.setattr(agent_skills, "ROOT", tmp_path)
    monkeypatch.setattr(agent_skills, "PAGES", tmp_path / "docs/guide/skills")
    monkeypatch.setattr(agent_skills, "CLAUDE_SKILLS", skills_dir)
    monkeypatch.setattr(agent_skills, "PROMPTS", tmp_path / ".github/prompts")
    monkeypatch.setattr(agent_skills, "INSTRUCTIONS", tmp_path / ".github/copilot-instructions.md")
    monkeypatch.setattr(sys, "argv", ["agent_skills.py"])
    assert agent_skills.main() == 0
    monkeypatch.setattr(sys, "argv", ["agent_skills.py", "--check"])
    return tmp_path


def test_the_generated_files_match_their_page(repo: Path) -> None:
    assert agent_skills.main() == 0
    skill = (agent_skills.CLAUDE_SKILLS / "ops-demo" / "SKILL.md").read_text()
    prompt = (repo / ".github/prompts/ops-demo.prompt.md").read_text()
    assert "name: ops-demo" in skill and "allowed-tools:" in skill and "agent: agent" in prompt
    assert "`/ops-demo`" in (repo / ".github/copilot-instructions.md").read_text()


def test_a_generated_file_edited_by_hand_fails_the_check(repo: Path) -> None:
    prompt = repo / ".github/prompts/ops-demo.prompt.md"
    prompt.write_text(prompt.read_text() + "\nA hand edit.\n")
    assert agent_skills.main() == 1


def test_a_generated_file_with_no_page_fails_the_check(repo: Path) -> None:
    (repo / ".github/prompts/ops-gone.prompt.md").write_text("left over\n")
    assert agent_skills.main() == 1


def test_a_skill_named_like_a_process_skill_is_refused(repo: Path) -> None:
    page = repo / "docs/guide/skills/spec.md"
    page.write_text(PAGE.replace("ops-demo", "spec"))
    found = agent_skills.problems(agent_skills.expected())
    assert any("does not start with ops-" in p for p in found) and any("process skill" in p for p in found), found


def test_a_page_with_no_proof_block_is_refused(repo: Path) -> None:
    (repo / "docs/guide/skills/ops-demo.md").write_text(PAGE.split("```bash proof", maxsplit=1)[0])
    with pytest.raises(ValueError, match="no ```bash proof block"):
        agent_skills.expected()


def test_instructions_past_two_pages_fail(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_skills, "MAX_INSTRUCTION_WORDS", 20)
    found = agent_skills.problems(agent_skills.expected())
    assert any("words, over 20" in p for p in found), found


def test_the_committed_skills_match_their_pages() -> None:
    """The repository's own pages and generated files: make verify runs the same check."""
    files = agent_skills.expected()
    assert not agent_skills.problems(files) and not agent_skills.stale(files)
