'use client';

import * as React from 'react';
import { CheckCircle2, Circle } from 'lucide-react';
import { toast } from 'sonner';

import { ConnectionCredentialFields, ConnectionOwnerExpiryFields, type ConsentState, vaultProblem, ymd } from '@/components/integrations/connect-dialog';
import { ScopePicker } from '@/components/integrations/scope-picker';
import { LoadingButton } from '@/components/shared/loading-button';
import { SampleData } from '@/components/shared/sample-data';
import { SettingsSection } from '@/components/shared/settings-section';
import { useActivateConnection, useConnectFlow, useSaveConnectionSetup } from '@/hooks/integration-queries';
import type { IntegrationDetail } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

/**
 * A draft connection's setup: the guided connect's Scopes, Credential and Owner and expiry steps as sections that
 * each save on their own, then Connect, which runs the same checks and makes it live.
 */
export function SetupTab({ connection: i }: { connection: IntegrationDetail }) {
  const flow = useConnectFlow(true);
  const save = useSaveConnectionSetup(i.id);
  const activate = useActivateConnection(i.id);
  const system = flow.catalog.find((c) => c.id === i.catalogId);
  const oauth = i.authMethod === 'oauth_consent';

  const [scopes, setScopes] = React.useState<string[]>(i.scopes);
  const [consent, setConsent] = React.useState<ConsentState>(i.consentBy ? 'granted' : 'none');
  const [credentialRef, setCredentialRef] = React.useState(i.credentialRef ?? '');
  const [owner, setOwner] = React.useState(i.ownerTeam);
  const [expiry, setExpiry] = React.useState(i.expiresAt ? i.expiresAt.slice(0, 10) : ymd(oauth ? 90 : 180));
  const credError = !oauth && credentialRef ? (vaultProblem(credentialRef) ?? undefined) : undefined;
  const expiryError = !expiry ? 'Choose when the connection expires.' : new Date(`${expiry}T23:59:59`).getTime() <= Date.now() ? 'Choose a date after today.' : undefined;

  // OAuth consent is saved the moment it is granted, so the checklist below reflects it without another click.
  const onConsent = (c: ConsentState) => {
    setConsent(c);
    if (c === 'granted') save.mutate({ consentBy: flow.currentUser }, { onSuccess: () => toast.success(`Consent granted by ${flow.currentUser}`) });
  };
  const saveWith = (patch: Parameters<typeof save.mutate>[0], done: string) => save.mutate(patch, { onSuccess: () => toast.success(done), onError: (e) => toast.error('Couldn’t save', { description: e.message }) });

  const checks = [
    { label: 'At least one scope granted', ok: i.scopes.length > 0 },
    { label: oauth ? 'Consent granted' : 'Vault reference saved', ok: oauth ? !!i.consentBy : !!i.credentialRef },
    { label: 'Owner team and an expiry in the future', ok: !!i.ownerTeam && !!i.expiresAt && new Date(i.expiresAt).getTime() > Date.now() },
  ];

  if (!system) return <p className="text-sm text-muted-foreground">Loading the system’s scopes…</p>;
  return (
    <div className="flex flex-col gap-4" data-testid="connection-setup">
      <SampleData>
      <SettingsSection title="Scopes" description="Grant only what the sources and tools on this connection need. Reads are selected; writes are opt-in.">
        <div className="flex flex-col gap-3">
          <ScopePicker scopes={system.scopes} selected={scopes} onChange={setScopes} />
          <LoadingButton size="sm" className="self-start" isLoading={save.isPending} disabled={!scopes.length || scopes.join() === i.scopes.join()} onClick={() => saveWith({ scopes }, `Saved ${scopes.length} scopes`)} data-testid="setup-save-scopes">
            Save scopes
          </LoadingButton>
        </div>
      </SettingsSection>
      <SettingsSection title="Credential" description="How the gateway proves who it is.">
        <div className="flex flex-col gap-3">
          <ConnectionCredentialFields
            system={system}
            auth={i.authMethod}
            scopes={i.scopes}
            instanceUrl={i.instanceUrl}
            currentUser={flow.currentUser}
            consent={consent}
            onConsent={onConsent}
            onSignIn={() => setConsent('screen')}
            credentialRef={credentialRef}
            onCredentialRef={setCredentialRef}
            credentialError={credError}
          />
          {!oauth && (
            <LoadingButton size="sm" className="self-start" isLoading={save.isPending} disabled={!credentialRef || !!credError || credentialRef === i.credentialRef} onClick={() => saveWith({ credentialRef }, 'Saved the vault reference')} data-testid="setup-save-credential">
              Save reference
            </LoadingButton>
          )}
        </div>
      </SettingsSection>
      <SettingsSection title="Owner and expiry" description="Who answers for it and when it ends.">
        <div className="flex flex-col gap-3">
          <ConnectionOwnerExpiryFields auth={i.authMethod} teams={flow.teams} owner={owner} onOwner={setOwner} expiry={expiry} onExpiry={setExpiry} expiryError={expiryError} />
          <LoadingButton size="sm" className="self-start" isLoading={save.isPending} disabled={!owner || !!expiryError} onClick={() => saveWith({ ownerTeam: owner, expiresAt: new Date(`${expiry}T23:59:59`).toISOString() }, 'Saved owner and expiry')} data-testid="setup-save-owner">
            Save owner and expiry
          </LoadingButton>
        </div>
      </SettingsSection>
      <SettingsSection title="Connect" description="Nothing can use the connection until it connects. The checks run again on the server.">
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col gap-1.5 text-sm" data-testid="setup-checklist">
            {checks.map((c) => (
              <li key={c.label} className={cn('flex items-center gap-2', !c.ok && 'text-muted-foreground')}>
                {c.ok ? <CheckCircle2 className="size-4 text-success-text" /> : <Circle className="size-4" />} {c.label}
              </li>
            ))}
          </ul>
          <LoadingButton
            className="self-start"
            isLoading={activate.isPending}
            disabled={!checks.every((c) => c.ok)}
            onClick={() => activate.mutate(undefined, { onSuccess: (x) => toast.success(`Connected ${x.name}`, { description: 'Sources, tool modules and mailboxes can now pick it.' }), onError: (e) => toast.error('Couldn’t connect', { description: e.message }) })}
            data-testid="setup-activate"
          >
            Connect {system.name}
          </LoadingButton>
        </div>
      </SettingsSection>
      </SampleData>
    </div>
  );
}
