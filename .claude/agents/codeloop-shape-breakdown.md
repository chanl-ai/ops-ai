---
name: codeloop-shape-breakdown
description: Run the breakdown stage of the shape lane for one codeloop card, using the breakdown skill.
---

# shape / breakdown

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `breakdown` skill (.claude/skills/breakdown/SKILL.md).
4. Write the result to `shape/{id}/breakdown.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check breakdown {id}`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
