'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { StopRowClick } from '@/components/shared/form-field';
import { CopyId } from '@/components/shared/setting/copy-field';

/** The record id as a column, whole and copyable. It is a detail a person reads once, so a list leaves it under View
 * until they turn it on (data-table-with-views); the table shows it after the data columns and before the row actions
 * (lib/column-order.ts). */
export function idColumn<T>(get: (row: T) => string): ColumnDef<T> {
  return {
    id: 'recordId',
    accessorFn: get,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Id" />,
    meta: { kind: 'id' },
    cell: ({ row }) => (
      <StopRowClick align="start">
        <CopyId value={get(row.original)} />
      </StopRowClick>
    ),
  };
}
