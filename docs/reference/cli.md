# The opsai command line

Status: current. The command list matches version 1.0.0.

The opsai command does from a terminal what the console does: author and publish agents and workflows, start runs, decide Human
tasks, chat, and manage apps, knowledge, secrets and people. Reach for it in scripts and CI, or when a change is easier
to keep as a file than to click through. It ships with the Python SDK and calls the same API with the same
permissions.

## Try it

Install it as [Install the CLI](../guide/install-cli.md) shows, then sign in and start a test run:

```bash
opsai login --base-url https://ops.example.com --team team_claims
opsai people me
opsai runs start wf_card_dispute --input "cardholder=Jordan Example,amount=120.00" --wait
```

`opsai login` asks for your work email and password and keeps the session in a profile. A run is a test run unless you pass `--live`; a test run uses an app's test account when it has one.

## Options every command takes

| Option | What it does | Default |
|---|---|---|
| `--profile NAME` | Which saved sign-in to use | The current profile, or `OPS_PROFILE` |
| `--team TEAM` | The team the command acts in | The profile's team, or `OPS_TEAM` |
| `--base-url URL` | The install's address | The profile's address, or `OPS_BASE_URL` |
| `--json` | Machine-readable output | Text for people |
| `--quiet` | Print only what a script needs | Off |

Profiles are kept in `~/.config/ops-ai/config.json`, readable only by you; `OPS_CONFIG` names another file. An API key in
`OPS_API_KEY` is used instead of a saved session. The command exits 0 when done, 1 when refused or failing, and 2 for a
usage or setup problem.

## Commands

| Area | Verbs | For |
|---|---|---|
| `login` | | Sign in and keep the session in a profile |
| `workflows` | `init`, `validate`, `plan`, `apply`, `export`, `publish`, `pause`, `archive`, `run`, `list`, `forms`, `batch-start`, `batch`, `watch`, `inspect`, `trace`, `test`, `retry`, `decide`, `schedule` | Author a workflow as a file, publish it and run it; `schedule show\|save\|clear\|kinds\|preview` sets when it runs by itself (`set` still works for `save`) |
| `agents` | `validate`, `apply`, `export`, `publish`, `pause`, `chat`, `run`, `test`, `trace`, `list`, `tool-options`, `grant-tools` | Author an agent, grant it tools, test and publish it |
| `chat` | `agents`, `threads`, `start`, `say`, `show`, `calls`, `approve`, `reject`, `submit`, `transcript`, `script`, `evals` | Chat as the chat screen does; script a conversation and score it |
| `runs` | `list`, `start`, `show`, `events`, `cancel`, `retry` | Start and follow workflow runs |
| `tasks` | `list`, `types`, `show`, `decide`, `approve` | Work the Human tasks queue |
| `cases` | `list`, `types`, `show`, `note` | Read cases and add notes |
| `threads` | `list`, `show`, `inbox` | Read conversations |
| `apps` | `list`, `show`, `add-tool`, `accounts`, `mine`, `connect`, `test`, `auth-configs` | Turn on apps and connect accounts |
| `connectors` | `list`, `disconnect` | Your own sign-ins on apps |
| `tools` | `list`, `show`, `run`, `discover`, `import`, `request-review`, `decide-review`, `publish`, `calls` | Take an OpenAPI description to a published tool, and read the call log |
| `secrets` | `list`, `create`, `rotate`, `rename`, `delete` | The team's secrets; a value is read from `--value` or standard input and never printed |
| `egress` | `list`, `allow-host`, `allow-range`, `remove-host`, `remove-range` | The hosts and ranges tools may reach (Security admins) |
| `policies` | `get`, `set` | The team's policies |
| `kb` | `bases`, `sources`, `items`, `add-file`, `add-text`, `sync`, `search`, `changes` | Knowledge bases and what is in them |
| `files`, `documents` | `list`, `show`, `upload`, `limits`; document types and extractions | Files and what is read from them |
| `resources`, `templates` | `list`, `plan`, `add`, `update`, `remove`; `list`, `install` | Copy an app's agents, skills and workflows, or a template, into the team |
| `skills`, `guardrails`, `widgets` | `list`, `show` | Read the team's skills, guardrails and widget templates |
| `people` | `list`, `invite`, `roles`, `role`, `me` | Members, invites and roles; an invite is printed unless `--send` |
| `models` | `aliases`, `providers`, `keys`, `test` | Model aliases and their prices; providers and keys for account admins (no key value is shown) |
| `memories` | `list`, `forget`, `forget-agent`, `export` | What agents remember about you |
| `test-data` | `list`, `clean --confirm` | Find and remove what test runs made |
| `plugin` | `validate`, `test` | Build and check a plugin (needs the plugin extra) |

`opsai <area> --help` lists each verb's arguments.

## Limits

- `workflows form`, `eval`, `replay` and `fork` are listed by the command but planned; they do nothing yet.
- `opsai login` signs in with a password only. Where people sign in through the company's provider, use an API key
  in `OPS_API_KEY` instead; signing in through the provider from the command line is planned.
- `ops` is accepted as the old name for one release and prints a note; use `opsai`.

## Next

<!-- site: cards -->
- **[Install the CLI](../guide/install-cli.md)**: Install it, including from a private package index.
- **[Python SDK](../sdk/python.md)**: The same calls from Python.
- **[HTTP API](http-api.md)**: The routes underneath every command.
