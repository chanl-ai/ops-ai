'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, LogOut, MonitorSmartphone, Smartphone, Trash2 } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ListEmpty } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import type { AccountSession, MfaDevice } from '@/lib/types/account';

/** Authenticators and recovery codes on the account. Removing the last authenticator is refused while MFA is required. */
export function MfaDevicesTable({ devices, onRegenerate, onRemove, busy }: { devices: MfaDevice[]; onRegenerate: () => void; onRemove: (d: MfaDevice) => void; busy: boolean }) {
  const columns: ColumnDef<MfaDevice>[] = [
    {
      accessorKey: 'label',
      header: 'Method',
      cell: ({ row }) => (
        <span className="flex items-center gap-2 font-medium">
          {row.original.kind === 'totp' ? <Smartphone className="size-4 text-muted-foreground" /> : <KeyRound className="size-4 text-muted-foreground" />}
          {row.original.label}
        </span>
      ),
      enableHiding: false,
    },
    { id: 'detail', header: 'Status', cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.kind === 'recovery_codes' ? `${row.original.remaining ?? 0} of 10 unused` : row.original.lastUsedAt ? `Last used ${relativeTime(row.original.lastUsedAt)}` : 'Not used yet'}</span> },
    { accessorKey: 'addedAt', header: 'Added', cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{relativeTime(row.original.addedAt)}</span> },
    {
      id: 'actions',
      cell: ({ row }) =>
        row.original.kind === 'recovery_codes' ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={onRegenerate} data-testid="regenerate-codes">
            Regenerate
          </Button>
        ) : (
          <Button size="icon" variant="ghost" aria-label={`Remove ${row.original.label}`} disabled={busy} onClick={() => onRemove(row.original)}>
            <Trash2 className="size-4" />
          </Button>
        ),
      enableHiding: false,
    },
  ];
  return (
    <DataTableWithViews
      columns={columns}
      data={devices}
      getRowId={(d) => d.id}
      searchColumn="label"
      searchPlaceholder="Search methods…"
      hideViewSwitcher
      emptyState={<ListEmpty icon={Smartphone} noun="two-step methods" filtered={false} description="Set up an authenticator app from the sign-in prompt; your workspace may require it." />}
    />
  );
}

/** Where the account is signed in. The current session is marked and cannot be revoked here; Sign out ends it. */
export function SessionsTable({ sessions, onRevoke, busyId }: { sessions: AccountSession[]; onRevoke: (s: AccountSession) => void; busyId: string | null }) {
  const columns: ColumnDef<AccountSession>[] = [
    {
      accessorKey: 'device',
      header: 'Device',
      cell: ({ row }) => (
        <div>
          <span className="flex items-center gap-2 font-medium">
            {row.original.device}
            {row.original.current && <Badge variant="secondary">This device</Badge>}
          </span>
          <span className="text-xs text-muted-foreground">{row.original.browser}</span>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'location', header: 'Location', cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.location} · <span className="font-mono text-xs text-muted-foreground">{row.original.ip}</span></span> },
    { accessorKey: 'lastSeenAt', header: 'Last seen', cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.current ? 'Now' : relativeTime(row.original.lastSeenAt)}</span> },
    { accessorKey: 'createdAt', header: 'Signed in', cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{relativeTime(row.original.createdAt)}</span> },
    {
      id: 'actions',
      cell: ({ row }) =>
        row.original.current ? null : (
          <Button size="sm" variant="outline" disabled={busyId === row.original.id} onClick={() => onRevoke(row.original)} data-testid={`revoke-${row.original.id}`}>
            <LogOut className="size-4" /> Sign out
          </Button>
        ),
      enableHiding: false,
    },
  ];
  return (
    <DataTableWithViews
      columns={columns}
      data={sessions}
      getRowId={(s) => s.id}
      searchColumn="device"
      searchPlaceholder="Search devices or places…"
      hideViewSwitcher
      emptyState={<ListEmpty icon={MonitorSmartphone} noun="sessions" filtered={false} description="Sessions appear here when you sign in." />}
    />
  );
}
