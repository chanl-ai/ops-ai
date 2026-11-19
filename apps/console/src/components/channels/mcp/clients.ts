/**
 * How each assistant takes an MCP link's address. Every one signs the person in with their own work account (OAuth
 * through platform-service), so no step carries a key. Claude reaches remote servers through Settings › Connectors;
 * its config file only starts local servers, so it gets steps and the address.
 */
export interface ConnectClient {
  id: string;
  name: string;
  initials: string;
  /** What the copy block holds. */
  kind: 'json' | 'command' | 'url';
  /** Where the snippet goes, when it is a file. */
  file?: string;
  steps: string[];
  snippet: (url: string, server: string) => string;
}

export const CONNECT_CLIENTS: ConnectClient[] = [
  {
    id: 'claude',
    name: 'Claude',
    initials: 'CL',
    kind: 'url',
    steps: ['In Claude, open Settings, then Connectors, then Add custom connector.', 'Paste the address above.', 'Sign in with your work account once. Claude can then run only what you may run.'],
    snippet: (url) => url,
  },
  {
    id: 'claude-code',
    name: 'Claude Code',
    initials: 'CC',
    kind: 'command',
    steps: ['Run the command in a terminal.', 'Run /mcp inside Claude Code and sign in with your work account.'],
    snippet: (url, server) => `claude mcp add --scope user --transport http ${server} ${url}`,
  },
  {
    id: 'cursor',
    name: 'Cursor',
    initials: 'CU',
    kind: 'json',
    file: '~/.cursor/mcp.json',
    steps: ['Add this to ~/.cursor/mcp.json, or open Settings, then MCP, then Add server.', 'Cursor opens a browser to sign in the first time a tool is used.'],
    snippet: (url, server) => JSON.stringify({ mcpServers: { [server]: { url } } }, null, 2),
  },
  {
    id: 'vscode',
    name: 'VS Code',
    initials: 'VS',
    kind: 'json',
    file: '.vscode/mcp.json',
    steps: ['Add this to .vscode/mcp.json in your project, or run MCP: Add Server from the command palette.', 'VS Code asks you to sign in with your work account the first time.'],
    snippet: (url, server) => JSON.stringify({ servers: { [server]: { type: 'http', url } } }, null, 2),
  },
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    initials: 'GP',
    kind: 'url',
    steps: ['Open Settings, then Connectors, then Create.', 'Paste the address above and choose OAuth.', 'Sign in with your work account. Your ChatGPT admin may need to allow custom connectors first.'],
    snippet: (url) => url,
  },
];
