import type { OpsAI } from '@chanl-ai/ops-ai';

type Agents = OpsAI['raw']['agents'];

/** One page of the apps an agent's tools picker lists (GET /v1/agents/{id}/tool-apps), searched and counted by the server. */
export type AgentToolAppsPage = Awaited<ReturnType<Agents['agents_tool_apps']>>;
export type AgentToolApp = AgentToolAppsPage['data'][number];
export type AgentToolAppMatch = AgentToolApp['matches'][number];
/** One page of one app's tools for the agent, each saying whether the agent holds it. */
export type AppToolsPage = Awaited<ReturnType<Agents['agents_app_tools']>>;
export type AppTool = AppToolsPage['data'][number];

/** The query both routes take: a search, whether the agent holds the tool (apps: holds any), and a cursor. */
export interface ToolAppsParams {
  search?: string;
  granted?: boolean;
  cursor?: string | null;
  limit?: number;
}
