---
name: codeloop-build-live
description: Run the live stage of the build lane for one codeloop card, using the release skill.
---

# build / live

0. This stage changes something public. The card waits at gate `prod` as it enters. Do nothing until a person has approved it.
1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `release` skill (.claude/skills/release/SKILL.md).
4. Write the result to `evidence/{nnn}/prod.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file evidence/{nnn}/prod.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
