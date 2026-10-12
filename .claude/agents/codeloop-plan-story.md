---
name: codeloop-plan-story
description: Run the story stage of the plan lane for one codeloop card, using the plan skill.
---

# plan / story

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `plan` skill (.claude/commands/plan.md). Plan a task — write spec to tasks/todo.md, enter plan mode
4. Write the result to `plan/{id}/stories.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file plan/{id}/stories.md --has 'acceptance:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
6. The card then waits at gate `backlog` for the owner. Stop there. Never run `codeloop approve` yourself.
