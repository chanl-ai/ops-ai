# ADR-0009 Chat experience inside the platform

Status: accepted (draft for review). Formerly DR-9.

## Context

End users (operations staff, relationship managers, the call centre, per Knowledge requirement 9)
need to chat with agents inside the platform and see data visualised in the conversation.
The mock already treats a chat agent as the workflow "Chat message → Agent → Reply" and lists a chat
widget as a deployment channel. Every user is bank staff: the widget deploys only to intranet portals
behind staff SSO, and public, customer-facing deployment is out of scope. The question is which
chat front end to use, how sessions run, and how interactive tool UIs are governed. This record fixes the architectural choices; the full chat
design is in [`07`](../../specs/07-agent-chat.md).

**MCP Apps** is the relevant standard. It is the first official MCP extension, stable at spec
version 2026-01-26, co-developed from the community MCP-UI project and OpenAI's Apps SDK ([spec][mcp-apps-spec],
[summary][mcp-apps-status], secondary). A tool declares a `ui://` resource in `_meta.ui.resourceUri`;
the host fetches it and renders it in a sandboxed iframe; the app talks to the host over JSON-RPC on
`postMessage` and can request tool calls, which the host forwards and may restrict; `_meta.ui.csp`
lists allowed external origins ([overview][mcp-apps]). Hosts listed include Claude, VS Code GitHub
Copilot and Microsoft 365 Copilot ([overview][mcp-apps]). ChatGPT supports the standard fields and
adds optional `window.openai` extensions such as checkout and file upload, which hosts other than
ChatGPT do not provide ([comparison][mcp-apps-openai], secondary). An earlier spike by the delivery
team rendered an MCP App card in a third-party assistant with a button calling a tool back.

## Options

| Option | What it is | Key facts |
|---|---|---|
| **A. Build on the Vercel AI SDK with assistant-ui, rendering MCP Apps through the MCP Apps host bridge** | Chat inside our Next.js console, our components | AI SDK is Apache 2.0, provider-agnostic, `useChat` with custom transports and tool parts ([repo][ai-sdk], [licence][ai-sdk-lic], [useChat][ai-sdk-chat]). assistant-ui is MIT, renders tool calls as React components with inline approvals, works with AI SDK and LangGraph backends ([repo][assistant-ui]). The MCP Apps SDK ships an App Bridge for hosts, and `@mcp-ui/client` provides React renderers ([overview][mcp-apps]) |
| B. Adopt LibreChat | Self-hosted ChatGPT-style app | MIT, multi-user auth, RBAC, MCP ([repo][librechat]); MCP Apps support merged 2026-09-24, off by default, using a separate sandbox origin ([PR 13831][librechat-apps]) |
| C. Adopt Open WebUI | Self-hosted chat app | Modified BSD licence that forbids removing its branding above 50 users in 30 days without an enterprise licence ([licence][openwebui-lic]) |
| D. CopilotKit | SDK for in-app copilots with generative UI and AG-UI protocol | MIT ([repo][copilotkit]); persistence and memory in a paid tier |
| E. Vendor assistant (Microsoft 365 Copilot, ChatGPT Enterprise, Claude) | The bank's existing assistant calls our workflows | M365 Copilot and Claude host MCP Apps ([overview][mcp-apps]); our platform would expose MCP and A2A endpoints |

### Criteria and scores

| Criterion | Weight | A | B | C | D | E |
|---|---|---|---|---|---|---|
| Sessions run through our runtime, gateways, entitlements and audit without a second path | 25 | 5 | 3 | 2 | 4 | 3 |
| One product with the console (same shell, components, login) and the intranet chat widget deployment | 15 | 5 | 2 | 2 | 4 | 1 |
| MCP Apps rendering with host-side control of tool calls | 15 | 4 | 4 | 2 | 3 | 4 |
| Licence and vendor risk | 15 | 5 | 5 | 2 | 4 | 3 |
| Time to first usable chat | 15 | 3 | 5 | 5 | 4 | 3 |
| Marginal effort per new chat agent (a template, no front-end work) | 15 | 5 | 4 | 4 | 4 | 4 |
| **Weighted total** | 100 | **4.55** | **3.75** | **2.75** | **3.85** | **3.00** |

## Decision

Option A. The chat lives in the Ops AI console and in the intranet widget deployment (staff SSO), built on AI SDK
`useChat` with a transport to our control plane, assistant-ui components wrapped in the console's
shared components, and MCP Apps rendered through the MCP Apps host bridge. Option E is added later
as a channel: the same published workflows are reachable from the bank's assistant through MCP or
A2A, under the same gateway checks. LibreChat (B) is the fallback if time to first chat becomes the
binding constraint.

Deployments are for bank staff only: the in-console chat and an intranet widget behind staff SSO.
The mock's public, customer-facing chat widget deployment is removed, in line with the design
lessons on public endpoints.

**How a chat session runs.**

| Concern | Design |
|---|---|
| Unit | A chat agent is a workflow created from a chat template; each conversation is one run; each user message is a Temporal Update to that run |
| Streaming | Temporal history records each completed turn; tokens stream from the agent-block activity to the browser over a server-sent-events channel keyed by run and turn, so streaming never goes through workflow history |
| Identity | The user's token is exchanged for a delegation token (`sub` = user, `act` = workflow), so every tool call is checked against the user's entitlements (ADR-0005). Chat is the first feature that needs user delegation |
| Tools and knowledge | Through the data gateway with the workflow's module scopes, exactly as in the email workflow |
| Models | Through the AI gateway with the workflow's key and budget |
| Writes | A write proposed in chat becomes a drafted action. If the user is entitled and the risk tier allows self-approval, the user's confirmation in the chat signs the approval token; otherwise it goes to the review queue like any other action |
| Audit | Same run journal, gateway logs and audit export as workflows; chat transcripts follow the retention rule set by [open question 4](../overview.md#open-questions) |
| Testing | The chat template has a suite like any workflow; the mock's agent Test sheet runs against a draft |

**How MCP Apps are governed.**

| Control | Design |
|---|---|
| Where apps come from | Only from tool modules registered at the data gateway. A module's `ui://` resources are part of the module version, reviewed with it and pinned by the workflow, so an app cannot change under a published workflow |
| Who serves them | The data gateway serves the MCP servers and their UI resources; the browser never connects to a module directly |
| Sandbox | Rendered in an iframe on a dedicated sandbox origin separate from the console, the pattern LibreChat also uses ([PR 13831][librechat-apps]); apps are bundled into one file, and the host's CSP allows no external origins unless the module's approval lists them |
| App-initiated tool calls | Forwarded by the host to the data gateway under the user's delegation token and the workflow's scope; an app can call only tools in its own module version, and write tools still need an approval token |
| Host capabilities | Open-link, file and other host capabilities off by default; `window.openai` extensions are not provided |
| Data shown | Only what the tool returned under the user's entitlement; nothing is fetched by the app directly |
| Logging | Every app-initiated call is logged at the gateway with `origin = app` and the UI resource version |

## Consequences

### Strongest counter-argument and our answer

**"LibreChat already does multi-user chat, MCP and MCP Apps, under MIT. Building is slower."** It is
slower to first chat. LibreChat is a separate application with its own users, agents, storage and
MCP connections, so chat sessions would bypass our runtime, registry and gate unless we rebuild its
backend around them, and its MCP Apps support is weeks old and off by default. Building on the AI SDK
keeps one product, one session model and one audit trail, and reuses the console's components. If
the bank wants chat before phase 2, LibreChat pointed at our MCP endpoint is a reasonable interim.

### What would change this decision

- The bank standardises on Microsoft 365 Copilot as the only chat surface for staff: then option E
  first, and our chat UI only for the intranet widget.
- assistant-ui or the AI SDK cannot render MCP Apps with host-side call control in a phase-2 spike:
  then CopilotKit or LibreChat's renderer.

## Phase 1 vs later

| Phase 1 | Later (phase 2) |
|---|---|
| Nothing user-facing. Phase 1 builds what chat reuses: the data gateway speaking MCP, the workflow identity model, the run journal, and the agent Test sheet | Chat template, in-console chat and intranet widget behind staff SSO, user delegation, MCP Apps host with sandbox origin, first app-enabled modules (case summary, account view), then MCP and A2A exposure to the bank's assistant |

## Sources

[ai-sdk]: https://github.com/vercel/ai
[ai-sdk-chat]: https://ai-sdk.dev/docs/ai-sdk-ui/chatbot
[ai-sdk-lic]: https://raw.githubusercontent.com/vercel/ai/main/LICENSE
[assistant-ui]: https://github.com/assistant-ui/assistant-ui
[copilotkit]: https://github.com/CopilotKit/CopilotKit
[librechat]: https://github.com/danny-avila/LibreChat
[librechat-apps]: https://github.com/danny-avila/LibreChat/pull/13831
[mcp-apps]: https://modelcontextprotocol.io/extensions/apps/overview
[mcp-apps-openai]: https://mcp.directory/blog/mcp-apps-standard-vs-openai-apps-sdk-2026
[mcp-apps-spec]: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
[mcp-apps-status]: https://technyanai.com/articles/en/20260126/mcp-apps-official-extension
[openwebui-lic]: https://github.com/open-webui/open-webui/blob/main/LICENSE
