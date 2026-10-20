---
name: codeloop-build-review
description: Run the review stage of the build lane for one codeloop card, using the review skill.
---

# build / review

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `review` skill (.claude/skills/review/SKILL.md).
4. Write the result to `evidence/{nnn}/review.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file evidence/{nnn}/review.md --has 'verdict: approve'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
6. The card then waits at gate `pr` for the reviewer. Stop there. Never run `codeloop approve` yourself.
