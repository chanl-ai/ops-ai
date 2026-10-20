'use client';

import * as React from 'react';
import { ShieldCheck } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import type { MfaSetup } from '@/lib/auth/provider';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/**
 * Two-step verification setup: add the account to an authenticator, keep the recovery codes, confirm with a code.
 * The setup key and the otpauth link stand in for a QR code until a QR renderer is added to the app.
 */
export function MfaSetupForm({ setup, loading, pending, error, onEnrol }: { setup?: MfaSetup; loading: boolean; pending: boolean; error: string | null; onEnrol: (code: string) => void }) {
  const [code, setCode] = React.useState('');
  return (
    <AuthFormWrapper showPanel={false} className="mx-auto max-w-lg">
      <form
        noValidate
        data-testid="mfa-setup"
        onSubmit={(e) => {
          e.preventDefault();
          if (code.length === 6) onEnrol(code);
        }}
      >
        <div className="flex flex-col gap-6">
          <AuthHeading icon={<ShieldCheck className="size-6" />} title="Set up two-step verification" description="Your workspace requires it. It takes a minute with any authenticator app." />
          <ol className="flex flex-col gap-4 text-sm">
            <li className="flex flex-col gap-2">
              <span className="font-medium">1. Add Northfield Ops AI to your authenticator</span>
              {loading || !setup ? (
                <Skeleton className="h-16 w-full" />
              ) : (
                <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3">
                  <a href={setup.otpauthUrl} className="text-sm font-medium underline underline-offset-4">
                    Open in your authenticator app
                  </a>
                  <span className="text-xs text-muted-foreground">Or enter this setup key:</span>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 font-mono text-sm tracking-wider" data-testid="mfa-secret">
                      {setup.secret}
                    </code>
                    <CopyButton text={setup.secret} variant="outline" size="sm" />
                  </div>
                </div>
              )}
            </li>
            <li className="flex flex-col gap-2">
              <span className="font-medium">2. Keep your recovery codes</span>
              <span className="text-xs text-muted-foreground">Each works once if you lose your phone. They are shown only now.</span>
              {setup && (
                <div className="grid grid-cols-2 gap-1 rounded-lg border bg-muted/30 p-3 font-mono text-sm" data-testid="mfa-recovery">
                  {setup.recoveryCodes.map((c) => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
              )}
            </li>
            <li className="flex flex-col gap-2">
              <span className="font-medium">3. Enter the 6-digit code your app shows</span>
              <FormField id="mfa-setup-code" label="Code">
                <Input id="mfa-setup-code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} placeholder="e.g. 482913" className="text-center text-lg tracking-widest" />
              </FormField>
            </li>
          </ol>
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending} loadingText="Checking…" disabled={code.length !== 6 || !setup} data-testid="mfa-enrol">
            Turn on two-step verification
          </LoadingButton>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
