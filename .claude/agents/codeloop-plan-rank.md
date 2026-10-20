---
name: codeloop-plan-rank
description: Run the rank stage of the plan lane for one codeloop card, using the manage skill.
---

# plan / rank

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `manage` skill (.claude/commands/manage.md). Track task progress — read/update tasks/todo.md
4. Write the result to `plan/{id}/ranked.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file plan/{id}/ranked.md --has 'rice:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
