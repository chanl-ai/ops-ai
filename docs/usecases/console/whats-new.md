# What's new tells people what changed, in plain words

Status: current. Id: `uc-510`. Service: `console`. Layers: ui. Card: an earlier change.

People using Ops AI had no way to see what a merge changed without reading commits, which name files and cards. The
console now has What's new in the sidebar footer: the repo's changelog entries, newest first, each a tag, a date, a title
and one or two sentences, with a Coming next tab for the roadmap. A dot marks an entry this person has not opened.

## Preconditions

| Needs | How |
|---|---|
| A private stack with platform sign-in | `withUiStack(..., { platform: true })` |
| James Richardson, password `northfield-demo` | The platform seed |
| Entries under `changelog/` and items in `roadmap.json` | The repo; the build reads them (`apps/console/next.config.ts`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sign in fresh and open What's new | The dot shows; the first entry is the newest; no card id or file path anywhere in the popover |
| 2 | Open Coming next | Every roadmap item's title is listed |
| 3 | Close and reload | No dot |
| 4 | In a tab whose storage refuses the seen list, open What's new, close, reload | The popover opens; the dot is back after the reload |
| 5 | At 1280 px, find What's new and open it | A round 48 px button in the bottom-right corner, not in the sidebar; the popover ends with "Version" and the release tag (`v2026-10-23.1`) or `main · <short commit>` |
| 6 | At 375 px, open it | The popover opens upward inside the screen; no sideways scroll |
| 7 | Through all of it | No page error |
| 8 | With the console's release switches off, open What's new | No entry for a feature behind a switch is listed: plugins, a person's own sign-in |

The non-vacuous check is step 3: before the popover remembered what was opened, the dot showed on every load.
Step 5 fails on the sidebar version: its trigger sits in the sidebar footer and the popover has no version line.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-510-ui.mjs` | passing |
