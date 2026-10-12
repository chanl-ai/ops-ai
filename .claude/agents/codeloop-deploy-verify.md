---
name: codeloop-deploy-verify
description: Run the verify stage of the deploy lane for one codeloop card, using the qa skill.
---

# deploy / verify

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `qa` skill (.claude/commands/qa.md). Quality gate — run all checks before promoting a task
4. Write the result to `deploy/{id}/verify.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file deploy/{id}/verify.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
