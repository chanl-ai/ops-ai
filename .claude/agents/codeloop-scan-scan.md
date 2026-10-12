---
name: codeloop-scan-scan
description: Run the scan stage of the scan lane for one codeloop card.
---

# scan / scan

1. Run `codeloop card show <id>`. It prints the output path, the done check, the stage notes and any earlier rejection notes. Follow those over anything remembered.
2. Run `codeloop wiki inject --files <files you expect to touch>` and read every page it prints.
3. Do the work for the `scan` stage.
4. Keep the change inside what the card asks for.
5. Run `codeloop card advance <id>`. It runs `codeloop scan competitors`. If it exits 2, read the output, fix the work and run it again. Stop after 3 failures: the card parks as stuck for the owner.
