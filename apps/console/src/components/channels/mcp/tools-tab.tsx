'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { Wrench } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ListEmpty } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import type { McpLink, McpLinkTool } from '@/lib/types/mcp-links';

const ACCESS: Record<McpLinkTool['access'], string> = { read: 'Read', write: 'Write · waits for a person', workflow: 'Starts a workflow' };

const columns: ColumnDef<McpLinkTool>[] = [
  { accessorKey: 'title', header: 'Tool', cell: ({ row }) => <span className="font-medium">{row.original.title}</span> },
  { accessorKey: 'name', header: 'Name in the assistant', cell: ({ row }) => <code className="font-mono text-xs">{row.original.name}</code> },
  { id: 'access', header: 'What it does', cell: ({ row }) => <Badge variant={row.original.access === 'read' ? 'secondary' : 'outline'}>{ACCESS[row.original.access]}</Badge> },
];

/** The tools a link offers, in the order they were picked, by the name an assistant calls each one. */
export function ToolsTab({ link }: { link: McpLink }) {
  return (
    <DataTableWithViews
      columns={columns}
      data={link.tools}
      getRowId={(t) => t.name}
      searchColumn="title"
      searchPlaceholder="Search this link’s tools…"
      hideViewSwitcher
      hidePaginationOnOnePage
      emptyState={<ListEmpty icon={Wrench} noun="tools" filtered={false} description="This link offers no tools." />}
    />
  );
}
