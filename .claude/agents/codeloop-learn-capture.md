---
name: codeloop-learn-capture
description: Run the capture stage of the learn lane for one codeloop card, using the reflect skill.
---

# learn / capture

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `reflect` skill (.claude/commands/reflect.md). Session-end reflection — capture what you learned
4. Write the result to `learn/{id}/capture.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file learn/{id}/capture.md --has 'gotcha:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
