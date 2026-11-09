'use client';

import * as React from 'react';
import { KeyRound, Power } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { LoadingButton } from '@/components/shared/loading-button';
import { NewAppCredentialDialog } from '@/components/connections/new-app-credential-dialog';
import { type SystemCard, useSetTeamApp } from '@/hooks/systems-queries';

/**
 * Turn on (appState off): an app the team turned off before goes back on as it was, with its accounts and settings,
 * and nothing signs in; one never turned on opens the Turn on window (`onFirstTurnOn`), which saves and stops.
 */
export function TurnOnButton({
  card,
  onFirstTurnOn,
  variant = 'default',
  testId = 'app-turn-on',
}: {
  card: SystemCard;
  onFirstTurnOn: () => void;
  variant?: 'outline' | 'default';
  testId?: string;
}) {
  const setTeamApp = useSetTeamApp();
  const again = () =>
    setTeamApp.mutate(
      { appId: card.id, body: { enabled: true, sandbox: false } },
      { onSuccess: () => toast.success(`${card.name} is on for this team`), onError: (e) => toast.error(`Couldn’t turn on ${card.name}`, { description: e.message }) },
    );
  return (
    <LoadingButton size="sm" variant={variant} isLoading={setTeamApp.isPending} onClick={(e) => (e.stopPropagation(), card.connectionId ? again() : onFirstTurnOn())} data-testid={testId}>
      <Power />
      Turn on
    </LoadingButton>
  );
}

/**
 * The next action of an app with nothing to sign in through (appState needs_auth_config): opens the new auth config
 * for that app. Saving it signs nobody in; the app's state then moves on by itself, as every auth config change
 * reloads the app's card.
 */
export function AddAuthConfigButton({
  appId,
  onCreated,
  variant = 'outline',
  link = false,
  testId = 'add-auth-config',
}: {
  appId: string;
  onCreated?: (credentialId: string) => void;
  variant?: 'outline' | 'default';
  /** Drawn as a link inside a sentence, as a field's hint. */
  link?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      {link ? (
        <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={(e) => (e.stopPropagation(), setOpen(true))} data-testid={testId}>
          Add an auth config
        </Button>
      ) : (
        <Button type="button" size="sm" variant={variant} onClick={(e) => (e.stopPropagation(), setOpen(true))} data-testid={testId}>
          <KeyRound />
          Add an auth config
        </Button>
      )}
      {/* Made from an app's own state, so the person stays where they are rather than opening the config's page. */}
      <NewAppCredentialDialog open={open} onOpenChange={setOpen} app={appId} onCreated={(id) => (setOpen(false), onCreated?.(id))} />
    </>
  );
}
