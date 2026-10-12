'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeySquare, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCreateSecret, useDeleteSecret, useRotateSecret, useSecrets } from '@/hooks/secrets-queries';
import { relativeTime, shortDate } from '@/lib/format';
import type { SecretMeta } from '@/lib/types/secrets';

function columns(onRotate: (s: SecretMeta) => void, onDelete: (s: SecretMeta) => void): ColumnDef<SecretMeta>[] {
  return [
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => (
        <div className="min-w-48">
          <code className="font-mono text-sm">{row.original.name}</code>
          <div className="font-mono text-[11px] text-muted-foreground">{`{{${row.original.name}}}`} in a header</div>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'version', header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, cell: ({ row }) => <span className="text-sm tabular-nums">v{row.original.version}</span> },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />,
      cell: ({ row }) => (
        <div className="min-w-32">
          <div className="text-sm">{row.original.createdBy}</div>
          <div className="text-xs text-muted-foreground">{shortDate(row.original.createdAt)}</div>
        </div>
      ),
    },
    { accessorKey: 'rotatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Rotated" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.rotatedAt ? relativeTime(row.original.rotatedAt) : 'Never'}</span> },
    { accessorKey: 'lastUsedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last used" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Never'}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Rotate', icon: RefreshCw, onClick: (r) => onRotate(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

/** Create (no `rotating`) or rotate one secret. The value field is write-only and cleared on every open. */
function SecretDialog({ open, rotating, onOpenChange }: { open: boolean; rotating: SecretMeta | null; onOpenChange: (open: boolean) => void }) {
  const create = useCreateSecret();
  const rotate = useRotateSecret();
  const [name, setName] = React.useState('');
  const [value, setValue] = React.useState('');
  const [errors, setErrors] = React.useState<{ name?: string; value?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) (setName(''), setValue(''), setErrors({}));
  }, [open]);
  const pending = create.isPending || rotate.isPending;
  const submit = async () => {
    const e = { name: rotating || /^[A-Z][A-Z0-9_]*$/.test(name) ? undefined : 'Upper case letters, digits and underscores, starting with a letter.', value: value ? undefined : 'Enter the value.' };
    setErrors(e);
    if (e.name || e.value) return;
    try {
      const saved = rotating ? await rotate.mutateAsync({ name: rotating.name, value }) : await create.mutateAsync({ name, value });
      setValue('');
      toast.success(rotating ? `Rotated ${rotating.name}` : `Saved ${(saved as SecretMeta).name}`, { description: rotating ? 'The next call sends the new value.' : `Reference it in a header as {{${(saved as SecretMeta).name}}}.` });
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={rotating ? `Rotate ${rotating.name}` : 'Add a secret'}
      description="The value is encrypted when saved and never shown again, here or anywhere else."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton isLoading={pending} loadingText="Saving…" onClick={submit} data-testid="secret-submit">
            {rotating ? 'Rotate' : 'Save secret'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!rotating && (
          <FormField id="secret-name" label="Name" error={errors.name} hint="Headers reference it as {{NAME}}.">
            <Input id="secret-name" value={name} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value.toUpperCase()), setErrors({}))} placeholder="e.g. STATEMENTS_KEY" className="font-mono text-sm" autoComplete="off" />
          </FormField>
        )}
        <FormField id="secret-value" label={rotating ? 'New value' : 'Value'} error={errors.value ?? errors.submit}>
          <Input id="secret-value" type="password" value={value} aria-invalid={!!(errors.value ?? errors.submit)} onChange={(e) => (setValue(e.target.value), setErrors({}))} autoComplete="new-password" />
        </FormField>
      </div>
    </DialogShell>
  );
}

export default function SecretsPage() {
  const query = useSecrets();
  const remove = useDeleteSecret();
  const [dialog, setDialog] = React.useState<{ rotating: SecretMeta | null } | null>(null);
  const [deleting, setDeleting] = React.useState<SecretMeta | null>(null);
  const cols = React.useMemo(() => columns((s) => setDialog({ rotating: s }), setDeleting), []);

  return (
    <SettingsPageLayout
      section="Secrets"
      description="Credentials tool calls send, such as API keys. A value is encrypted, never shown again, and scrubbed from whatever a system answers."
      actions={
        <Button onClick={() => setDialog({ rotating: null })}>
          <Plus className="size-4" /> Add secret
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="secrets" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={query.data ?? []}
          getRowId={(s) => s.name}
          searchColumn="name"
          searchPlaceholder="Search secrets…"
          hideViewSwitcher
          emptyState={<EmptyState icon={KeySquare} title="No secrets yet" description="Add the credential a tool module's header names, such as {{STATEMENTS_KEY}}." />}
        />
      )}

      <SecretDialog open={!!dialog} rotating={dialog?.rotating ?? null} onOpenChange={(o) => !o && setDialog(null)} />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="secret"
        entityName={deleting?.name}
        description="Calls whose headers name it are refused with SECRET_MISSING from now on, and nothing is sent."
        confirmText="Delete secret"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(deleting!.name);
            toast.success(`Deleted ${deleting!.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${deleting!.name}`, { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
