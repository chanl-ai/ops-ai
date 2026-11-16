# API changes in the standards migration

Status: current, 2026-11-15. Each service's API document changes where the standards call for it: the shared list
contract and its paging ([components.md](components.md), C2), typed bodies and replies (C5) and the standard error
reply. Old parameter names, filters and reply shapes are not kept. The console's data layer, both SDKs and the CLI are
updated later in this migration from this page; in-repo service clients and api-layer use-case scripts change in the
same commit as the route.

Each service has a table: one row per change, with what a caller must change. "Old form works" says whether a caller
that has not changed still gets the same answer.

## files-service

| Route | What changed | Before | After | What a caller must change | Old form works |
|---|---|---|---|---|---|

### Follow-ups for the SDK and console steps (files-service)

| Where | What to change |
|---|---|
