'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { actionLabel, areaLabel, byActionOrder } from '@/components/access/access-words';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { Badge } from '@/components/ui/badge';
import type { RoleDetail } from '@/lib/types/settings';

type GridRow = RoleDetail['grid'][number];

/** A role's grid: one row per area, one column per action; a cell says All or Own, or nothing when not granted. */
export function RoleGrid({ grid }: { grid: GridRow[] }) {
  const actions = React.useMemo(() => [...new Set(grid.flatMap((r) => Object.keys(r.actions)))].sort(byActionOrder), [grid]);
  const columns = React.useMemo<ColumnDef<GridRow>[]>(
    () => [
      { accessorKey: 'area', header: 'Area', meta: { kind: 'name' }, cell: ({ row }) => <span className="font-medium">{areaLabel(row.original.area)}</span>, enableHiding: false },
      ...actions.map(
        (action): ColumnDef<GridRow> => ({
          id: action,
          accessorFn: (r) => r.actions[action] ?? '',
          header: actionLabel(action),
          meta: { kind: 'status' },
          // Every action shows: a grid with columns hidden would read as "not allowed".
          enableHiding: false,
          cell: ({ row }) => {
            const scope = row.original.actions[action];
            return scope ? (
              <Badge variant="outline" className={scope === 'all' ? 'border-success/40 bg-success/10 text-success-text' : ''} data-testid={`cell-${row.original.area}-${action}`}>
                {scope === 'all' ? 'All' : 'Own'}
              </Badge>
            ) : null;
          },
        }),
      ),
    ],
    [actions],
  );
  return <DataTableWithViews columns={columns} data={grid} getRowId={(r) => r.area} hideViewSwitcher />;
}
