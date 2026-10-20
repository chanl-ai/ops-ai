'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { ShieldCheck } from 'lucide-react';
import { useParams } from 'next/navigation';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { Badge } from '@/components/ui/badge';

import { ACTIONS, AREAS, label, roleOf, type Scope } from '../../_sample/access';

type GridRow = { area: string; cells: Record<string, Scope | undefined> };

/** Mock (c-150): a role's grid, one row per area and one column per action; a cell says own or all, or nothing. */
export default function RoleMock() {
  const { id } = useParams<{ id: string }>();
  const role = roleOf(id) ?? roleOf('viewer')!;
  const rows: GridRow[] = AREAS.map((area) => ({ area, cells: Object.fromEntries(role.permissions.filter((p) => p.area === area).map((p) => [p.action, p.scope])) }));
  const columns: ColumnDef<GridRow>[] = [
    { accessorKey: 'area', header: 'Area', meta: { kind: 'name' }, cell: ({ row }) => <span className="font-medium">{label(row.original.area)}</span> },
    ...ACTIONS.map(
      (action): ColumnDef<GridRow> => ({
        id: action,
        accessorFn: (r) => r.cells[action] ?? '',
        header: label(action),
        meta: { kind: 'status' },
        cell: ({ row }) => {
          const scope = row.original.cells[action];
          return scope ? (
            <Badge variant="outline" className={scope === 'all' ? 'border-success/40 bg-success/10 text-success-text' : ''} data-testid={`cell-${row.original.area}-${action}`}>
              {scope === 'all' ? 'All' : 'Own'}
            </Badge>
          ) : null;
        },
      }),
    ),
  ];
  return (
    <PageLayout
      icon={ShieldCheck}
      title={role.name}
      description={role.description}
      backHref="/preview/access/roles"
      badge={
        <>
          <Badge variant="outline">{role.builtin ? 'Built in · read-only' : 'Custom'}</Badge>
          <span className="text-xs text-muted-foreground">
            {role.permissionCount} permissions · {role.assignmentCount} people
          </span>
        </>
      }
    >
      <p className="pb-2 text-sm text-muted-foreground">All: every record in the team. Own: only records the person created or was assigned. Empty: not allowed.</p>
      <DataTableWithViews columns={columns} data={rows} getRowId={(r) => r.area} />
    </PageLayout>
  );
}
