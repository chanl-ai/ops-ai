# Knowledge, source and file pages follow what the caller may do with each record

Status: current. Id: `uc-138`. Service: `console`, `kb-service` and `files-service`. Layers: ui.

The knowledge base page worked out from the team role whether to show its edit controls, the source page showed Delete
and its settings to everyone, and the file sheet offered Delete to a chat-only member. Each detail now carries canEdit
and canDelete from the write routes' own check (c-216), and the pages follow them.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, kb, files, platform-service and console (ISOLATED=1 adds 1000) |

Priya is Operations' admin and Ravi its viewer. The script uses Operations' first seeded knowledge base and source, and
uploads one file as Priya.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya and then Ravi open the base, the source's settings and the file | Each page is read-only exactly when the record's canEdit is false, and the file's Delete is off exactly when canDelete is false |
| 2 | Compare the two | Priya may change the base and Ravi may not |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-138-ui.mjs` | passing |
