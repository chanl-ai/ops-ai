---
name: codeloop-market-brief
description: Run the brief stage of the market lane for one codeloop card, using the plan skill.
---

# market / brief

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `plan` skill (.claude/commands/plan.md). Plan a task — write spec to tasks/todo.md, enter plan mode
4. Write the result to `marketing/{id}/brief.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file marketing/{id}/brief.md --has 'audience:' 'claim:' 'metric:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
