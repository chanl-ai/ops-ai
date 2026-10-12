'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Route } from 'lucide-react';

import { WORKFLOW_TOOL_APPROVAL } from '@/components/agents/workflow-tool-facts';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ListEmpty } from '@/components/shared/query-states';
import { AccessBadge, RiskBadge } from '@/components/status-badges';
import { plural } from '@/lib/format';
import type { Tool } from '@/lib/types/domain';

const columns: ColumnDef<Tool>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow tool" />,
    cell: ({ row }) => (
      <div>
        <Link href={`/workflows/${row.original.workflow?.workflowId}`} className="font-mono text-sm hover:underline">
          {row.original.name}
        </Link>
        <div className="font-mono text-xs text-muted-foreground">{row.original.workflow?.workflowId}</div>
      </div>
    ),
    enableHiding: false,
  },
  { id: 'tier', header: 'Risk tier', cell: ({ row }) => row.original.workflow && <RiskBadge risk={row.original.workflow.tier} /> },
  { id: 'approval', header: 'When called', cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.workflow && WORKFLOW_TOOL_APPROVAL[row.original.workflow.approval]}</span> },
  {
    id: 'access',
    header: 'Access',
    cell: ({ row }) => (
      <span className="flex gap-1">
        <AccessBadge access={row.original.access} />
        {row.original.workflow?.movesMoney && <AccessBadge access="money_movement" />}
      </span>
    ),
  },
  { id: 'granted', header: 'Granted to', cell: ({ row }) => <span className="text-sm tabular-nums">{row.original.grantedAgentIds.length ? plural(row.original.grantedAgentIds.length, 'agent') : 'No agent yet'}</span> },
];

/**
 * Workflows exposed to agents, as they sit beside app tools: each is a write tool that starts a run. Exposure is
 * switched on the Deployments MCP tab, so the empty state and footer point there.
 */
export function WorkflowToolsTable({ tools, total }: { tools: Tool[]; total: number }) {
  return (
    <div className="flex flex-col gap-2" data-testid="workflow-tools">
      <DataTableWithViews
        columns={columns}
        data={tools}
        getRowId={(t) => t.id}
        searchColumn="name"
        searchPlaceholder="Search workflow tools…"
        emptyState={<ListEmpty icon={Route} noun="workflow tools" filtered={false} description="Expose a published workflow to agents on the Deployments MCP tab; it then appears here and in every agent's Grant tools." />}
      />
      <p className="text-sm text-muted-foreground">
        {plural(total, 'workflow')} exposed to agents.{' '}
        <Link href="/deployments?tab=mcp" className="underline underline-offset-2" data-testid="workflow-tools-manage">
          Manage exposure on the MCP tab →
        </Link>
      </p>
    </div>
  );
}
