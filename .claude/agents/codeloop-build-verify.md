---
name: codeloop-build-verify
description: Run the verify stage of the build lane for one codeloop card, using the verify skill.
---

# build / verify

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `verify` skill (.claude/skills/verify/SKILL.md).
4. Write the result to `evidence/{nnn}/verify.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop verify {id}`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
6. The card then waits at gate `local` for the owner. Stop there. Never run `codeloop approve` yourself.
