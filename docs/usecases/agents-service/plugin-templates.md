# uc-590 Plugin templates

Status: current. Id: `uc-590`. Service: `agents-service`. Layers: api, sdk, cli, ui.
Cards: an earlier change, an earlier change (story group E of the planning repo `docs/plans/ops-ai/apps.html`, steps 22-23 and 30-32).

A plugin brings tools, and it can also bring the agents, skills, workflows and document types that use them. Until
now a team that turned a plugin on got its tools and nothing else: the templates were checked when the plugin was
validated and never offered. This use case lists a plugin's templates for the team that has it on, and installs each
one as the team's own copy through the checks a person's create goes through.

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
| S8 | A team admin lists the app's resources and adds one with `ops resources` | cli | 23 | 23 |
| S9 | On the app's Resources tab a person adds a resource to the team, and Added opens the team's copy | ui | 32 | 32 |

## Preconditions

| Needs | How |
|---|---|
| tools-service with plugins on and the test plugin loaded | `tools({"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": [services/tools-service/tests/plugin_templates/templates_desk]})`; with no platform-service the install switch is on for every plugin |
| agents-service reading tools-service's operations and templates | `agents(gateway_url=<tools>, kb_url=<that kb>)` |
| documents-service reading templates from tools-service | `kb(..., documents_env={OPS_TOOLS_URL: <tools>, platform sign-in})`, so one files-service serves both |
| People | Dev auth: Priya Shah (team_ops admin) turns the plugin on for team_ops; William Kamau (team_platform admin) is the team with it off |

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
| 23 | (cli) `ops resources list plugin:test.templates`, then `ops resources add plugin:test.templates case-helper` | Each exits 0; four resources; the agent's copy |
| 30 | `GET /v1/plugin-templates` on tools-service, the app's resources | The four resources; each is named `<source>:<template id>` for Add to team |
| 31 | `POST /v1/resources/plugin:test.templates:case-helper/copies` on agents-service twice (the agent was deleted in step 11), and `POST /v1/resources/plugin:test.templates:case-letter/copies` on documents-service | 201 then 200 with the same copy; the document type answers the copy step 7 made |
| 32 | (ui) Priya opens the templates desk's page › Resources, presses Add to team on the agent, comes back and presses Open, then adds the document type | Four rows each offer Add to team; the agent's copy opens at `/agents/{id}`, the row then reads Added and Open lands on the same copy; the document type's copy opens at `/document-types/{id}` |

## Scripts

| Layer | Script |
|---|---|
| api | `scripts/test-uc-590-api.py` |
| sdk | `scripts/test-uc-590-sdk.py` |
| cli | `scripts/test-uc-590-cli.py` |
| ui | `scripts/test-uc-590-ui.mjs` |
