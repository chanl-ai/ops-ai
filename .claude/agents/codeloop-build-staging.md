---
name: codeloop-build-staging
description: Run the staging stage of the build lane for one codeloop card, using the release skill.
---

# build / staging

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `release` skill (.claude/skills/release/SKILL.md).
4. Write the result to `evidence/{nnn}/staging.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file evidence/{nnn}/staging.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
