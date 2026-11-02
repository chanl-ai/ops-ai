'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { appHref } from '@/components/connections/systems-grid';
import { CONNECTED_MESSAGE, openSignIn, type ConnectedMessage } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTeam } from '@/hooks/use-team';
import { type SystemCard, type TeamPluginBody, useDeleteConnection, useSetTeamPlugin, useStartSignIn, useTestEnvironment } from '@/hooks/systems-queries';
import { draftFor, keyed, pluginGroups, turnOnBody, type Kinds } from '@/lib/connect-plan';

/** A plugin the small window can connect: it signs in with an account through Ops AI's own app, so nothing is typed. */
export function connectsSmall(card: SystemCard, kinds: Kinds | undefined): boolean {
  const kind = kinds?.kinds.find((k) => k.id === (card.authKind ?? card.plugin?.kinds[0]));
  // An app turned off keeps its connection and its app credential, Ops AI's or the team's own: Connect turns it on again
  // here, in the same window, rather than in the full setup dialog.
  return card.kind === 'plugin' && Boolean(kind?.signsIn) && (Boolean(card.plugin?.platformApp) || Boolean(card.connectionId));
}

/**
 * Connect from the catalog in a small window (c-607): one button turns the plugin on for the team in
 * production with Ops AI's app and opens the system's own page to allow access. Environments, who signs in and the
 * team's own app are on the app's page; an app that needs keys or its own app opens c-580's connect dialog instead.
 */
export function ConnectSmallDialog({ card, kinds, open, onOpenChange }: { card: SystemCard; kinds: Kinds; open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const setTeamPlugin = useSetTeamPlugin();
  const start = useStartSignIn();
  const remove = useDeleteConnection();
  const test = useTestEnvironment();
  const opened = React.useRef<Window | null>(null);
  // The connection this window made, until the system's page answers: Cancel removes it and turns the plugin off.
  const made = React.useRef<string | null>(null);
  const reopened = React.useRef(false);
  const [waiting, setWaiting] = React.useState(false);
  // Whose account it is: team account anyone in the team can run tools as, or the person's own.
  const [team, setTeam] = React.useState(true);
  const { team: current } = useTeam();
  // The account's name, which steps and tools pick it by (da761a2e); the app and the team until the person changes it.
  const [accountName, setAccountName] = React.useState('');
  const suggested = `${card.name} · ${current?.name ?? 'Team'}`;
  const plugin = card.plugin;
  const kind = kinds.kinds.find((k) => k.id === (card.authKind ?? plugin?.kinds[0]));
  const environment = keyed(kinds).find((e) => e.production)?.id ?? 'production';

  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage>) => {
      if (e.origin !== window.location.origin || e.data?.type !== CONNECTED_MESSAGE || e.source !== opened.current) return;
      opened.current = null;
      made.current = null;
      // The new account is tested once before the app's page shows it, as every connection is (c-580).
      void test
        .mutateAsync({ connectionId: e.data.connectionId, environment })
        .catch(() => undefined)
        .finally(() => {
          toast.success(`${card.name} is connected for the team`);
          onOpenChange(false);
          router.push(appHref(card));
        });
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [card, environment, onOpenChange, router, test]);

  if (!plugin || !kind) return null;
  const connect = async () => {
    try {
      const draft = draftFor(environment, pluginGroups(kind, kinds, plugin, 'platform'));
      const view = await setTeamPlugin.mutateAsync({
        path: { plugin_id: card.pluginId ?? '' },
        // A team account is the fallback and each person may connect their own, when the plugin offers it; unticked,
        // the account is the person's alone and calls sign in as each person.
        body: {
          // An app turned off keeps its connection: its kind and who signs in stay as they were (first: false).
          ...turnOnBody(kind, plugin, 'platform', draft, {}, !card.connectionId, team ? (plugin.signIn.includes('person_or_team') ? 'person_or_team' : undefined) : plugin.signIn.includes('person') ? 'person' : undefined),
          accountName: accountName.trim() || suggested,
        } as TeamPluginBody,
      });
      const id = String(view.connectionId ?? card.connectionId ?? '');
      // Cancel removes only what this window made; an app turned on again keeps its connection and is turned off again.
      made.current = card.connectionId ? null : id;
      reopened.current = Boolean(card.connectionId);
      const s = await start.mutateAsync({ connectionId: id, environment, account: team ? 'team' : 'self' });
      opened.current = openSignIn(s, id);
      setWaiting(true);
    } catch (e) {
      toast.error(`Couldn’t connect ${card.name}`, { description: e instanceof Error ? e.message : String(e) });
    }
  };

  const cancel = async () => {
    opened.current?.close();
    opened.current = null;
    const id = made.current;
    made.current = null;
    if (!id && reopened.current) {
      reopened.current = false;
      await setTeamPlugin.mutateAsync({ path: { plugin_id: card.pluginId ?? '' }, body: { enabled: false, environment } as TeamPluginBody }).catch(() => undefined);
    }
    if (id) {
      try {
        await remove.mutateAsync(id);
        await setTeamPlugin.mutateAsync({ path: { plugin_id: card.pluginId ?? '' }, body: { enabled: false, environment } as TeamPluginBody });
      } catch (e) {
        toast.error(`Couldn’t remove what was made for ${card.name}`, { description: e instanceof Error ? e.message : String(e) });
      }
    }
    onOpenChange(false);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(o) : void cancel())}
      size="sm"
      title={`Connect ${card.name}`}
      description={card.description ?? undefined}
      data-testid="connect-small"
      footer={
        <>
          <Button variant="outline" onClick={() => void cancel()} data-testid="connect-small-cancel">
            Cancel
          </Button>
          <LoadingButton isLoading={setTeamPlugin.isPending || start.isPending || waiting} onClick={() => void connect()} data-testid="connect-small-button">
            <ExternalLink />
            Connect
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="connect-small-name" label="Account name" hint="Steps and tools pick an account by this name.">
          <Input id="connect-small-name" value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder={suggested} data-testid="connect-small-name" />
        </FormField>
        <label className="flex items-start gap-2" data-testid="connect-small-team">
          <Checkbox checked={team} onCheckedChange={(v) => setTeam(v === true)} className="mt-0.5" />
          <span className="grid gap-1">
            <span className="text-sm">Team account</span>
            <span className="text-xs text-muted-foreground">
              Anyone in {current?.name ?? 'the team'} can run tools as this account. Off, it is yours alone.
            </span>
          </span>
        </label>
        <FormField id="connect-small-credential" label="App credential" hint="How it signs in. Your team’s own apps are made under Credentials.">
          {/* Ops AI's app is the one choice here; a team's own app is set on the app's Settings (Use your own app). */}
          <Select value="opsai">
            <SelectTrigger id="connect-small-credential" className="w-full" data-testid="connect-small-app">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="opsai">{card.plugin?.platformApp ? 'Ops AI’s app' : 'Your own app'}</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
        {waiting && <p className="text-sm">Allow access in the {card.name} window that opened.</p>}
      </div>
    </DialogShell>
  );
}
