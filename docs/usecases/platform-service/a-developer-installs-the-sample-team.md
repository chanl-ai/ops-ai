# A developer installs the sample team with one command, and a second run makes nothing

Status: current. Id: `uc-563`. Service: `platform-service` with every service the sample team uses. Layers: cli.
Card: an earlier change.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A developer runs the sample team installer and it makes a team, its people and their records | cli | 1 | 1 |
| S2 | Running it again finds everything and makes nothing | cli | 2 | 2 |
| S3 | The team's lead signs in and finds the sample agents and workflows the installer made | cli | 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The use case stack with platform sign-in, the fake model, kb, files and documents, and tools-service with the core fake bank | `withUiStack(..., { platform: true, demo: true, tools: { bank: 'core', gateway: true, mail: true } })` |
| Wanjiru Kamau (workspace admin, can make teams), password `northfield-demo` | The platform seed |

The installer is `scripts/sample_team.py install`, the command `make sample-team` runs. The script runs it with
`--name "CLI bank <tag>"` (a team of its own) and `--no-levy` (the levy story's code module and workflows need the
documents model). Its lines go to `.logs/usecase/uc563-install-*.log`, never to the script's output, because the
installer's FAIL lines are not the script's checks.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `uv run python scripts/sample_team.py install --origin <console> --admin-env <file> --name "CLI bank <tag>" --no-levy` | Exit 0, at least one MADE line, no FAIL line |
| 2 | The same command with `--expect-found` | Exit 0, no MADE line, FOUND lines, no FAIL line |
| 3 | Alex Morgan, the team's lead the installer added, signs in; `GET /v1/teams`, then the team's agents and workflow definitions | The team is listed; it holds at least three agents and one workflow |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| cli | `platform-service/scripts/test-uc-563-cli.mjs` | passing |

## Non-vacuous check

Step 2: `--expect-found` turns every MADE line into a FAIL, so an installer that stops finding a record by name and
makes it again fails this step.
