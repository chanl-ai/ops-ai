'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Lock, UserPlus } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { RecordTable } from '@/components/shared/setting/record-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import { useViewerRole } from '@/lib/settings-preview-store';

import { MEMBERS, type SampleMember } from '../../_sample/data';
import { mockSave } from '../../_sample/save';

const nameOf = (m: SampleMember) => m.name;

/** Govern › Access (S06): who is in the team and what each may do; only an Admin changes a role. */
export default function AccessPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const columns = React.useMemo<ColumnDef<SampleMember>[]>(
    () => [
      { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Member" />, cell: ({ row }) => <div><div className="font-medium">{row.original.name}</div><div className="text-xs text-muted-foreground">{row.original.email}</div></div>, enableHiding: false },
      { accessorKey: 'role', header: 'Role', cell: ({ row }) => <Badge variant={admin ? 'secondary' : 'outline'} className="gap-1 font-normal">{!admin && <Lock className="size-3" />}{row.original.role}</Badge> },
      { accessorKey: 'team', header: 'Team' },
      { accessorKey: 'lastActiveAt', header: 'Last active', cell: ({ row }) => <span className="text-sm text-muted-foreground">{relativeTime(row.original.lastActiveAt)}</span> },
    ],
    [admin],
  );
  return (
    <PreviewPageLayout
      title="Access"
      description="Who is in the team and what each person may do"
      actions={
        <Button onClick={() => mockSave('Invitation')} disabled={!admin}>
          <UserPlus className="size-4" /> Invite
        </Button>
      }
    >
      {!admin && <p className="text-sm text-muted-foreground" data-testid="access-lock">You can read this list. Only an Admin can change a role or invite someone.</p>}
      <RecordTable columns={columns} data={MEMBERS} nameOf={nameOf} searchPlaceholder="Search members…" />
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Pending invitations</h2>
        <EntityRow name="Tomas Reyes" avatar meta="Invited by Priya Shah · expires in 6 days · Builder" actions={admin ? [{ label: 'Resend', onClick: () => mockSave('Resend') }, { label: 'Revoke', onClick: () => mockSave('Revoke'), destructive: true }] : undefined} />
      </div>
    </PreviewPageLayout>
  );
}
