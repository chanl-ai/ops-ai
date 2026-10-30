# A crafted PDF runs no script in the viewer

Status: current. Id: `uc-398`. Service: `console`. Layers: ui. Card: an earlier change.

PDF.js before 6.2.108 runs a document's JavaScript in the page's own origin when scripting is on and no CSP blocks it
(GHSA-hq66-cqwq-w95j, CVE-2026-16633). The console's viewer opens uploaded bank documents, so a document's scripts must
never run there. The viewer draws pages to a canvas and builds no annotation layer, which is where PDF.js binds
document scripts, and it loads the patched release.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and the demo seed | `make db-up`; the use-case stack seeds itself |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James uploads a PDF whose open action, page link and form field each carry JavaScript that alerts, submits to a marker URL and logs a marker | The upload completes |
| 2 | He opens the file's page, then leaves it | The viewer draws page 1; no dialog opens, no request reaches the marker URL, nothing logs the marker, and neither the page nor leaving it raises an error |
| 3 | The worker the browser loaded names its PDF.js version | 6.2.108 or later |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-398-ui.mjs` | passing |
