'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, KeyRound, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCan } from '@/hooks/me-queries';
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from '@/hooks/settings-queries';
import { relativeTime } from '@/lib/format';
import type { ApiKey } from '@/lib/types/settings';

const EXPIRY = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
];
const day = (iso: string) => new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short' });

/**
 * The team's API keys, the list Settings › Team › API keys owns (platform-service issues every key). A key runs read
 * tools only over MCP; a key made here can read and nothing else, always expires, and shows its secret once.
 */
export function KeysTab({ linkId }: { linkId: string }) {
  const q = useApiKeys({ page: 1, pageSize: 100, filters: { mcpLink: [linkId] } });
  const canCreate = useCan('access', 'create') === true;
  const canRevoke = useCan('access', 'delete') === true;
  const revoke = useRevokeApiKey();
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const [making, setMaking] = React.useState(false);
  if (q.isPending) return <PageSkeleton statCards={0} tableRows={3} />;
  if (q.isError && !q.data) return <QueryError what="the team’s keys" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />;
  const rows = (q.data?.data ?? []).filter((k) => (k as ApiKey & { status?: string }).status !== 'revoked');
  const columns: ColumnDef<ApiKey>[] = [
    {
      accessorKey: 'name',
      header: 'Key',
      cell: ({ row }) => (
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{row.original.name}</span>
          <code className="font-mono text-xs text-muted-foreground">{row.original.prefix}…</code>
        </span>
      ),
    },
    { accessorKey: 'createdBy', header: 'Belongs to' },
    { id: 'created', header: 'Created', cell: ({ row }) => <span className="tabular-nums">{day(row.original.createdAt)}</span> },
    {
      id: 'used',
      header: 'Last used',
      cell: ({ row }) =>
        row.original.lastUsedAt ? (
          <span className="flex items-center gap-1.5">
            <CheckCircle2 className="size-3.5 text-success" aria-hidden /> {relativeTime(row.original.lastUsedAt)}
          </span>
        ) : (
          <span className="text-muted-foreground">Never</span>
        ),
    },
    { id: 'runs', header: 'Can run', cell: () => <Badge variant="secondary">Reads only</Badge> },
    ...(canRevoke
      ? [
          {
            id: 'revoke',
            header: '',
            cell: ({ row }: { row: { original: ApiKey } }) => (
              <Button variant="ghost" size="sm" onClick={() => setRevoking(row.original)} data-testid={`mcp-key-revoke-${row.original.id}`}>
                Revoke
              </Button>
            ),
          } satisfies ColumnDef<ApiKey>,
        ]
      : []),
  ];
  return (
    <div className="flex flex-col gap-3" data-testid="mcp-link-keys">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">Keys run read tools only. A write asks the person to sign in instead. Each key opens this link and nothing else.</p>
        {canCreate && (
          <Button onClick={() => setMaking(true)} data-testid="mcp-key-new">
            <Plus className="size-4" /> New key
          </Button>
        )}
      </div>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(k) => k.id}
        searchColumn="name"
        searchPlaceholder="Search keys…"
        hideViewSwitcher
        hidePaginationOnOnePage
        emptyState={<ListEmpty icon={KeyRound} noun="keys" filtered={false} description="A key lets a script or another system read through this link without a person signing in." />}
      />
      <NewKeyDialog open={making} onOpenChange={setMaking} linkId={linkId} />
      {revoking && (
        <ConfirmActionDialog
          open
          onOpenChange={(o) => !o && setRevoking(null)}
          title={`Revoke ${revoking.name}?`}
          consequence="Every system using this key stops at once. Nothing else changes."
          runsNow
          confirmLabel="Revoke key"
          destructive
          isPending={revoke.isPending}
          onConfirm={() =>
            revoke
              .mutateAsync(revoking.id)
              .then(() => {
                toast.success(`Revoked ${revoking.name}`);
                setRevoking(null);
              })
              .catch((e: Error) => toast.error('Couldn’t revoke the key', { description: e.message }))
          }
        />
      )}
    </div>
  );
}

function NewKeyDialog({ open, onOpenChange, linkId }: { open: boolean; onOpenChange: (open: boolean) => void; linkId: string }) {
  const create = useCreateApiKey();
  const [name, setName] = React.useState('');
  const [expiry, setExpiry] = React.useState('90');
  const [secret, setSecret] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setName('');
    setExpiry('90');
    setSecret(null);
    setError(null);
  }, [open]);
  const submit = () => {
    if (!name.trim()) return setError('Name the key after the system that will use it.');
    create.mutate(
      { name: name.trim(), scopes: ['read'], expiresInDays: Number(expiry), target: { kind: 'mcp_link', id: linkId } },
      { onSuccess: (r) => setSecret(r.key), onError: (e) => setError(e.message) },
    );
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={secret ? 'Key made' : 'New key'}
      description={secret ? 'Copy it now. It is not shown again.' : 'A key for one system. It reads through this link only and always expires.'}
      onSubmit={secret ? undefined : submit}
      footer={
        secret ? (
          <Button type="button" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        ) : (
          <>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={create.isPending} loadingText="Making…" data-testid="mcp-key-create">
              Make key
            </LoadingButton>
          </>
        )
      }
    >
      {secret ? (
        <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/30 p-2 pl-3" data-testid="mcp-key-secret">
          <code className="min-w-0 flex-1 break-all font-mono text-sm">{secret}</code>
          <CopyButton text={secret} variant="outline" size="sm" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <FormField id="mcp-key-name" label="Name" hint="Name the system that uses it, e.g. Claims triage script." error={error ?? undefined}>
            <Input id="mcp-key-name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={!!error} data-testid="mcp-key-name" />
          </FormField>
          <FormField id="mcp-key-expiry" label="Expires after">
            <Select value={expiry} onValueChange={setExpiry}>
              <SelectTrigger id="mcp-key-expiry">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPIRY.map((e) => (
                  <SelectItem key={e.value} value={e.value}>
                    {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
      )}
    </DialogShell>
  );
}
