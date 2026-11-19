# MCP

Status: current. Team tools over MCP are built behind an install switch; agents over MCP are planned.

Give an AI assistant such as Claude, Cursor or ChatGPT your team's tools without handing it any credentials. Ops AI
serves a team's tools at one MCP address; the assistant's calls go through the same tool gateway as an agent's, so
they meet the same permissions, approvals, limits, masking and records.

## Try it

Copy the team's address from the console under Channels › MCP, then add it to the assistant. A client that takes a
JSON configuration:

```json
{
  "mcpServers": {
    "ops-ai-claims": {
      "url": "https://ops.example.com/mcp/team_claims",
      "headers": { "Authorization": "Bearer ok_..." }
    }
  }
}
```

With an API key in the header, the assistant connects at once. Without one, the assistant opens a browser, you sign in
to Ops AI and allow the connection on a consent page; the connection then lasts 8 hours by default.

## How it works

| Part | Behaviour |
|---|---|
| Team address | `/mcp/<team>` lists the team's read tools the caller may use, the team's published skills as prompts, and template tools |
| MCP links | `/mcp/<team>/<link>` serves a chosen set of the team's tools and published workflows, made on Channels › MCP. Any other tool is refused; a paused link answers that it is paused; each call is recorded with the link |
| Who the call is for | The person who signed in, or the API key's team, with their own permissions. The address's team must be theirs |
| Test runs | Every call is a test run: it uses an app's test account when the team has one |
| Writes | A write waits for a person's approval, whatever the team's approval settings |
| Records | Every call is in the tool call log, marked as coming over MCP with the client's name |

## Options

| Setting | What it does | Default | Who changes it |
|---|---|---|---|
| MCP address on this install | Serves the MCP addresses. While off, an address answers that MCP is off for this install | Off | The operator, in the install's feature flags |
| Assistant connection length | How long an assistant stays connected before the person signs in again | 8 hours, at most 30 days | A Security admin, in Governance › Policies |
| Connected assistants | See and disconnect the assistants you allowed | | Each person, in My security |

## Limits

- Agents over MCP are planned. Today an assistant reaches a team's tools, its skills and, through a link, its
  workflows.
- The team address lists read tools only; a write is reached through a link or by name, and waits for a person.
- Keys bound to one link, and a rate limit per token, are planned.

## Next

<!-- site: cards -->
- **[Egress and connections](../security/egress-and-connections.md)**: The gateway every MCP call goes through.
- **[Access, approvals and audit](../security/access-approvals-and-audit.md)**: How a held write is approved.
- **[HTTP API](http-api.md)**: API keys and the routes behind MCP links.
