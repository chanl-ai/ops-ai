---
name: codeloop-build-research
description: Run the research stage of the build lane for one codeloop card, using the research skill.
---

# build / research

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `research` skill (.claude/skills/research/SKILL.md).
4. Write the result to `{spec}/research.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check research {id} --min-sources 3`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
