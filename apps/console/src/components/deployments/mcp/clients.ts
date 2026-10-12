/**
 * How each assistant client takes the workspace MCP URL. Every client signs in through the workspace SSO
 * (OAuth), so no snippet carries a key. Claude Desktop reaches remote servers through Settings → Connectors;
 * its JSON config file only starts local servers, so it gets steps and the URL.
 */
export interface ConnectClient {
  id: string;
  name: string;
  initials: string;
  /** What the copy block holds. */
  kind: 'json' | 'command' | 'url' | 'link';
  /** Where the snippet goes, when it is a file. */
  file?: string;
  steps: string[];
  snippet: (url: string) => string;
}

const SERVER = 'northfield-ops-ai';

export const CONNECT_CLIENTS: ConnectClient[] = [
  {
    id: 'claude-desktop',
    name: 'Claude Desktop',
    initials: 'C',
    kind: 'url',
    steps: ['Open Settings, then Connectors.', 'Choose Add custom connector and paste the URL.', 'Sign in with your Northfield account when Claude asks.'],
    snippet: (url) => url,
  },
  {
    id: 'claude-code',
    name: 'Claude Code',
    initials: 'CC',
    kind: 'command',
    steps: ['Run the command in a terminal.', 'Run /mcp inside Claude Code and sign in with your Northfield account.'],
    snippet: (url) => `claude mcp add --scope user --transport http ${SERVER} ${url}`,
  },
  {
    id: 'cursor',
    name: 'Cursor',
    initials: 'Cu',
    kind: 'json',
    file: '~/.cursor/mcp.json',
    steps: ['Add this to ~/.cursor/mcp.json, or open Settings, then MCP, then Add server.', 'Cursor opens a browser to sign in the first time a tool is used.'],
    snippet: (url) => JSON.stringify({ mcpServers: { [SERVER]: { url } } }, null, 2),
  },
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    initials: 'G',
    kind: 'url',
    steps: ['Open Settings, then Connectors, then Create.', 'Name it Northfield Ops AI, paste the URL and choose OAuth.', 'Your workspace admin may need to allow custom connectors first.'],
    snippet: (url) => url,
  },
  {
    id: 'copilot-teams',
    name: 'Microsoft Copilot (Teams)',
    initials: 'MC',
    kind: 'link',
    steps: ['In Copilot Studio, open your agent, then Tools, then Add a tool, then Model Context Protocol.', 'Paste the URL and choose OAuth 2.0 with the Northfield tenant.', 'Publish the agent to Teams.'],
    snippet: (url) => url,
  },
  {
    id: 'vscode',
    name: 'VS Code',
    initials: 'VS',
    kind: 'json',
    file: '.vscode/mcp.json',
    steps: ['Add this to .vscode/mcp.json in your project, or run MCP: Add Server from the command palette.', 'Copilot Chat in agent mode lists the workflows as tools.'],
    snippet: (url) => JSON.stringify({ servers: { [SERVER]: { type: 'http', url } } }, null, 2),
  },
];
