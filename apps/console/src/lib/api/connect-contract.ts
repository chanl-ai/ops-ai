import type { ConnectAudience, ConnectOverview, ConnectRange, ConnectSettings, ConnectSettingsInput, ConnectTool } from '@/lib/types/connect';

/**
 * Connect page. One read returns everything the page shows, computed server-side; the only inline write is the
 * Expose switch, which creates, resumes or pauses the workflow's MCP deployment.
 */
export interface ConnectApi {
  get(params: { range: ConnectRange }): Promise<ConnectOverview>;
  /**
   * Exposes or withdraws a workflow for one audience. `assistants` creates, resumes or pauses its MCP deployment;
   * `agents` registers or removes its workflow tool. 422 when the workflow has no published version; 409 when
   * withdrawing from agents while an agent is granted the tool.
   */
  setExposed(workflowId: string, audience: ConnectAudience, exposed: boolean): Promise<ConnectTool>;
  /** Records that someone copied the URL, the journey's first step. */
  recordCopy(): Promise<void>;
  saveSettings(input: ConnectSettingsInput): Promise<ConnectSettings>;
}
