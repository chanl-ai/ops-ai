---
name: codeloop-market-draft
description: Run the draft stage of the market lane for one codeloop card, using the design skill.
---

# market / draft

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `design` skill (.claude/commands/design.md). Architecture before code — generate lightweight spec from codebase analysis
4. Write the result to `marketing/{id}/blog.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check file marketing/{id}/blog.md --has 'claim:'`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
6. The card then waits at gate `copy` for the owner. Stop there. Never run `codeloop approve` yourself.
