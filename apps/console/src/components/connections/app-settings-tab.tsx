'use client';

import * as React from 'react';
import { Bot, Workflow } from 'lucide-react';
import { toast } from 'sonner';

import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DangerZone } from '@/components/shared/danger-zone';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { SettingsSection } from '@/components/shared/settings-section';
import { type AppPage, useAppUsers, useChangeAccount, useDeleteApp, useSetTeamApp } from '@/hooks/systems-queries';
import type { Kinds } from '@/lib/connect-plan';
import { plural } from '@/lib/format';

/**
 * The app's Settings tab: whether people may connect their own account, how the app signs in, and the danger zone
 * (turn it off, or delete it from the team). Auth configs and their callback URL live on the Auth configs tab.
 */
export function SettingsTab({ app, kinds, onSetUp, onDeleted }: { app: AppPage; kinds?: Kinds; onSetUp: () => void; onDeleted: () => void }) {
  const conn = app.connection;
  const change = useChangeAccount();
  const kind = kinds?.kinds.find((k) => k.id === conn?.authKind);
  const [off, setOff] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  if (!conn) return null;
  const may = Boolean(conn.mayManage);
  const personal = conn.signIn !== 'team';
  // On: each person may add their own account, with the team's sign-in as backup for those who have not.
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
              <span className="block text-xs text-muted-foreground">They connect it under My accounts, and tools they run use it. Off, everyone runs as a team account.</span>
            </label>
            <Switch id="app-everyone" checked={personal} disabled={!may || change.isPending} onCheckedChange={flip} data-testid="app-everyone" />
          </div>
        </SettingsSection>
      )}
      <SettingsSection title="Sign-in">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1 text-sm">
            <span className="block font-medium">{kind?.label ?? conn.authKind}</span>
            <span className="block text-xs text-muted-foreground">
              {kind?.signsIn ? `Each account signs in to ${app.card.name} through an auth config.` : `Each account holds its own keys for ${app.card.name}.`}
            </span>
          </span>
          {may && (
            <Button size="sm" variant="outline" onClick={onSetUp} data-testid="app-edit">
              Change sign-in
            </Button>
          )}
        </div>
      </SettingsSection>
      {may && (
        <DangerZone
          items={[
            ...(app.card.pluginId
              ? [{ title: 'Turn off', description: 'Its tools stop for this team; its accounts and what you added stay.', action: `Turn off ${app.card.name}`, onClick: () => setOff(true), testId: 'app-off' }]
              : []),
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
      {off && <TurnOffDialog name={app.card.name} appId={app.card.id} onClose={() => setOff(false)} />}
      {deleting && <DeleteAppDialog app={app} onClose={() => setDeleting(false)} onDeleted={onDeleted} />}
    </div>
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
