---
name: codeloop-wiki-architecture
description: Run the architecture stage of the wiki lane for one codeloop card, using the architecture skill.
---

# wiki / architecture

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work with the `architecture` skill.
4. Write the result to `.codeloop/wiki/architecture/overview.md`.
5. Run `codeloop card advance <id>`. It runs `codeloop check architecture`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
6. The card then waits at gate `wiki` for the owner. Stop there. Never run `codeloop approve` yourself.
