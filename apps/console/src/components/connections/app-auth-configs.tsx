'use client';

import * as React from 'react';
import { ExternalLink, KeyRound, MoreVertical, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { CallbackUrl } from '@/components/connections/callback-url';
import { CredentialDeleteDialog } from '@/components/connections/credential-delete-dialog';
import { CredentialEditDialog } from '@/components/connections/credential-edit-dialog';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ListEmpty } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  type AppPage,
  useAppCredential,
  useChangeAccount,
  useDeleteAccount,
  useMakeTeamDefault,
  usePinDefault,
  useSignOutMine,
  useSignOutTeam,
} from '@/hooks/systems-queries';

export type AuthConfig = NonNullable<AppPage['authConfigs']>[number];
export type ConfigAccount = NonNullable<AuthConfig['accounts']>[number];

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

// The Apps design's three account states; a refused or revoked sign-in reads Expired, its reason beside it.
const STATE: Record<ConfigAccount['state'], { label: string; className: string }> = {
  connected: { label: 'Connected', className: 'border-success/40 bg-success/10 text-success-text' },
  not_signed_in: { label: 'Not signed in', className: '' },
  expired: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  refused: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  revoked: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
};

/** Whose sign-in an account is, by name: the team's, or one person's own. */
const whose = (a: ConfigAccount, team: string) => (a.owner.kind === 'team' ? `${team} team sign-in` : `${a.owner.name}’s own sign-in`);

/**
 * Auth configs: how the app's accounts sign in, each config with the accounts under it. Ops AI's own app is never
 * edited or deleted; the team's own are, by a team admin, with Delete naming the accounts on it and moving them. Each
 * account shows whose sign-in it is, its one state from the API and only the actions the API offers.
 */
export function AuthConfigsTab({
  app,
  team,
  onAddAccount,
  onSignIn,
}: {
  app: AppPage;
  /** The team's name, for whose sign-in a team account is. */
  team: string;
  /** Opens Connect on this config. */
  onAddAccount: (config: AuthConfig) => void;
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
}) {
  const configs = app.authConfigs ?? [];
  const [editing, setEditing] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<string | null>(null);
  const others = (a: ConfigAccount) => configs.filter((c) => c.id !== a.configId && c.type !== 'account');
  if (!configs.length)
    return (
      <Section title="Auth configs" flush>
        <div className="p-4" data-testid="app-auth-configs-none">
          <ListEmpty icon={KeyRound} noun="auth configs" filtered={false} description={`${app.card.name} has no auth config yet. Connect it to add one.`} />
        </div>
      </Section>
    );
  return (
    <div className="flex flex-col gap-4" data-testid="app-auth-configs">
      {configs.map((c) => (
        <Section
          key={c.id || 'account'}
          title={
            <span className="flex flex-wrap items-center gap-2" data-testid={`auth-config-${c.name}`}>
              {c.name}
              {c.type === 'ops_ai' && <Badge variant="secondary">Built in</Badge>}
              {c.default && <Badge variant="outline">Default</Badge>}
            </span>
          }
          description={
            c.type === 'ops_ai'
              ? `Ops AI’s own ${app.card.name} app. Kept by Ops AI; it cannot be edited or deleted.`
              : c.type === 'account'
                ? 'Each account holds its own key.'
                : [c.clientId ? `Client ID ${c.clientId}` : null, c.secretEnds ? `secret ending ${c.secretEnds}` : null].filter(Boolean).join(' · ') || 'The team’s own app.'
          }
          flush
          actions={
            <span className="flex flex-wrap gap-2">
              {c.canEdit && (
                <Button size="sm" variant="outline" onClick={() => setEditing(c.id)} data-testid={`auth-config-edit-${c.name}`}>
                  <Pencil />
                  Edit
                </Button>
              )}
              {c.canDelete && (
                <Button size="sm" variant="outline" onClick={() => setDeleting(c.id)} data-testid={`auth-config-delete-${c.name}`}>
                  <Trash2 />
                  Delete
                </Button>
              )}
              {app.card.mayManage && c.type !== 'account' && (
                <Button size="sm" variant="outline" onClick={() => onAddAccount(c)} data-testid={`auth-config-add-${c.name}`}>
                  <Plus />
                  Add account
                </Button>
              )}
            </span>
          }
        >
          {c.type === 'own' && c.canEdit && (
            <div className="border-b px-4 py-3">
              <CallbackUrl app={app.card.name} id={`auth-config-callback-${c.id}`} testId={`auth-config-callback-${c.name}`} />
            </div>
          )}
          {c.accounts?.length ? (
            <Rows testId={`auth-config-accounts-${c.name}`}>
              {c.accounts.map((a) => (
                <AccountRow key={a.id} app={app} account={a} team={team} moveTo={others(a)} onSignIn={onSignIn} />
              ))}
            </Rows>
          ) : (
            <p className="px-4 py-3 text-sm text-muted-foreground">No account signs in with it yet.</p>
          )}
        </Section>
      ))}
      <CredentialEditDialog credentialId={editing} onClose={() => setEditing(null)} />
      {deleting && <DeleteConfig id={deleting} platform={configs.some((c) => c.type === 'ops_ai')} onClose={() => setDeleting(null)} />}
    </div>
  );
}

/** Delete on a config: its page answer names the accounts on it, which the dialog offers to move. */
export function DeleteConfig({ id, platform, onClose }: { id: string; platform: boolean; onClose: () => void }) {
  const q = useAppCredential(id);
  return <CredentialDeleteDialog credential={q.data ?? null} platform={platform} onOpenChange={(o) => !o && onClose()} onDeleted={onClose} />;
}

function AccountRow({
  app,
  account: a,
  team,
  moveTo,
  onSignIn,
}: {
  app: AppPage;
  account: ConfigAccount;
  team: string;
  moveTo: AuthConfig[];
  onSignIn: (account: 'self' | 'team', accountId: string) => void;
}) {
  const ref = { appId: app.card.id, accountId: a.id };
  const change = useChangeAccount();
  const remove = useDeleteAccount();
  const signOutTeam = useSignOutTeam();
  const signOutMine = useSignOutMine();
  const pin = usePinDefault();
  const teamDefault = useMakeTeamDefault();
  const [dialog, setDialog] = React.useState<'rename' | 'move' | 'delete' | null>(null);
  const can = (x: NonNullable<ConfigAccount['actions']>[number]) => (a.actions ?? []).includes(x);
  // An account only its owner signs in to is signed in, renewed and ended as that person's own.
  const as = a.owner.kind === 'person' ? 'self' : 'team';
  const failed = a.test?.status === 'failed' ? a.test.message || 'no reason given' : null;
  const disconnect = () =>
    (as === 'self' ? signOutMine.mutateAsync(a.id) : signOutTeam.mutateAsync(ref)).then(
      () => toast.success(`${a.name} is disconnected`),
      (e: unknown) => toast.error('Couldn’t disconnect', { description: message(e) }),
    );
  const menu = [
    can('rename') && { label: 'Rename', onClick: () => setDialog('rename') },
    can('make_team_default') && {
      label: 'Make the team’s default',
      onClick: () =>
        teamDefault.mutate(ref, {
          onSuccess: () => toast.success(`${a.name} is the team’s default`, { description: 'Calls that name no account use it.' }),
          onError: (e) => toast.error('Couldn’t make it the default', { description: e.message }),
        }),
    },
    can('make_default') && {
      label: 'Make my default',
      onClick: () => pin.mutate(ref, { onError: (e) => toast.error('Couldn’t make it your default', { description: e.message }) }),
    },
    can('move') && moveTo.length > 0 && { label: 'Move to another auth config', onClick: () => setDialog('move') },
    can('disconnect') && { label: 'Disconnect', onClick: () => void disconnect() },
    can('delete') && { label: 'Delete', onClick: () => setDialog('delete'), destructive: true },
  ].filter(Boolean) as { label: string; onClick: () => void; destructive?: boolean }[];
  return (
    <>
      <Row
        wrap
        title={
          <span className="flex flex-wrap items-center gap-2" data-testid={`account-${a.name}`}>
            {a.name}
            {a.default && <Badge variant="secondary">Default</Badge>}
            {a.sandbox && (
              <Badge variant="outline" data-testid={`account-sandbox-${a.name}`}>
                Sandbox
              </Badge>
            )}
            <Badge variant="outline" className={STATE[a.state].className} data-testid={`account-state-${a.name}`} data-state={a.state}>
              {STATE[a.state].label}
            </Badge>
            {a.myDefault && <Badge variant="outline">Your default</Badge>}
          </span>
        }
        description={
          failed ? (
            <span className="text-warning-text" data-testid={`account-test-failed-${a.name}`}>
              Signed in, but a test call failed: {failed}
            </span>
          ) : (
            [whose(a, team), a.account ? `as ${a.account}` : null, a.stateReason].filter(Boolean).join(' · ')
          )
        }
        trailing={
          <span className="flex flex-wrap items-center gap-2">
            {can('sign_in') && (
              <Button size="sm" onClick={() => onSignIn(as, a.id)} data-testid={`account-sign-in-${a.name}`}>
                <ExternalLink />
                Sign in
              </Button>
            )}
            {can('reconnect') && (a.state !== 'connected' || failed) && (
              <Button size="sm" onClick={() => onSignIn(as, a.id)} data-testid={`account-reconnect-${a.name}`}>
                <RefreshCw />
                Reconnect
              </Button>
            )}
            {can('connect_mine') && (
              <Button size="sm" variant="outline" onClick={() => onSignIn('self', a.id)} data-testid={`account-connect-mine-${a.name}`}>
                <ExternalLink />
                Use my own account
              </Button>
            )}
            {(menu.length > 0 || (can('reconnect') && a.state === 'connected' && !failed)) && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" aria-label={`${a.name} actions`} data-testid={`account-menu-${a.name}`}>
                    <MoreVertical />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {can('reconnect') && a.state === 'connected' && !failed && <DropdownMenuItem onClick={() => onSignIn(as, a.id)}>Reconnect</DropdownMenuItem>}
                  {menu.map((m) => (
                    <DropdownMenuItem key={m.label} onClick={m.onClick} className={m.destructive ? 'text-destructive' : undefined} data-testid={`account-action-${m.label}-${a.name}`}>
                      {m.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </span>
        }
      />
      {dialog === 'rename' && (
        <RenameDialog
          name={a.name}
          busy={change.isPending}
          onClose={() => setDialog(null)}
          onSave={(name) =>
            change.mutate(
              { ...ref, body: { revision: a.revision, name } },
              { onSuccess: () => (toast.success(`Renamed to ${name}`), setDialog(null)), onError: (e) => toast.error('Couldn’t rename it', { description: e.message }) },
            )
          }
        />
      )}
      {dialog === 'move' && (
        <MoveDialog
          account={a.name}
          to={moveTo}
          busy={change.isPending}
          onClose={() => setDialog(null)}
          onMove={(c) =>
            change.mutate(
              // Ops AI's own app is no credential: null puts the account on it.
              { ...ref, body: { revision: a.revision, credentialId: c.type === 'ops_ai' ? null : c.id } },
              {
                onSuccess: () => (toast.success(`${a.name} moved to ${c.name}`, { description: 'It signs in again with Reconnect.' }), setDialog(null)),
                onError: (e) => toast.error('Couldn’t move it', { description: e.message }),
              },
            )
          }
        />
      )}
      <DeleteDialog
        open={dialog === 'delete'}
        onOpenChange={(o) => !o && setDialog(null)}
        entityType="account"
        entityName={a.name}
        description={`Calls naming ${a.name} stop working. Its sign-in is ended.`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(ref);
            toast.success(`${a.name} is deleted`);
            setDialog(null);
          } catch (e) {
            toast.error('Couldn’t delete it', { description: message(e) });
          }
        }}
        testIdPrefix={`account-delete-${a.name}`}
      />
    </>
  );
}

function RenameDialog({ name, busy, onClose, onSave }: { name: string; busy: boolean; onClose: () => void; onSave: (name: string) => void }) {
  const [value, setValue] = React.useState(name);
  const next = value.trim();
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Rename ${name}`}
      description="Steps and tools pick an account by this name."
      data-testid="account-rename"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton isLoading={busy} disabled={!next || next === name} onClick={() => onSave(next)} data-testid="account-rename-save">
            Save
          </LoadingButton>
        </>
      }
    >
      <FormField id="account-rename-name" label="Name">
        <Input id="account-rename-name" value={value} onChange={(e) => setValue(e.target.value)} />
      </FormField>
    </DialogShell>
  );
}

function MoveDialog({ account, to, busy, onClose, onMove }: { account: string; to: AuthConfig[]; busy: boolean; onClose: () => void; onMove: (c: AuthConfig) => void }) {
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
