'use client';

import * as React from 'react';
import { Bot, Workflow } from 'lucide-react';
import { toast } from 'sonner';

import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Switch } from '@/components/ui/switch';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DangerZone } from '@/components/shared/danger-zone';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { SettingsSection } from '@/components/shared/settings-section';
import { AddAuthConfigButton, TurnOnButton } from '@/components/connections/app-actions';
import { type AppPage, useAppUsers, useChangeAccount, useChangeAppKind, useDeleteApp, useSetTeamApp } from '@/hooks/systems-queries';
import type { Kind, Kinds } from '@/lib/connect-plan';
import { addAuthConfigFirst, appStateFor } from '@/lib/app-state';
import { plural } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * The app's Settings tab: whether people may connect their own account, how the app signs in, whether it is on for the
 * team, and deleting it. Turning it off keeps its accounts and tools, so it is a setting, not in the danger zone. Auth
 * configs and their callback URL live on the Auth configs tab.
 */
export function SettingsTab({
  app,
  kinds,
  onSetUp,
  onTurnOn,
  onDeleted,
}: {
  app: AppPage;
  kinds?: Kinds;
  onSetUp: () => void;
  /** The first turn-on's window; an app turned off before goes back on from here directly. */
  onTurnOn: () => void;
  onDeleted: () => void;
}) {
  const conn = app.connection;
  const change = useChangeAccount();
  const kind = kinds?.kinds.find((k) => k.id === conn?.authKind);
  const [off, setOff] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [changing, setChanging] = React.useState(false);
  // An app with no account yet (never turned on) still shows whether it is on, and its one next action.
  if (!conn)
    return app.card.pluginId && app.card.mayManage && app.card.plugin ? (
      <div className="flex flex-col gap-4" data-testid="app-settings">
        <OnForTeam app={app} onTurnOn={onTurnOn} onTurnOff={() => setOff(true)} />
      </div>
    ) : null;
  // An app the system no longer has installed changes nothing here; an admin may still delete what it left.
  const mayDelete = Boolean(conn.mayManage);
  const may = mayDelete && app.card.appGroup !== 'gone';
  const personal = conn.signIn !== 'team';
  // On: tools a person runs use their own account, and the team's sign-in serves only runs nobody started.
  const flip = (on: boolean) =>
    change.mutate(
      { appId: app.card.id, accountId: conn.id, body: { revision: conn.revision, signIn: on ? 'person_or_team' : 'team', teamBackup: on } },
      { onError: (e) => toast.error('Couldn’t change personal accounts', { description: e.message }) },
    );
  return (
    <div className="flex flex-col gap-4" data-testid="app-settings">
      {kind?.perPerson && (
        <SettingsSection title="Personal accounts">
          <div className="flex items-center gap-3">
            <label htmlFor="app-everyone" className="min-w-0 flex-1 text-sm">
              <span className="block font-medium">{`People can connect their own ${app.card.name} account`}</span>
              <span className="block text-xs text-muted-foreground">Tools a person runs use their own account, connected under Connectors; anyone who has not is asked to connect. Runs nobody started, such as schedules and mailboxes, use the team account. Off, everyone runs as the team account.</span>
            </label>
            <Switch id="app-everyone" checked={personal} disabled={!may || change.isPending} onCheckedChange={flip} data-testid="app-everyone" />
          </div>
        </SettingsSection>
      )}
      <SettingsSection title="Sign-in">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1 basis-60 text-sm">
            <span className="block font-medium">{kind?.label ?? conn.authKind}</span>
            <span className="block text-xs text-muted-foreground">
              {kind?.signsIn ? `Each account signs in to ${app.card.name} through an auth config.` : `Each account holds its own keys for ${app.card.name}.`}
            </span>
          </span>
          {may && (
            <span className="flex flex-wrap gap-2">
              {/* A plugin signs in the one way it declares; a custom app may move to another kind. */}
              {!app.card.pluginId && (kinds?.kinds.length ?? 0) > 1 && (
                <Button size="sm" variant="outline" onClick={() => setChanging(true)} data-testid="app-change-kind">
                  Change sign-in
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={onSetUp} data-testid="app-edit">
                Edit settings
              </Button>
            </span>
          )}
        </div>
        {app.card.pluginId && <p className="text-xs text-muted-foreground">{`${app.card.name}’s plugin sets how it signs in.`}</p>}
      </SettingsSection>
      {may && app.card.pluginId && <OnForTeam app={app} onTurnOn={onTurnOn} onTurnOff={() => setOff(true)} />}
      {mayDelete && (
        <DangerZone
          items={[
            {
              title: 'Delete app',
              description: `Removes ${app.card.name}, its accounts and its tools from this team. Agents using its tools stop.`,
              action: 'Delete app',
              onClick: () => setDeleting(true),
              destructive: true,
              testId: 'app-delete',
            },
          ]}
        />
      )}
      {changing && kinds && <ChangeKindDialog app={app} kinds={kinds.kinds} current={conn.authKind} onClose={() => setChanging(false)} onChanged={onSetUp} />}
      {off && <TurnOffDialog name={app.card.name} appId={app.card.id} onClose={() => setOff(false)} />}
      {deleting && <DeleteAppDialog app={app} onClose={() => setDeleting(false)} onDeleted={onDeleted} />}
    </div>
  );
}

/**
 * Change sign-in: one of the ways a custom app may sign in. Every account moves to it and drops what it held for the old
 * way (keys, tokens, each person's sign-in), so the window says so first; the answer names the accounts to set up again,
 * and the set-up window then opens for the new way's fields.
 */
function ChangeKindDialog({ app, kinds, current, onClose, onChanged }: { app: AppPage; kinds: Kind[]; current: string; onClose: () => void; onChanged: () => void }) {
  const change = useChangeAppKind();
  const [picked, setPicked] = React.useState(current);
  const accounts = (app.accounts ?? []).filter((a) => a.kind === 'team').length;
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="md"
      title={`Change how ${app.card.name} signs in`}
      description={`Every account of ${app.card.name} moves to the new way and must be set up and signed in again. Its keys, tokens and each person's sign-in for the old way are removed.`}
      data-testid="app-kind-dialog"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={change.isPending}
            disabled={picked === current}
            onClick={() =>
              change.mutate(
                { appId: app.card.id, kind: picked },
                {
                  onSuccess: (r) => {
                    toast.success(`${app.card.name} signs in a new way`, { description: r.accounts.length ? `Set up again: ${r.accounts.join(', ')}` : undefined });
                    onClose();
                    onChanged();
                  },
                  onError: (e) => toast.error('Couldn’t change how it signs in', { description: e.message }),
                },
              )
            }
            data-testid="app-kind-save"
          >
            Change sign-in
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <RadioGroup value={picked} onValueChange={setPicked} className="grid gap-2" aria-label="Ways to sign in">
          {kinds.map((k) => (
            <label key={k.id} htmlFor={`kind-${k.id}`} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', picked === k.id && 'border-primary bg-primary/5')}>
              <RadioGroupItem value={k.id} id={`kind-${k.id}`} className="mt-0.5" data-testid={`app-kind-${k.id}`} />
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {k.label}
                  {k.id === current && <span className="ml-2 text-xs font-normal text-muted-foreground">Now</span>}
                </span>
                <span className="block text-xs text-muted-foreground">{k.id === 'none' ? 'Calls send no credentials.' : k.signsIn ? 'Each account signs in once in the browser.' : 'Each account holds its own keys.'}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
        {accounts > 0 && <p className="text-xs text-muted-foreground">{`${plural(accounts, 'account')} will need setting up again.`}</p>}
      </div>
    </DialogShell>
  );
}

/** Delete app: names the accounts it takes and the tools it holds, and says why when a tool still uses it. */
function DeleteAppDialog({ app, onClose, onDeleted }: { app: AppPage; onClose: () => void; onDeleted: () => void }) {
  const remove = useDeleteApp();
  const accounts = (app.accounts ?? []).filter((a) => a.kind === 'team').map((a) => a.account ?? a.name);
  const [refused, setRefused] = React.useState<string | null>(null);
  return (
    <ConfirmActionDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Delete ${app.card.name}?`}
      consequence={`${app.card.name} leaves this team with ${plural(accounts.length, 'account')} and their secrets. Agents and workflows using its ${plural(app.tools.length, 'tool')} stop.`}
      details={[
        { label: 'Accounts', value: accounts.join(', ') || 'None' },
        { label: 'Tools', value: plural(app.tools.length, 'tool') },
      ]}
      runsNow
      note={refused ?? undefined}
      confirmLabel="Delete app"
      destructive
      isPending={remove.isPending}
      onConfirm={() =>
        remove.mutateAsync(app.card.id).then(
          () => {
            toast.success(`${app.card.name} is deleted from this team`);
            onDeleted();
          },
          (e: unknown) => setRefused(e instanceof Error ? e.message : String(e)),
        )
      }
    />
  );
}

/** On for this team: the card's state, as the header's badge reads it (lib/app-state.ts), with its one next action. */
function OnForTeam({ app, onTurnOn, onTurnOff }: { app: AppPage; onTurnOn: () => void; onTurnOff: () => void }) {
  const shown = appStateFor(app.card.appState, app.card.appGroup, Boolean(app.card.mayManage));
  return (
    <SettingsSection title="On for this team">
      <div className="flex flex-wrap items-center gap-3" data-testid="app-on-for-team" data-state={app.card.appState}>
        <span className="min-w-0 flex-1 basis-60 text-sm">
          <span className="block font-medium">
            {shown.on ? `${app.card.name} is on` : shown.action === 'add_auth_config' ? addAuthConfigFirst(app.card.name) : `${app.card.name} is off`}
          </span>
          <span className="block text-xs text-muted-foreground">
            {shown.action === 'fix_auth_config'
              ? `${app.card.appStateReason ?? ''} Add a working auth config and sign in again, or turn it off.`
              : shown.on
              ? 'Turned off, its tools stop for this team; its accounts and the tools you added stay.'
              : shown.action === 'add_auth_config'
                ? `${app.card.name} signs in through an auth config, and this team has none it can use.`
                : 'Its tools stop for this team until it is turned on. Turning it on keeps its accounts and the tools you added, and signs nobody in.'}
          </span>
        </span>
        {shown.on ? (
          // Turn off stays whenever the team has it on, a broken auth config included.
          <span className="flex flex-wrap gap-2">
            {shown.action === 'fix_auth_config' && <AddAuthConfigButton appId={app.card.id} testId="app-settings-fix-auth-config" />}
            <Button size="sm" variant="outline" onClick={onTurnOff} data-testid="app-off">
              Turn off
            </Button>
          </span>
        ) : shown.action === 'add_auth_config' ? (
          <AddAuthConfigButton appId={app.card.id} testId="app-settings-add-auth-config" />
        ) : shown.action === 'turn_on' ? (
          <TurnOnButton card={app.card} variant="outline" onFirstTurnOn={onTurnOn} testId="app-settings-turn-on" />
        ) : null}
      </div>
    </SettingsSection>
  );
}

/**
 * Turn off: stops the app's tools for this team, keeping its accounts and what the team added. The window names every
 * agent and workflow using its tools first, read when it opens; when the service cannot tell, it says so.
 */
function TurnOffDialog({ name, appId, onClose }: { name: string; appId: string; onClose: () => void }) {
  const users = useAppUsers(appId);
  const setTeamApp = useSetTeamApp();
  const listed = [...(users.data?.agents ?? []).map((a) => ({ ...a, what: 'agent' as const })), ...(users.data?.workflows ?? []).map((w) => ({ ...w, what: 'workflow' as const }))];
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Turn off ${name}?`}
      description="These use its tools and stop working until it is turned on again."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton
            variant="destructive"
            isLoading={setTeamApp.isPending}
            disabled={users.isPending || users.isError}
            onClick={() =>
              setTeamApp.mutate(
                { appId, body: { enabled: false, sandbox: false } },
                { onSuccess: () => (onClose(), toast.success(`${name} is off for this team`)), onError: (e) => toast.error(`Couldn’t turn off ${name}`, { description: e.message }) },
              )
            }
            data-testid="app-off-confirm"
          >
            Turn off
          </LoadingButton>
        </>
      }
    >
      <div data-testid="app-off-users">
        {users.isPending ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : users.isError ? (
          <QueryError what={`what uses ${name}`} error={users.error} onRetry={() => users.refetch()} retrying={users.isFetching} />
        ) : listed.length ? (
          <Rows>
            {listed.map((u) => (
              <Row
                key={`${u.what}:${u.id}`}
                leading={u.what === 'agent' ? <Bot className="size-4 text-muted-foreground" /> : <Workflow className="size-4 text-muted-foreground" />}
                title={u.name}
                description={`${u.what === 'agent' ? 'Agent' : 'Workflow'} · ${plural(u.tools.length, 'tool')}`}
              />
            ))}
          </Rows>
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="app-off-none">
            No agent or workflow uses its tools.
          </p>
        )}
      </div>
    </DialogShell>
  );
}
