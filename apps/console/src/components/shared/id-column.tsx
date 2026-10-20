'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { StopRowClick } from '@/components/shared/form-field';
import { CopyId } from '@/components/shared/setting/copy-field';

/** The record id as a column: middle-truncated, whole value in the title, copyable. Follows the select-all column in every table of records. */
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
