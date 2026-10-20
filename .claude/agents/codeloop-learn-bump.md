---
name: codeloop-learn-bump
description: Run the bump stage of the learn lane for one codeloop card, using the reflect skill.
---

# learn / bump

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `reflect` skill (.claude/commands/reflect.md). Session-end reflection — capture what you learned
4. Write the result to `learn/{id}/bump.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file learn/{id}/bump.md --has 'freq:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
