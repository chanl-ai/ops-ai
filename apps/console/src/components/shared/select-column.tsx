'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { Checkbox } from '@/components/ui/checkbox';

/** Row-selection column for DataTableWithViews; checking a row never opens it. */
export function selectColumn<T>(label: (row: T) => string, canSelect: (row: T) => boolean = () => true): ColumnDef<T> {
  return {
    id: 'select',
    header: ({ table }) => (
      <Checkbox
        aria-label="Select all on this page"
        checked={table.getIsAllPageRowsSelected() || (table.getIsSomePageRowsSelected() && 'indeterminate')}
        onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)}
      />
    ),
    cell: ({ row }) => (
      <Checkbox
        aria-label={`Select ${label(row.original)}`}
        checked={row.getIsSelected()}
        disabled={!canSelect(row.original)}
        onClick={(e) => e.stopPropagation()}
        onCheckedChange={(v) => row.toggleSelected(!!v)}
      />
    ),
    enableSorting: false,
    enableHiding: false,
  };
}
