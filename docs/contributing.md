# Contributing

Status: current.

How Ops AI is built, for someone changing it: the architecture and the decisions behind it, the standards a change is
reviewed against, each service and package, the use cases that prove each feature, the designs in progress and the
release process. How to set up, branch, commit and open a pull request is in the contributing guide at the root of
the repository.

## Where to start

<!-- site: cards -->
| Area | What it holds |
|---|---|
| [Architecture](architecture/README.md) | The system as built: the services, one request end to end, runtime, identity, data and operations, and the decision records |
| [Engineering standards](architecture/engineering-standards.md) | The rules a change is reviewed against, each with its id, an example and the check that enforces it |
| [Services](services/README.md) | One page per service: what it does, its routes and tables, its tests |
| [Packages](packages/ops_signin/overview.md) | The shared libraries the services build on: sign-in, email, document reading, logging and the use-case runner |
| [Use-case test catalogue](usecases/README.md) | The end-to-end checks that prove each feature, by area, and how to run them |
| [Design proposals](design/workflows/workflows-and-agents.md) | Designs proposed or approved, the console's screens and plans, and the prior-art research behind them |
| [Agent skills](guide/skills/ops-run.md) | The skills a coding assistant uses in this repository: run the stack, write docs, add a tool module or a workflow step |
| [Release process](deploy/release.md) | How a release is cut, tested on staging, tagged and shipped, and the team's own environments |

## Next

<!-- site: cards -->
- **[Contributing guide](../CONTRIBUTING.md)**: Set up, branch, commit and open a pull request.
- **[All documents](README.md)**: Every page in the repository's docs, with one line on each.
