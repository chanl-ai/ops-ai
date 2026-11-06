'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { Checkbox } from '@/components/ui/checkbox';

/** Row-selection column for DataTableWithViews; checking a row never opens it. */
export function selectColumn<T>(label: (row: T) => string, canSelect: (row: T) => boolean = () => true): ColumnDef<T> {
  return {
    id: 'select',
    // Select all takes only the rows that can be picked; the table's own toggle would take every row on the page.
    header: ({ table }) => {
      const rows = table.getPaginationRowModel().rows.filter((r) => canSelect(r.original));
      const all = rows.length > 0 && rows.every((r) => r.getIsSelected());
      return (
        <Checkbox
          aria-label="Select all on this page"
          checked={all || (rows.some((r) => r.getIsSelected()) && 'indeterminate')}
          disabled={!rows.length}
          onCheckedChange={(v) =>
            table.setRowSelection((prev) => {
              const next = { ...prev };
              for (const r of rows) {
                if (v) next[r.id] = true;
                else delete next[r.id];
              }
              return next;
            })
          }
        />
      );
    },
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
    // A fixed width, so the name column pinned beside it on a phone starts where it ends.
    meta: { className: 'w-10' },
  };
}
