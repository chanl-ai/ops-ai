---
name: codeloop-deploy-smoke
description: Run the smoke stage of the deploy lane for one codeloop card, using the debug skill.
---

# deploy / smoke

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `debug` skill (.claude/commands/debug.md). Investigate production issues — search logs, check health, create regression tasks
4. Write the result to `deploy/{id}/smoke.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file deploy/{id}/smoke.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
