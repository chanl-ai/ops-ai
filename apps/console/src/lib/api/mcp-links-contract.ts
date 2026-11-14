import type { McpLink, McpLinkInput } from '@/lib/types/mcp-links';

/** The team's MCP links (tools-service `/v1/mcp-links`); a link's calls are the call log's (`governance.toolCalls`). */
export interface McpLinksApi {
  list(): Promise<McpLink[]>;
  get(id: string): Promise<McpLink>;
  /** 422 when a picked tool is not one the team can run, or the name's address is taken in the team. */
  create(input: McpLinkInput): Promise<McpLink>;
  setPaused(id: string, paused: boolean): Promise<McpLink>;
  /** Its address answers 404 from then on; its calls stay in Activity. */
  remove(id: string): Promise<void>;
}
