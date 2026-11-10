'use client';

import * as React from 'react';
import { TriangleAlert } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import type { AuthConfig, ConfigAccount } from '@/components/connections/app-auth-configs';
import { type SignIn, WhoSignsIn } from '@/components/connections/who-signs-in';
import { type AppPage, useChangeAccount } from '@/hooks/systems-queries';
import { useAccountUses } from '@/hooks/plugin-update-queries';
import { useTeam } from '@/hooks/use-team';

/** What a row shows the account as: whoever signed in, else its name. */
const shownAs = (a: ConfigAccount) => a.account ?? a.name;

/**
 * One team account's settings, apart from Connect (which signs it in): its name, what it points at, who signs in to it
 * and its auth config. The team's default is the star on the account's row. Each field shows only where the API
 * offers its action on the row. Renaming and changing who signs in rewrite no workflow or agent version, so both say
 * first how many name the account; changing the auth config signs the account in again.
 */
export function AccountSettingsDialog({
  app,
  account: a,
  configs,
  onClose,
}: {
  app: AppPage;
  account: ConfigAccount;
  /** The app's auth configs the account may sign in through, its current one included. */
  configs: AuthConfig[];
  onClose: () => void;
}) {
  const can = (x: NonNullable<ConfigAccount['actions']>[number]) => (a.actions ?? []).includes(x);
  const offered = app.card.plugin?.signIn;
  const mayRename = can('rename');
  const asksWho = mayRename && (offered?.length ?? 0) > 1 && a.signIn != null;
  const choices = configs.filter((c) => c.type !== 'account');
  const mayMove = can('move') && choices.length > 1;
  const { team } = useTeam();
  const change = useChangeAccount();
  const [name, setName] = React.useState(a.name);
  const [who, setWho] = React.useState<SignIn>((a.signIn as SignIn | null | undefined) ?? 'team');
  const [config, setConfig] = React.useState(a.configId ?? '');
  const next = name.trim();
  const renamed = mayRename && next !== a.name;
  const whoChanged = asksWho && who !== a.signIn;
  const moved = mayMove && config !== (a.configId ?? '');
  const dirty = renamed || whoChanged || moved;
  const busy = change.isPending;

  const save = async () => {
    const body: Parameters<typeof change.mutateAsync>[0]['body'] = { revision: a.revision };
    if (renamed) body.name = next;
    if (whoChanged) Object.assign(body, { signIn: who, teamBackup: who === 'person_or_team' });
    // Ops AI's own app is no credential of the team's: null puts the account on it.
    if (moved) body.credentialId = choices.find((c) => c.id === config)?.type === 'ops_ai' ? null : config;
    try {
      if (renamed || whoChanged || moved) await change.mutateAsync({ appId: app.card.id, accountId: a.id, body });
      toast.success(`${renamed ? next : a.name} is saved`, moved ? { description: 'Sign it in again from its row.' } : undefined);
      onClose();
    } catch (e) {
      toast.error('Couldn’t save the account', { description: e instanceof Error ? e.message : String(e) });
    }
  };

  const points = (a.identity ?? []).map((e) => e.shown).join(' · ');
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="md"
      title={a.name}
      description={`Settings for this ${app.card.name} account. Signing in again is Sign in, on the row.`}
      data-testid="account-settings"
      onSubmit={() => dirty && !busy && next && void save()}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={busy} disabled={!dirty || !next} data-testid="account-settings-save">
            Save
          </LoadingButton>
        </>
      }
    >
      {a.samePlaceAs && (
        <Alert data-testid="account-settings-same-place">
          <TriangleAlert className="text-warning-text" />
          <AlertTitle>{`Points at the same place as ${a.samePlaceAs}`}</AlertTitle>
          <AlertDescription>Both accounts reach the same place. That is fine for a read login and a write login; otherwise delete one.</AlertDescription>
        </Alert>
      )}
      {mayRename && (
        <FormField id="account-settings-name" label="Account name" hint="Steps, agents and chats name an account by this.">
          <Input id="account-settings-name" value={name} onChange={(e) => setName(e.target.value)} data-testid="account-settings-name" />
        </FormField>
      )}
      {(renamed || whoChanged) && <NamedBy app={app.card.id} name={a.name} change={renamed ? 'rename' : 'who'} />}
      <FormField id="account-settings-points" label="Points at">
        <p id="account-settings-points" className="text-sm text-muted-foreground" data-testid="account-settings-points">
          {points || 'Nothing it names yet'}
        </p>
      </FormField>
      {asksWho && (
        <FormField id="account-settings-who" label="Who signs in">
          <WhoSignsIn
            value={who}
            onChange={setWho}
            offered={offered}
            signedIn={team?.memberCount ? { count: a.peopleSignedIn ?? 0, of: team.memberCount } : undefined}
          />
        </FormField>
      )}
      {mayMove && (
        <FormField id="account-settings-config" label="Auth config" hint="Changing it signs the account in again.">
          <Select value={config} onValueChange={setConfig}>
            <SelectTrigger id="account-settings-config" className="w-full" data-testid="account-settings-config">
              <SelectValue placeholder="Pick an auth config" />
            </SelectTrigger>
            <SelectContent>
              {choices.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      )}
    </DialogShell>
  );
}

/**
 * What still names the account, before a rename or a change of who signs in: neither rewrites a workflow or agent
 * version. A rename leaves each one on the old name, so its next publish is refused until it names the new one; a
 * change of who signs in changes whose login every one of them runs as. Says so while the count loads or cannot be
 * read, so nobody changes it on a guess.
 */
export function NamedBy({ app, name, change = 'rename' }: { app: string; name: string; change?: 'rename' | 'who' }) {
  const uses = useAccountUses(app, name);
  const published = uses.data?.published ?? 0;
  const drafts = uses.data?.drafts ?? 0;
  const n = published + drafts;
  const named = `${published} published and ${drafts} draft versions name ${name}.`;
  const text = uses.isPending
    ? 'Checking which workflows and agents name it…'
    : uses.isError
      ? 'Couldn’t check which workflows and agents name it. Each one that does is changed by this.'
      : n === 0
        ? 'No workflow or agent names it.'
        : change === 'rename'
          ? `${named} They keep the old name: each one’s next publish is refused until its step or agent names the new one.`
          : `${named} Each one’s calls change to the login you pick here once you save.`;
  return (
    <p
      className={n > 0 || uses.isError ? 'flex gap-2 text-sm text-warning-text' : 'text-sm text-muted-foreground'}
      role={n > 0 ? 'alert' : undefined}
      data-testid={change === 'rename' ? 'account-rename-uses' : 'account-who-uses'}
    >
      {(n > 0 || uses.isError) && <TriangleAlert className="mt-0.5 size-4 shrink-0" />}
      <span>{text}</span>
    </p>
  );
}
