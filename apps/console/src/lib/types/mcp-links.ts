/**
 * An MCP link: a named address for a chosen set of one team's tools and published workflows, served by tools-service
 * at `/mcp/<team>/<link>`. People connect their assistant to it with their own sign-in.
 */
export interface McpLinkTool {
  /** The tool's name over MCP: an operation's name, or `workflow__<id>` for a published workflow. */
  name: string;
  title: string;
  kind: 'tool' | 'workflow';
  access: 'read' | 'write' | 'workflow';
}

export interface McpLink {
  id: string;
  name: string;
  slug: string;
  teamId: string;
  /** Always test while outside assistants reach test data only. */
  environment: 'test';
  /** The address an assistant connects to; null while the install names no public address for its MCP service. */
  url: string | null;
  tools: McpLinkTool[];
  toolCount: number;
  paused: boolean;
  createdBy: string;
  createdAt: string;
  lastCall: { at: string; outcome: string; client: string | null } | null;
}

export interface McpLinkInput {
  name: string;
  /** As the tools picker names them: an operation's name or `workflow:<id>`, with the label it showed. */
  tools: { id: string; label: string }[];
}
