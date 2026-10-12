---
name: codeloop-deploy-prod
description: Run the prod stage of the deploy lane for one codeloop card, using the ship skill.
---

# deploy / prod

0. This stage changes something public. The card waits at gate `prod` as it enters. Do nothing until a person has approved it.
1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `ship` skill (.claude/commands/ship.md). Close the loop — QA, deploy staging, deploy prod, verify, close task
4. Write the result to `deploy/{id}/prod.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file deploy/{id}/prod.md --has 'result: pass'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
