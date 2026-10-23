# The console has no preview mock pages

Status: current. Id: `uc-517`. Service: `console` on agents-service and tools-service. Layers: ui. Card: c-517.

The console served development-only copies of its pages under `/preview/` beside the real ones, so what the maintainers
reviewed could drift from what shipped. The copies are deleted. The pieces they drew that the real pages lacked are
built: an agent's ID to copy, and adding an allowed host in place from a tool whose request goes to an unlisted one,
with the Egress page's own form. Only `/preview/human-tasks` stays, until the maintainers picks its layout.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens an agent | Its Settings tab shows the Agent ID with a copy button |
| 2 | James starts Import operations, HTTP, and types a request to `statements.uc517.example` | "statements.uc517.example is not an allowed host"; a Security admin can add it; no Add button |
| 3 | Sam, a Security admin, does the same and presses Add allowed host | The Egress form opens with the host filled in; adding it clears the notice, the import stays on its step, and the host is on the allowlist |
| 4 | Anyone opens a former preview route | 404 for home, case-story, start-run, deployments, access, channels, settings and workflow-layout; human-tasks still opens |
| 5 | Through all of it | No page error |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-517-ui.mjs` | passing |

## Non-vacuous check

With the agent settings, the agent page and the tool request builder at their versions from before c-517, steps 1 to 3
fail: no Agent ID field, no host notice, no Add allowed host. Step 4 failed during the build while the settings and
workflow-layout mocks still answered 200. On the card's last commit all five pass (`uc-red.txt` and `uc-green.txt`
under `evidenceDir('517')`).
