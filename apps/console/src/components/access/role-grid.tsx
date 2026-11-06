'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { actionLabel, areaLabel, byActionOrder } from '@/components/access/access-words';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import type { RoleDetail } from '@/lib/types/settings';

type GridRow = RoleDetail['grid'][number];

/**
 * A role's grid: one row per area, one column per action; a cell says All or Own, or nothing when not granted. With
 * `onToggle` each cell is a checkbox: ticking grants it on every record, unticking takes it away, and a cell held on
 * one's own records keeps that scope while ticked.
 */
export function RoleGrid({
  grid,
  onToggle,
  notHeld = [],
}: {
  grid: GridRow[];
  onToggle?: (area: string, action: string, on: boolean) => void;
  /** Cells the role may never hold (area.action), shown unticked and locked. */
  notHeld?: string[];
}) {
  const never = React.useMemo(() => new Set(notHeld), [notHeld]);
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
            if (onToggle)
              return (
                <label className="flex items-center gap-1.5">
                  <Checkbox
                    checked={!!scope}
                    disabled={never.has(`${row.original.area}.${action}`)}
                    title={never.has(`${row.original.area}.${action}`) ? 'Only a built-in role holds secrets, egress and Security-team permissions' : undefined}
                    onCheckedChange={(on) => onToggle(row.original.area, action, on === true)}
                    aria-label={`${areaLabel(row.original.area)}: ${actionLabel(action)}`}
                    data-testid={`cell-${row.original.area}-${action}`}
                  />
                  {scope === 'own' && <span className="text-xs text-muted-foreground">Own</span>}
                </label>
              );
            return scope ? (
              <Badge variant="outline" className={scope === 'all' ? 'border-success/40 bg-success/10 text-success-text' : ''} data-testid={`cell-${row.original.area}-${action}`}>
                {scope === 'all' ? 'All' : 'Own'}
              </Badge>
            ) : null;
          },
        }),
      ),
    ],
    [actions, onToggle, never],
  );
  // Every area on one page: a matrix with areas paged away reads as "not allowed" and hides cells from an edit.
  const onePage = { enabled: true, total: grid.length, page: 1, pageSize: Math.max(grid.length, 1), onPaginationChange: () => undefined };
  return <DataTableWithViews columns={columns} data={grid} getRowId={(r) => r.area} hideViewSwitcher serverPagination={onePage} />;
}
