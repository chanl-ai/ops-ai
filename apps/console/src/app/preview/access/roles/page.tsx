'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { ShieldCheck } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { Badge } from '@/components/ui/badge';

import { ROLES, type SampleRole } from '../_sample/access';

type Row = SampleRole & { onRowClick: (r: SampleRole) => void; rowTestId: string };

/** Mock (c-150): Access › Roles, every role of the team with what it is for and how many hold it. */
export default function RolesMock() {
  const router = useRouter();
  const columns = React.useMemo<ColumnDef<Row>[]>(
    () => [
      {
        accessorKey: 'name',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Role" />,
        meta: { kind: 'name' },
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.name}</div>
            <div className="text-xs text-muted-foreground">{row.original.description}</div>
          </div>
        ),
      },
      { id: 'kind', accessorFn: (r) => (r.builtin ? 'Built in' : 'Custom'), header: 'Kind', meta: { kind: 'status' }, cell: ({ row }) => <Badge variant="outline">{row.original.builtin ? 'Built in' : 'Custom'}</Badge> },
      { accessorKey: 'permissionCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Permissions" />, meta: { kind: 'number' } },
      { accessorKey: 'assignmentCount', header: ({ column }) => <DataTableColumnHeader column={column} title="People" />, meta: { kind: 'number' } },
    ],
    [],
  );
  const rows = ROLES.map((r) => ({ ...r, onRowClick: (x: SampleRole) => router.push(`/preview/access/roles/${x.id}`), rowTestId: `role-row-${r.id}` }));
  return (
    <PageLayout icon={ShieldCheck} title="Roles" description="What each role allows in the team; built-in roles are read-only">
      <DataTableWithViews columns={columns} data={rows} getRowId={(r) => r.id} searchColumn="name" searchPlaceholder="Search roles…" />
    </PageLayout>
  );
}
