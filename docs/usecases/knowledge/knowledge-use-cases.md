# Knowledge use cases

Status: current (design, 2026-11-12). Every use case that touches knowledge bases, their sources, documents and the
files under them, with what each proves and where the SDK, MCP and console layers stand.

Each page is written as: a short title; "In this example we will do X. It assumes Y and Z."; numbered steps through the
SDK, the CLI or the console, using the shared steps in the use cases README. The SDK is the main connecting point: a
console step is only written once the same step exists through the SDK.

## The list

| Id | Short title | What it proves | Layers | State |
|---|---|---|---|---|
| uc-080 | Cited answer from knowledge | An agent's answer cites the page and section it came from | api | api ok |
| uc-399 | Read knowledge usage and refs | A person with the cell reads their team's usage, refs and search; a service with the scope reads tenant-wide | api | api ok |
| uc-675 | Website source | A website source keeps a base current and answers cite it | api, sdk | ok |
| uc-676 | Typed text and pushed items | Typed pages and pushed items are indexed, versioned and cited; the same push changes nothing | api, sdk, ui | ok |
| uc-677 | Turn on rerank and rewrite | An owner turns them on and a hard question gets a better passage | api, sdk, ui | sdk and ui pass; CLI cannot set retrieval |
| uc-678 | SharePoint and Confluence sources | A team takes in libraries and spaces, kept current and cited | api, sdk, ui | ok |
| uc-129 | Add documents from Files | A builder adds files already in Files to a base | ui | ui ok |
| uc-096 | Knowledge base end to end | A person creates a base, adds files and a page, tests a question and retires it | ui | ui ok |
| uc-113 | Pick a base past the first hundred | The agent page's picker searches on the server | ui | ui ok |
| uc-138 | Knowledge pages follow what the caller may do | Edit and delete controls follow the record's own flags | ui | ui ok |
| uc-093 | Store a file once | A file is stored once, downloaded, held and deleted | api | not run |
| uc-094 | Another team's file is missing | Another team's file answers 404 on every route | api, ui | not run |
| uc-331 | Read a file with Detect | Detect runs from the Files page | api, ui | not run |
| uc-629 | File preview | A file's page shows its preview or says why not | ui | not run |
| uc-243 | Document types | Builders manage types, versions, samples and tests | ui | not run |
| uc-672 | Read a scan with a document type | A scan, a half scan and a filled form are each read once | api, sdk | ok |

## Merged, dropped, kept

| Change | Why |
|---|---|
| uc-113 folds into uc-096 as a step ("attach a base to an agent from the picker") | It proves one control that uc-096 already walks; its own stack start costs more than the check |
| uc-138 stays, limited to knowledge pages | The file sheet's flag belongs to the Files area list |
| Files, Detect and Document types leave this list | They are the Files area; they are listed here only because the base reads them |
| Nothing dropped as dead | Every listed script ran green or has not run; "not run" ones are in the Files area |

## What the layers need

| Layer | Today | Gap |
|---|---|---|
| SDK | `ops.knowledge.create/get/list/search`; sources and items through `ops.raw.kb` | No named SDK calls for sources and items; the shared step `addKnowledgeBase` wraps the raw ones |
| CLI | Not checked for knowledge | A CLI command to create a base and push an item would let a use case run it |
| MCP | The team address lists templates and skills | No knowledge search tool, so an assistant on the MCP address cannot ask a base a question |
| Console | uc-096, 129, 676, 677, 678 | Step 11-13 of uc-676 and the others walk the pre-move addresses; re-check with `/data/knowledge` |
