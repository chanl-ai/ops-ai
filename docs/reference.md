# Reference

Status: current. Agents over MCP are planned; everything else on this tab is built.

Look up the exact shape of a call once you know what you want to build. Every surface below reaches the same API under
the same permissions, so pick the one that fits where your code runs.

## Surfaces

<!-- site: cards -->
1. **[HTTP API](reference/http-api.md)**: Sign-in headers, list paging, errors, and every route, generated from the release you run.
2. **[Python SDK](sdk/python.md)**: Start workflows, decide their tasks and manage a team from Python.
3. **[TypeScript SDK](sdk/typescript.md)**: The same client for Node and the browser.
4. **[The opsai command line](reference/cli.md)**: Every area of the product from a terminal, for scripts and CI.
5. **[MCP](reference/mcp.md)**: A team's tools in Claude, Cursor or ChatGPT, through the same gateway as an agent.
6. **[SDK 1.0.0 changelog](sdk/changelog.md)**: What changed for callers in 1.0.0, and [how to upgrade](sdk/upgrading.md).

## Which one to use

| You are | Use |
|---|---|
| Writing a service or script in Python or TypeScript | The SDK: paging, retries and errors are handled |
| Calling from another language or a system that only speaks HTTP | The HTTP API |
| Automating from a shell or a CI job | `opsai` |
| Giving an AI assistant your team's tools | MCP |

## Next

<!-- site: cards -->
- **[Quickstart](guide/quickstart.md)**: Run Ops AI and your first workflow before reaching for the reference.
- **[Upgrading to 1.0.0](sdk/upgrading.md)**: What changed in the SDKs and how to move to it.
