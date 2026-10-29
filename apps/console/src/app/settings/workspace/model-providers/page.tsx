'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Info, KeyRound, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCan } from '@/hooks/me-queries';
import { useProviderKeys, useRemoveProviderKey, useSaveProviderKey } from '@/hooks/provider-key-queries';
import { relativeTime } from '@/lib/format';
import type { ProviderKey } from '@/lib/types/provider-keys';

// The rule models-service holds a key name to: what a provider connection's key reference gives (OPENAI, openai).
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$/;

/** Adds a key, or replaces the value of `replacing`. The value goes to models-service once and is never shown again. */
function KeyDialog({ open, onOpenChange, replacing }: { open: boolean; onOpenChange: (o: boolean) => void; replacing: string | null }) {
  const save = useSaveProviderKey();
  const [name, setName] = React.useState('');
  const [value, setValue] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) (setName(replacing ?? ''), setValue(''), setError(undefined));
  }, [open, replacing]);
  const submit = async () => {
    if (!NAME.test(name)) return setError('Use letters, digits, _, . and -, starting with a letter or digit, up to 120.');
    if (!value.trim()) return setError('Paste the provider’s key.');
    try {
      await save.mutateAsync({ name, value: value.trim() });
      // Cleared at once, so the key leaves the page with the dialog.
      setValue('');
      toast.success(replacing ? `Replaced ${name}` : `Saved ${name}`, { description: 'The next model call that signs in with it uses this value.' });
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={replacing ? `Replace ${replacing}` : 'Add a model provider key'}
      description="Kept encrypted by the models service and read by it alone. After saving, only its name and when it changed are shown."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={save.isPending} loadingText="Saving…" data-testid="provider-key-save">
            {replacing ? 'Replace key' : 'Save key'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="pk-name" label="Name" error={error} hint="The name the provider connection signs in with, such as OPENAI. Saving the same name again replaces its value.">
          <Input id="pk-name" value={name} readOnly={!!replacing} onChange={(e) => (setName(e.target.value), setError(undefined))} placeholder="e.g. OPENAI" className="font-mono text-sm" />
        </FormField>
        <FormField id="pk-value" label="Key">
          <Input id="pk-value" type="password" autoComplete="off" value={value} onChange={(e) => (setValue(e.target.value), setError(undefined))} className="font-mono text-sm" />
        </FormField>
      </div>
    </DialogShell>
  );
}

function columns(onReplace: (k: ProviderKey) => void, onRemove: (k: ProviderKey) => void): ColumnDef<ProviderKey>[] {
  return [
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => <code className="font-mono text-sm">{row.original.name}</code>,
      enableHiding: false,
    },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Saved" />,
      cell: ({ row }) => (
        <span className="text-sm whitespace-nowrap text-muted-foreground">
          {relativeTime(row.original.createdAt)} by {row.original.createdBy}
        </span>
      ),
    },
    {
      accessorKey: 'rotatedAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Last replaced" />,
      cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.rotatedAt ? `${relativeTime(row.original.rotatedAt)} (version ${row.original.version})` : 'Never'}</span>,
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Replace key', icon: RotateCcw, onClick: (r) => onReplace(r.original) },
              { label: 'Remove', icon: Trash2, variant: 'destructive', onClick: (r) => onRemove(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

/**
 * The account's model provider keys (models-service `/v1/provider-keys`, owner 2026-10-27): account admins add, replace
 * and remove them; only the models service reads a value, and no team sees one, so a new team needs no setup.
 */
export default function ModelProvidersPage() {
  const admin = useCan('settings', 'manage') === true;
  const keys = useProviderKeys(admin);
  const remove = useRemoveProviderKey();
  const [editing, setEditing] = React.useState<{ replacing: string | null } | null>(null);
  const [removing, setRemoving] = React.useState<string | null>(null);
  const cols = React.useMemo(() => columns((k) => setEditing({ replacing: k.name }), (k) => setRemoving(k.name)), []);

  return (
    <SettingsPageLayout
      section="Model providers"
      description="The keys the account’s AI models sign in to their providers with. No team sees a key, and a value is never shown after saving."
      actions={
        admin && (
          <Button onClick={() => setEditing({ replacing: null })} data-testid="provider-key-add">
            <Plus className="size-4" /> Add key
          </Button>
        )
      }
    >
      {!admin ? (
        <Alert>
          <Info />
          <AlertDescription>Only an account admin (an admin on the Security team) sees and changes model provider keys.</AlertDescription>
        </Alert>
      ) : keys.isPending ? (
        <PageSkeleton statCards={0} tableRows={2} />
      ) : keys.isError && !keys.data ? (
        <QueryError what="model provider keys" onRetry={() => keys.refetch()} retrying={keys.isFetching} error={keys.error} testId="provider-keys-error" />
      ) : (
        <div data-testid="provider-keys">
          <DataTableWithViews
            columns={cols}
            data={keys.data ?? []}
            getRowId={(k) => k.name}
            searchColumn="name"
            searchPlaceholder="Search key names…"
            hideViewSwitcher
            emptyState={<ListEmpty icon={KeyRound} noun="model provider keys" filtered={false} createLabel="Add key" onCreate={() => setEditing({ replacing: null })} description="Add the key your model provider gave you, named the way its connection refers to it." />}
          />
        </div>
      )}
      <KeyDialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)} replacing={editing?.replacing ?? null} />
      <DeleteDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        entityType="key"
        entityName={removing ?? undefined}
        verb="Remove"
        description="A key a provider connection still signs in with cannot be removed. The value cannot be recovered."
        isLoading={remove.isPending}
        onConfirm={async () => {
          const name = removing!;
          try {
            await remove.mutateAsync(name);
            toast.success(`Removed ${name}`);
            setRemoving(null);
          } catch (e) {
            toast.error(`Couldn’t remove ${name}`, { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
