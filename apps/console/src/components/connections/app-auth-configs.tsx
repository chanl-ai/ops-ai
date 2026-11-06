'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Plus, Trash2 } from 'lucide-react';

import { CallbackUrl } from '@/components/connections/callback-url';
import { CredentialDeleteDialog } from '@/components/connections/credential-delete-dialog';
import { CredentialEditDialog } from '@/components/connections/credential-edit-dialog';
import { NewAppCredentialDialog } from '@/components/connections/new-app-credential-dialog';
import { type ConfigMode, MODE_LABEL } from '@/components/connections/sign-in-place';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { CopyButton } from '@/components/shared/copy-button';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow } from '@/components/shared/field-row';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { type AppPage, useAppCredential } from '@/hooks/systems-queries';
import { plural } from '@/lib/format';

export type AuthConfig = NonNullable<AppPage['authConfigs']>[number];
export type ConfigAccount = NonNullable<AppPage['accounts']>[number];

// The Apps design's three account states; a refused or revoked sign-in reads Expired, its reason beside it.
export const STATE: Record<ConfigAccount['state'], { label: string; className: string }> = {
  connected: { label: 'Connected', className: 'border-success/40 bg-success/10 text-success-text' },
  not_signed_in: { label: 'Not signed in', className: '' },
  expired: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  refused: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  revoked: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
};

/**
 * The app's Auth configs tab: how Ops AI signs in to the app, one row each, with where it signs in and how many
 * accounts use it (a link to them on the Accounts tab). What a person reads once (client ID, secret, callback URL,
 * permissions) opens in the config's details sheet. Ops AI's app is always listed and never edited.
 */
export function AuthConfigsTab({ app, onShowAccounts }: { app: AppPage; onShowAccounts: (configId: string) => void }) {
  const configs = (app.authConfigs ?? []).filter((c) => c.type !== 'account');
  const [open, setOpen] = React.useState<string | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<string | null>(null);
  const shown = configs.find((c) => c.id === open) ?? null;
  const rows = configs.map((c) => ({ ...c, onRowClick: (x: AuthConfig) => setOpen(x.id) }));
  const columns: ColumnDef<AuthConfig>[] = [
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Auth config" />,
      meta: { kind: 'name' },
      cell: ({ row: { original: c } }) => (
        <span className="flex min-w-0 flex-wrap items-center gap-2" data-testid={`auth-config-${c.name}`}>
          <span className="truncate">{c.name}</span>
          <Badge variant={c.type === 'ops_ai' ? 'secondary' : 'outline'}>{c.type === 'ops_ai' ? 'Built in' : 'Your team’s app'}</Badge>
        </span>
      ),
    },
    {
      id: 'place',
      accessorFn: (c) => c.signInPlace ?? '',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Sign-in place" />,
      cell: ({ row: { original: c } }) => <PlaceOf config={c} />,
    },
    {
      id: 'accounts',
      accessorFn: (c) => c.accountCount,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Accounts" />,
      cell: ({ row: { original: c } }) => (
        <StopRowClick align="start">
          <Button variant="link" size="sm" className="h-auto p-0 tabular-nums" disabled={!c.accountCount} onClick={() => onShowAccounts(c.id)} data-testid={`auth-config-accounts-${c.name}`}>
            {c.accountCount ? plural(c.accountCount, 'account') : 'No accounts'}
          </Button>
        </StopRowClick>
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-4" data-testid="app-auth-configs">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          {`How Ops AI signs in to ${app.card.name}. Ops AI’s app needs no setup; add your team’s own app to use your consent screen or a fixed org.`}
        </p>
        {app.card.mayManage && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="auth-config-new">
            <Plus />
            New auth config
          </Button>
        )}
      </div>
      <DataTableWithViews columns={columns} data={rows} getRowId={(c) => c.id} hideViewSwitcher />
      <DetailSheet
        open={!!shown}
        onOpenChange={(o) => !o && setOpen(null)}
        title={shown?.name ?? ''}
        description={shown ? `${shown.type === 'ops_ai' ? 'Built in' : 'Your team’s app'} · Auth config · ${app.card.name}` : undefined}
        testId="auth-config-details"
        footerActions={
          shown && shown.type === 'own' ? (
            <span className="flex gap-2">
              {shown.canDelete && (
                <Button variant="outline" size="sm" onClick={() => setDeleting(shown.id)} data-testid={`auth-config-delete-${shown.name}`}>
                  <Trash2 />
                  Delete
                </Button>
              )}
              {shown.canEdit && (
                <Button size="sm" onClick={() => setEditing(shown.id)} data-testid={`auth-config-edit-${shown.name}`}>
                  <Pencil />
                  Edit
                </Button>
              )}
            </span>
          ) : undefined
        }
      >
        {shown && <ConfigDetails app={app} config={shown} onShowAccounts={(id) => (setOpen(null), onShowAccounts(id))} />}
      </DetailSheet>
      <NewAppCredentialDialog open={adding} onOpenChange={setAdding} app={app.card.id} onCreated={() => setAdding(false)} />
      <CredentialEditDialog credentialId={editing} onClose={() => setEditing(null)} />
      {deleting && <DeleteConfig id={deleting} platform={configs.some((c) => c.type === 'ops_ai')} onClose={() => (setDeleting(null), setOpen(null))} />}
    </div>
  );
}

/** Where a config's accounts sign in, as a person reads it, with Fixed or Default; Connect asks when it holds none. */
function PlaceOf({ config: c }: { config: AuthConfig }) {
  const held = (c.fields ?? []).find((f) => f.value);
  if (!held) return <span className="text-sm text-muted-foreground">Asked in Connect</span>;
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid={`auth-config-place-${c.name}`}>
      <span className="truncate">{held.shown ?? held.value}</span>
      {held.mode && <Badge variant="outline">{MODE_LABEL[held.mode as ConfigMode]}</Badge>}
    </span>
  );
}

/** A config's read-once details: its client, callback URL, sign-in place, permissions and how many accounts use it. */
function ConfigDetails({ app, config: c, onShowAccounts }: { app: AppPage; config: AuthConfig; onShowAccounts: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-4" data-testid={`auth-config-details-${c.name}`}>
      {c.type === 'ops_ai' && <p className="text-sm text-muted-foreground">Kept by Ops AI. It cannot be edited.</p>}
      {c.clientId && (
        <FieldRow label="Client ID" value={c.clientId} mono adornment={<CopyButton text={c.clientId} size="icon" className="size-6" />} testId={`auth-config-client-id-${c.name}`} />
      )}
      {c.secretEnds && <FieldRow label="Client secret" value={`Ends in ${c.secretEnds}`} testId={`auth-config-secret-${c.name}`} />}
      {c.type === 'own' && <CallbackUrl app={app.card.name} id={`auth-config-callback-${c.id}`} testId={`auth-config-callback-${c.name}`} />}
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium">Sign-in place</span>
        <PlaceOf config={c} />
      </div>
      {(c.permissions ?? []).length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Permissions</span>
          <span className="flex flex-wrap gap-2" data-testid={`auth-config-permissions-${c.name}`}>
            {(c.permissions ?? []).map((p) => (
              <Badge key={p.id} variant="outline" title={p.id}>
                {p.label}
                {p.askedAtSignIn ? ' · next sign-in' : ''}
              </Badge>
            ))}
          </span>
          <span className="text-xs text-muted-foreground">From the tools switched on in Tools.</span>
        </div>
      )}
      <div className="flex items-center gap-2 text-sm">
        <span className="font-medium">Accounts</span>
        <Button variant="link" size="sm" className="h-auto p-0 tabular-nums" disabled={!c.accountCount} onClick={() => onShowAccounts(c.id)}>
          {c.accountCount ? plural(c.accountCount, 'account') : 'No accounts'}
        </Button>
      </div>
    </div>
  );
}

/** Delete on a config: its page answer names the accounts on it, which the dialog offers to move. */
export function DeleteConfig({ id, platform, onClose }: { id: string; platform: boolean; onClose: () => void }) {
  const q = useAppCredential(id);
  return <CredentialDeleteDialog credential={q.data ?? null} platform={platform} onOpenChange={(o) => !o && onClose()} onDeleted={onClose} />;
}

export function MoveDialog({ account, to, busy, onClose, onMove }: { account: string; to: AuthConfig[]; busy: boolean; onClose: () => void; onMove: (c: AuthConfig) => void }) {
  const [picked, setPicked] = React.useState(to[0]?.id ?? '');
  const chosen = to.find((c) => c.id === picked);
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Move ${account}`}
      description="It signs in with the auth config you pick, and signs in again once moved."
      data-testid="account-move"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton isLoading={busy} disabled={!chosen} onClick={() => chosen && onMove(chosen)} data-testid="account-move-save">
            Move
          </LoadingButton>
        </>
      }
    >
      <FormField id="account-move-to" label="Auth config">
        <Select value={picked} onValueChange={setPicked}>
          <SelectTrigger id="account-move-to" data-testid="account-move-to">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {to.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
    </DialogShell>
  );
}
