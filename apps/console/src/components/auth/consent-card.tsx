'use client';

import { Bot } from 'lucide-react';

import { KeyValues } from '@/components/shared/surface';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { plural } from '@/lib/format';
import type { OAuthConsent } from '@/lib/types/oauth';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

const lasts = (hours: number) => (hours % 24 === 0 && hours >= 24 ? plural(hours / 24, 'day') : plural(hours, 'hour'));

/**
 * Asks the signed-in person to let an assistant use one team's tools. The assistant's name is what it called itself,
 * so the page says so and shows the website the browser returns to, which is what tells a lookalike apart.
 */
export function ConsentCard({ consent, pending, error, onAnswer }: { consent?: OAuthConsent; pending: 'allow' | 'deny' | null; error: string | null; onAnswer: (decision: 'allow' | 'deny') => void }) {
  return (
    <div className="mx-auto w-full max-w-md">
      <AuthFormWrapper showPanel={false}>
        <div className="flex flex-col gap-6" data-testid="consent">
          <AuthHeading
            icon={<Bot className="size-6" />}
            title={consent ? `Let ${consent.client.name} use ${consent.team.name}?` : 'This request cannot continue'}
            description={consent ? 'It will act as you, in this team only.' : undefined}
          />
          {consent && (
            <>
              <KeyValues
                rows={[
                  ['Assistant', <span key="a" data-testid="consent-client-name" className="break-words">{consent.client.name}</span>],
                  ['Name source', <span key="s" data-testid="consent-name-source" className="text-muted-foreground">{consent.client.nameIsSelfReported ? 'This is the name the assistant gave itself. Ops AI has not checked it.' : 'Checked by Ops AI.'}</span>],
                  ['Team', <span key="t" data-testid="consent-team">{consent.team.name} <span className="font-mono text-xs text-muted-foreground">{consent.team.id}</span></span>],
                  ['You return to', <span key="r" data-testid="consent-redirect-host" className="font-mono text-sm break-all">{consent.redirectHost}</span>],
                  ['Lasts', `${lasts(consent.connectionHours)}, then it asks you to sign in again`],
                ]}
              />
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                <li>It can run the tools you may run in this team.</li>
                <li>Anything that changes data still waits for approval where your team requires it.</li>
                <li>You can disconnect it any time under My security.</li>
              </ul>
            </>
          )}
          <AuthError message={error} />
          {consent && (
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="outline" disabled={!!pending} onClick={() => onAnswer('deny')} data-testid="consent-deny">
                Deny
              </Button>
              <LoadingButton isLoading={pending === 'allow'} loadingText="Allowing…" disabled={!!pending} onClick={() => onAnswer('allow')} data-testid="consent-allow">
                Allow
              </LoadingButton>
            </div>
          )}
        </div>
      </AuthFormWrapper>
    </div>
  );
}
