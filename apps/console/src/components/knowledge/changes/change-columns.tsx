'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { PencilLine, XCircle } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { StopRowClick } from '@/components/shared/form-field';
import { selectColumn } from '@/components/shared/select-column';
import { facetFilterFn } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { KnowledgeChange } from '@/lib/types/knowledge-changes';

import { FaqCheck, OriginChip, statusWord, TrustChip } from './change-chips';

export type ChangeRow = KnowledgeChange & { onRowClick: (c: KnowledgeChange) => void; rowTestId: string };

/** An FAQ draft a person may still approve, reject or edit: the only kind of change the service decides. */
export const decidable = (c: KnowledgeChange) => c.origin === 'generated_faq' && c.canDecide && (c.status === 'pending' || c.status === 'source_changed');

/** The Changes queue's columns: the draft pair, its passage, where it came from, its check, status and when. */
export function changeColumns({ onEdit, onReject }: { onEdit: (c: KnowledgeChange) => void; onReject: (c: KnowledgeChange) => void }): ColumnDef<ChangeRow>[] {
  return [
    selectColumn<ChangeRow>((c) => c.summary, decidable),
    {
      id: 'summary',
      accessorFn: (c) => `${c.summary} ${c.documentTitle}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Draft pair" />,
      cell: ({ row }) => {
        const c = row.original;
        return (
          <div className="max-w-xs min-w-56 whitespace-normal">
            <div className="font-medium break-words">{c.faq?.question ?? c.summary}</div>
            <div className="text-sm break-words text-muted-foreground">{c.faq ? c.faq.answer : `${c.documentTitle} · ${c.fromVersion} → ${c.toVersion}`}</div>
          </div>
        );
      },
      enableHiding: false,
    },
    {
      id: 'passage',
      header: 'Source passage',
      cell: ({ row }) => {
        const c = row.original;
        return (
          <div className="max-w-sm min-w-56 whitespace-normal">
            <div className="truncate text-xs text-muted-foreground" title={`${c.documentTitle} › ${c.section}`}>
              {c.documentTitle} › {c.faq?.sectionPath.at(-1) ?? c.section} · {c.toVersion}
            </div>
            {c.before ? <p className="line-clamp-3 text-sm">“{c.before}”</p> : <p className="text-sm text-muted-foreground">{c.sourceName}</p>}
          </div>
        );
      },
    },
    {
      accessorKey: 'origin',
      header: 'From',
      cell: ({ row }) => <OriginChip origin={row.original.origin} />,
      filterFn: facetFilterFn,
      enableSorting: false,
    },
    {
      id: 'check',
      header: 'Check',
      cell: ({ row }) => (row.original.faq ? <FaqCheck change={row.original} /> : <TrustChip state={row.original.trust} />),
    },
    {
      id: 'status',
      header: 'Status',
      cell: ({ row }) => (
        <div className="flex flex-col text-sm whitespace-nowrap">
          <span>{statusWord(row.original.status)}</span>
          {row.original.decidedBy && <span className="text-xs text-muted-foreground">by {row.original.decidedBy}</span>}
        </div>
      ),
    },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Drafted" />,
      cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{relativeTime(row.original.decidedAt ?? row.original.createdAt)}</span>,
    },
    {
      id: 'actions',
      meta: { className: 'w-10' },
      cell: ({ row }) =>
        decidable(row.original) ? (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Edit', icon: PencilLine, onClick: (r) => onEdit(r.original) },
                { label: 'Reject', icon: XCircle, variant: 'destructive', onClick: (r) => onReject(r.original) },
              ]}
            />
          </StopRowClick>
        ) : null,
      enableHiding: false,
    },
  ];
}
