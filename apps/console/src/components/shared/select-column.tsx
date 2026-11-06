'use client';

import type { ColumnDef } from '@tanstack/react-table';

import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';

/**
 * The primitive's 16px box is under WCAG 2.2's 24px target minimum, so the select boxes are 24×24 buttons that draw the
 * same 16px box inside (`before:`), with a negative margin so the column keeps its width.
 */
const TARGET =
  'relative -m-1 size-6 rounded-md border-0 bg-transparent shadow-none dark:bg-transparent data-[state=checked]:bg-transparent dark:data-[state=checked]:bg-transparent ' +
  'before:absolute before:inset-1 before:rounded-[4px] before:border before:border-muted-foreground/60 before:shadow-xs dark:before:bg-input/30 ' +
  'data-[state=checked]:before:border-primary data-[state=checked]:before:bg-primary dark:data-[state=checked]:before:bg-primary [&>span]:relative';

function SelectBox({ className, ...props }: React.ComponentProps<typeof Checkbox>) {
  return <Checkbox className={cn(TARGET, className)} {...props} />;
}

/** Row-selection column for DataTableWithViews; checking a row never opens it. */
export function selectColumn<T>(label: (row: T) => string, canSelect: (row: T) => boolean = () => true): ColumnDef<T> {
  return {
    id: 'select',
    // Select all takes only the rows that can be picked; the table's own toggle would take every row on the page.
    header: ({ table }) => {
      const rows = table.getPaginationRowModel().rows.filter((r) => canSelect(r.original));
      const all = rows.length > 0 && rows.every((r) => r.getIsSelected());
      return (
        <SelectBox
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
      <SelectBox
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
