import { RiskBadge } from '@/components/status-badges';
import type { Tool, WorkflowToolApproval } from '@/lib/types/domain';

/** How a workflow behaves when called, from its approval rules; shared by the MCP tab and the agent tool pickers. */
export const WORKFLOW_TOOL_APPROVAL: Record<WorkflowToolApproval, string> = {
  pauses_on_writes: 'Pauses for a person before writes',
  pauses_always: 'Pauses for a person at every gate',
  runs_without_pause: 'Runs without pausing',
};

/** The workflow behind a workflow tool: its id, risk tier and whether a call pauses for a person. */
export function WorkflowToolFacts({ workflow }: { workflow: NonNullable<Tool['workflow']> }) {
  return (
    <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid={`workflow-tool-${workflow.workflowId}`}>
      <code className="font-mono">{workflow.workflowId}</code>
      <RiskBadge risk={workflow.tier} />
      <span>{WORKFLOW_TOOL_APPROVAL[workflow.approval]}</span>
    </span>
  );
}
