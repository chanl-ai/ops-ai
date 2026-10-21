'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';
import type { ColumnDef, ColumnFiltersState } from '@tanstack/react-table';
import { Activity } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { Note } from '@/components/shared/setting/note';
import { Badge } from '@/components/ui/badge';
import { facetFilterFn } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';

import { TYPE_LABEL } from '../_parts/gallery';
import { ROOT, type ChannelType } from '../_sample/data';

type Kind = 'email' | 'workflow_run' | 'agent_run' | 'chat' | 'tool_call' | 'decision';
type Status = 'running' | 'waiting' | 'done' | 'failed' | 'skipped';

interface ActivityRow {
  id: string;
  kind: Kind;
  title: string;
  status: Status;
  outcome: string;
  source: string;
  channel?: ChannelType;
  agent?: string;
  actor: string;
  at: string;
  rowTestId: string;
}

const KIND: Record<Kind, string> = { email: 'Email received', workflow_run: 'Workflow run', agent_run: 'Agent run', chat: 'Chat', tool_call: 'Tool call', decision: 'Human Task decision' };
const TONE: Record<Status, string> = { running: '', waiting: 'border-warning/40 text-warning-text', done: 'border-success/40 text-success-text', failed: 'border-destructive/40 text-destructive', skipped: 'text-muted-foreground' };
const ago = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

// Sample rows in the shape agents-service's GET /v1/activity is to return (one row per thing that happened).
const ROWS: Omit<ActivityRow, 'rowTestId'>[] = [
  { id: 'email:msg_81c2', kind: 'email', title: 'Notice of garnishment NS-2026-GN-01187', status: 'done', outcome: 'started', source: 'Court levies', channel: 'email', actor: 'registry@courts.example', at: ago(9) },
  { id: 'workflow_run:wfrun_a1d9', kind: 'workflow_run', title: 'Levy intake', status: 'waiting', outcome: 'waiting', source: 'Court levies', channel: 'email', actor: 'Email to levies@harborpine.example', at: ago(9) },
  { id: 'decision:rev_77e1', kind: 'decision', title: 'Hold on CHQ-2219 for 3,250.00 CAD', status: 'done', outcome: 'approved', source: 'Levy intake', channel: 'email', actor: 'Maya Okafor', at: ago(4) },
  { id: 'email:msg_80aa', kind: 'email', title: 'Re: Notice of garnishment', status: 'skipped', outcome: 'duplicate', source: 'Court levies', channel: 'email', actor: 'registry@courts.example', at: ago(7) },
  { id: 'chat:th_f79d', kind: 'chat', title: 'What does Priya Natarajan have with us?', status: 'done', outcome: 'answered', source: 'Advisor intranet', channel: 'chat', agent: 'ag_advisor', actor: 'James Richardson', at: ago(6) },
  { id: 'tool_call:call_qdx', kind: 'tool_call', title: 'list_accounts', status: 'done', outcome: 'ok', source: 'Advisor’s Helper', channel: 'chat', agent: 'ag_advisor', actor: 'James Richardson', at: ago(6) },
  { id: 'chat:th_02bc', kind: 'chat', title: 'Branch hours on Saturday', status: 'done', outcome: 'answered', source: 'Branch site chat', channel: 'chat', actor: 'Visitor', at: ago(3) },
  { id: 'workflow_run:wfrun_7c22', kind: 'workflow_run', title: 'Outbound wire review', status: 'failed', outcome: 'failed', source: 'Core banking runs', channel: 'api', actor: 'Core banking key', at: ago(4) },
  { id: 'agent_run:run_5e10', kind: 'agent_run', title: 'Customer summary for CUS-1002', status: 'done', outcome: 'succeeded', source: 'Advisor’s Helper', agent: 'ag_advisor', actor: 'Customer summary workflow', at: ago(18) },
];

const COLUMNS: ColumnDef<ActivityRow>[] = [
  {
    accessorKey: 'title',
    header: 'What happened',
    cell: ({ row }) => (
      <span className="min-w-0">
        <span className="block truncate font-medium">{row.original.title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {KIND[row.original.kind]} · {row.original.actor}
        </span>
      </span>
    ),
    enableHiding: false,
  },
  { accessorKey: 'kind', header: 'Kind', cell: ({ row }) => KIND[row.original.kind], filterFn: facetFilterFn },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <Badge variant="outline" className={`font-normal capitalize ${TONE[row.original.status]}`}>
        {row.original.outcome.replace(/_/g, ' ')}
      </Badge>
    ),
    filterFn: facetFilterFn,
  },
  { accessorKey: 'channel', header: 'Channel', cell: ({ row }) => (row.original.channel ? TYPE_LABEL[row.original.channel] : '—'), filterFn: facetFilterFn },
  { accessorKey: 'source', header: 'Source', filterFn: facetFilterFn },
  { accessorKey: 'at', header: ({ column }) => <DataTableColumnHeader column={column} title="When" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.at)}</span> },
];

/**
 * The one Activity page: runs, chats, emails received, tool calls and Human Task decisions in one list, filtered by
 * kind, status, channel and source. Channel, agent and workflow pages link here pre-filtered instead of listing their
 * own; the Audit log stays separate.
 */
export default function ActivityMock() {
  const params = useSearchParams();
  const channel = params.get('channel');
  const agent = params.get('agent');
  const rows = React.useMemo(() => ROWS.filter((r) => !agent || r.agent === agent).map((r) => ({ ...r, rowTestId: `activity-${r.id}` })), [agent]);
  const initial: ColumnFiltersState = channel ? [{ id: 'channel', value: [channel] }] : [];
  const options = (key: 'kind' | 'status' | 'channel' | 'source', label: (v: string) => string = (v) => v) =>
    [...new Set(ROWS.map((r) => r[key]).filter(Boolean) as string[])].map((v) => ({ label: label(v), value: v }));
  return (
    <PageLayout icon={Activity} title="Activity" description="Everything that happened in the workspace: runs, chats, emails received, tool calls and decisions" backHref={ROOT}>
      <div className="flex flex-col gap-6 pb-16">
        <Note tone="sample" title="Design mock">
          Sample rows in the shape the activity list will return. Each row opens its run, chat, email or Human Task. It replaces Govern › Activity, whose tool calls become the Tool call kind.
        </Note>
        <DataTableWithViews
          columns={COLUMNS}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="title"
          searchPlaceholder="Search activity…"
          hideViewSwitcher
          initialColumnFilters={initial}
          filters={[
            { column: 'kind', title: 'Kind', options: options('kind', (v) => KIND[v as Kind]) },
            { column: 'status', title: 'Status', options: options('status') },
            { column: 'channel', title: 'Channel', options: options('channel', (v) => TYPE_LABEL[v as ChannelType]) },
            { column: 'source', title: 'Source', options: options('source') },
          ]}
        />
      </div>
    </PageLayout>
  );
}
