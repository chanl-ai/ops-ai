# uc-590 Plugin templates

Status: current. Id: `uc-590`. Service: `agents-service`. Layers: api, sdk, cli, ui.

A plugin brings tools, and it can also bring the agents, skills, workflows and document types that use them. Until
now a team that turned a plugin on got its tools and nothing else: the templates were checked when the plugin was
validated and never offered. This use case lists a plugin's templates for the team that has it on, and installs each
one as the team's own copy through the checks a person's create goes through. Stories S10 to S16 cover adding an
app's resources selectively once its sign-in is resolved: the state each resource shows, a preview of what a resource
brings with it, the dependencies a copy needs, names that clash, updates and removal, and an app's knowledge source.
They run on a second plugin, the service desk, written for each run by `scripts/resources_desk.py`: an agent, a skill,
a workflow whose agent step runs that agent, a document type, and a knowledge source of two help articles. A step
that fails there names behaviour the product does not have yet, and the expected result in the table below is the rule
it asserts.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team with the plugin on sees its agent, skill, workflow and document type; a team with it off sees none | api | 1-2 | 2 |
| S2 | A builder installs the plugin's agent as the team's draft with the plugin's tools; the same version again answers that copy, and once it is deleted a new one is made | api | 3-5 | 5 |
| S3 | The skill, the workflow and the document type install as the team's own records, and another team never sees them | api | 6-8 | 8 |
| S4 | A template of a plugin that is off for the team, a version the plugin does not ship, or a model alias nobody serves is refused with why, and nothing is made | api | 9-11 | 11 |
| S5 | A developer lists and installs a template through the Python SDK and gets the same copy as the API gives | sdk | 21 | 21 |
| S6 | The app's Resources list what it brings, and Add to team copies the agent on agents-service and the document type on documents-service, once | api | 30-31 | 31 |
| S7 | A developer adds a resource to the team through the SDK's `resources_copy_resource` | sdk | 22 | 22 |
| S8 | A team admin lists the app's resources and adds one with `opsai resources` | cli | 23 | 23 |
| S9 | On the app's Resources tab a person adds a resource to the team, and Added opens the team's copy | ui | 32 | 32 |
| S10 | Everyone in the team sees each resource and its state; a viewer cannot add one and is told so in plain words, a builder can | api | 40-42 | 41 |
| S11 | A builder previews several resources and adds them with what they depend on: a workflow before the agent it runs is refused naming it, bindings are the team's own, and the workflow runs the team's copy | api | 43-47 | 44 |
| S12 | A resource whose name the team already uses is refused with name_taken, and added under a name of the team's choosing | api | 48-50 | 48 |
| S13 | A changed template reads update available and never overwrites the team's edited copy; removing a copy names what uses it first; a template the app stops shipping leaves the copy, marked as removed by the app | api | 51-55 | 53 |
| S14 | An app's knowledge source is one of its resources, added to the team's knowledge base and synced; a team with the app off is refused | api | 56-58 | 57 |
| S15 | A developer lists an app's resources with their state, adds one with a binding, previews several, and removes a copy through the SDK's words | sdk | 60-63 | 60 |
| S16 | On the app's Resources tab a viewer reads who adds each resource; a builder ticks several, is told a workflow needs its agent first, sees Update available and Remove, and finds the app's knowledge source | ui | 70-76 | 72 |

## Preconditions

| Needs | How |
|---|---|
| tools-service with plugins on and the test plugin loaded | `tools({"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": [services/tools-service/tests/plugin_templates/templates_desk]})`; an installed plugin is there for every team, and each team turns it on for itself |
| agents-service reading tools-service's operations and templates | `agents(gateway_url=<tools>, kb_url=<that kb>)` |
| documents-service reading templates from tools-service | `kb(..., documents_env={OPS_TOOLS_URL: <tools>, platform sign-in})`, so one files-service serves both |
| People | Dev auth: Priya Shah (team_ops admin) turns the plugin on for team_ops; William Kamau (team_platform admin) is the team with it off |
| The service desk (S10 to S16) | `scripts/resources_desk.py` writes plugin `test.resources` 0.1.0 into the run's folder, beside the test plugin in `OPS_PLUGIN_PATHS`; step 55 starts tools-service again on 0.2.0, which drops the skill. kb-service starts with plugins on and the run's tools-service address, so it takes the desk's knowledge source |
| More people (S10 to S16) | James Richardson (team_ops builder) adds; Ravi Menon (team_ops viewer) only looks |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | (api) Priya turns the plugin on for team_ops (`PUT /v1/plugins/test.templates/team`) | 200 |
| 2 | (api) `GET /v1/templates` on agents-service and documents-service as team_ops, then as team_platform | team_ops: the agent, skill and workflow (agents-service) and the document type (documents-service), each with `installed.copies` 0; team_platform: none |
| 3 | (api) Install the agent (`POST /v1/resources/plugin:test.templates:case-helper/copies`) | 201; a draft agent in team_ops granting `templates_get_case` and `templates_close_case`; `needs` names the knowledge base and model alias left |
| 4 | (api) The same install again | 200 with the same copy; nothing new made |
| 5 | (api) Delete the agent, install again | 201 with a new agent |
| 6 | (api) Install the skill and the workflow | 201 each; a draft skill granting `templates_close_case`; a draft workflow under an id of its own |
| 7 | (api) Install the document type on documents-service | 201; a document type in team_ops with the template's fields, ready to read |
| 8 | (api) team_platform reads the copies | Not found for each |
| 9 | (api) team_platform installs the agent | 404 `template_not_found` |
| 10 | (api) Install the agent at version 1 | 404 `template_version_not_found` |
| 11 | (api) Install the agent with model alias `nobody-serves-this` after its copy is deleted | 422 `unknown_model_alias`; no agent made |
| 21 | (sdk) `templates_list_templates(kind="agent")` and `resources_copy_resource` as team_ops on a fresh install | The same list as the API; 201 then 200 with the same copy |
| 22 | (sdk) `resources_copy_resource("plugin:test.templates:close-politely", {})` | The skill's copy with its record id |
| 23 | (cli) `opsai resources list plugin:test.templates`, then `opsai resources add plugin:test.templates case-helper` | Each exits 0; four resources; the agent's copy |
| 30 | `GET /v1/plugin-templates` on tools-service, the app's resources | The four resources; each is named `<source>:<template id>` for Add to team |
| 31 | `POST /v1/resources/plugin:test.templates:case-helper/copies` on agents-service twice (the agent was deleted in step 11), and `POST /v1/resources/plugin:test.templates:case-letter/copies` on documents-service | 201 then 200 with the same copy; the document type answers the copy step 7 made |
| 32 | (ui) Priya opens the templates desk's page › Resources, presses Add to team on the agent, comes back and presses Open, then adds the document type | Four rows each offer Add to team; the agent's copy opens at `/agents/{id}`, the row then reads Added and Open lands on the same copy; the document type's copy opens at `/document-types/{id}` |
| 40 | (api) Priya turns the desk on; Ravi and James list `GET /v1/templates?source=plugin:test.resources` on agents-service and documents-service | 200; each sees the ticket helper, close-ticket skill, ticket triage workflow and ticket form, each with `installed.copies` 0 |
| 41 | (api) The same lists | Each row has `state` `available`; `canAdd` true for James on every row, and for Ravi only on the ticket form, since every member keeps the team's document types |
| 42 | (api) Ravi adds the agent | 403, the reason free of grid cells and team ids; nothing made |
| 43 | (api) James asks `POST /v1/resources/plan` for the workflow | 200 naming the ticket helper it runs, the tool `resources_get_ticket`, and the knowledge base and model alias left to bind |
| 44 | (api) James adds the workflow before the agent | 422 naming `ticket-helper`; no workflow made (one made is deleted) |
| 45 | (api) James adds the agent bound to team_platform's knowledge base | 422; no agent made (one made is deleted) |
| 46 | (api) James adds the agent with team_ops's "Help articles" base and a served model alias | 201; `needs` empty; the agent's `collections` and `model` are the ones given |
| 47 | (api) James adds the workflow | 201; its `ops.ai.agent` step runs the team's agent copy, not `ticket-helper` |
| 48 | (api) Priya makes a skill named "Close a ticket politely"; James adds the skill as it is | 409 `name_taken`; no skill made (one made is deleted, then Priya's skill) |
| 49 | (api) James adds the skill named "Close a ticket, desk" | 201; the skill carries that name |
| 50 | (api) Priya makes a document type "Ticket form"; James adds the ticket form as it is, then named "Ticket form, desk" | 409 `name_taken`, then 201 |
| 51 | (api) The desk's agent template changes on disk at the same version | The agent row's `installed.changed` is true; the team's agent keeps its instructions |
| 52 | (api) Priya edits the agent's instructions, then `POST /v1/resources/plugin:test.resources:ticket-helper/copies/{agent}/update` | 200 or 409 answering what the update changes; the agent keeps Priya's instructions |
| 53 | (api) Priya deletes the agent the workflow runs | 409 naming Ticket triage; nothing deleted |
| 54 | (api) Priya deletes the added ticket form | 204; the ticket form row reads `installed.copies` 0 |
| 55 | (api) tools-service starts again on the desk's 0.2.0, which ships no skill | The team's skill still opens; its row reads `state` `removed_upstream` |
| 56 | (api) `GET /v1/plugin-templates` on tools-service | The desk's resources include a `knowledge_source` |
| 57 | (api) Priya adds the desk's help articles to "Help articles" (`POST /v1/sources`, type tool), then syncs | 201, sync 200; the source holds "Replace a meter" and "Reset a password" |
| 58 | (api) team_platform adds the same source | 400 or 422 telling it to turn the app on |
| 60 | (sdk) James: `ops.resources.list("plugin:test.resources")` | The four resources, each with `state` `available` and `installed.copies` 0 |
| 61 | (sdk) James: `ops.resources.add(<the agent's item>, modelAlias=<served>)` | Created; the agent's model is that alias; `needs` names the knowledge base left |
| 62 | (sdk) James: `ops.resources.plan([workflow, skill])` | What each brings, naming the ticket helper |
| 63 | (sdk) James: `ops.resources.update` and `ops.resources.remove(<the copy>)` | Both exist; remove deletes the agent |
| 69 | (ui) Priya turns the desk on through the API | 200 |
| 70 | (ui) Ravi opens the desk's Resources tab | Four rows; no Add to team on the agent, skill and workflow, and the words "A builder adds this" |
| 71 | (ui) Priya opens the same tab | A checkbox on each row and one Add selected |
| 72 | (ui) Priya presses Add to team on the workflow | The page names Ticket helper and opens no workflow (one opened is deleted) |
| 73 | (ui) Priya's agent copy is made through the API, then the desk's agent template changes on disk | The tab reads Update available |
| 74 | (ui) The same tab | An added row offers Remove |
| 75 | (ui) The same tab | Help articles is listed |
| 76 | (ui) Every page of the walk | No page errors |

## Scripts

| Layer | Script |
|---|---|
| api | `scripts/test-uc-590-api.py` |
| sdk | `scripts/test-uc-590-sdk.py` |
| cli | `scripts/test-uc-590-cli.py` |
| ui | `scripts/test-uc-590-ui.mjs` |
| The service desk plugin, written per run (api, sdk, ui) | `scripts/resources_desk.py` |
