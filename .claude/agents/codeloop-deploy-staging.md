---
name: codeloop-deploy-staging
description: Run the staging stage of the deploy lane for one codeloop card, using the deploy skill.
---

# deploy / staging

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `deploy` skill (.claude/commands/deploy.md). Deploy to staging or production with verification gates
4. Write the result to `deploy/{id}/staging.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file deploy/{id}/staging.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
