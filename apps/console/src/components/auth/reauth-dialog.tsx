'use client';

import * as React from 'react';
import { LockKeyhole, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SSO_PROVIDER_LABEL } from '@/components/settings/sign-in-sections';
import { useReauthenticate, useSession, useSignInPolicy, useStartSsoStepUp, useTakeStepUp } from '@/hooks/auth-queries';
import type { StepUp } from '@/lib/auth';

/**
 * Step-up before approving a call that needs one. Password accounts confirm with their password, plus the authenticator code when
 * enrolled. SSO and Google accounts go back to their identity provider, which applies its own MFA, and return here
 * with a step-up waiting; the person then presses Approve again. Either way the token is good for 5 minutes.
 */
export function ReauthDialog({ open, onOpenChange, action, onVerified }: { open: boolean; onOpenChange: (o: boolean) => void; action: string; onVerified: (s: StepUp) => void }) {
  const { session } = useSession();
  const { data: policy } = useSignInPolicy();
  const reauth = useReauthenticate();
  const startSso = useStartSsoStepUp();
  const [password, setPassword] = React.useState('');
  const [code, setCode] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) {
      setPassword('');
      setCode('');
      setError(undefined);
    }
  }, [open]);
  const viaIdp = session?.authMethod === 'sso' || session?.authMethod === 'google';
  const needsCode = !viaIdp && !!session?.mfaEnrolled;
  const idp = session?.authMethod === 'google' ? 'Google' : policy ? SSO_PROVIDER_LABEL[policy.sso.provider] : 'your identity provider';

  const submit = async () => {
    setError(undefined);
    if (!password) return setError('Enter your password.');
    if (needsCode && !/^\d{6}$/.test(code.trim())) return setError('Enter the 6-digit code from your authenticator app.');
    try {
      onVerified(await reauth.mutateAsync({ method: 'password', password, code: needsCode ? code.trim() : undefined }));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const goToIdp = async () => {
    setError(undefined);
    try {
      const { redirectUrl } = await startSso.mutateAsync({ returnTo: window.location.pathname + window.location.search });
      window.location.assign(redirectUrl);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Confirm it is you"
      description={`${action} needs two approvers. Confirm your identity to continue; you will not be asked again for 5 minutes.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={reauth.isPending || startSso.isPending}>
            Cancel
          </Button>
          {viaIdp ? (
            <LoadingButton isLoading={startSso.isPending} loadingText="Redirecting…" onClick={goToIdp} data-testid="reauth-idp">
              <ShieldCheck className="size-4" /> Verify with {idp}
            </LoadingButton>
          ) : (
            <LoadingButton isLoading={reauth.isPending} onClick={submit} data-testid="reauth-submit">
              <LockKeyhole className="size-4" /> Confirm
            </LoadingButton>
          )}
        </div>
      }
    >
      {viaIdp ? (
        <div className="flex flex-col gap-2 text-sm text-muted-foreground" data-testid="reauth-sso">
          <p>You sign in through {idp}. You will go there to confirm, then come back to this page; press Approve again when you are back.</p>
          {error && <p className="text-destructive">{error}</p>}
        </div>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          data-testid="reauth-dialog"
        >
          <FormField id="reauth-secret" label={`Password for ${session?.user.email ?? 'your account'}`} error={needsCode ? undefined : error}>
            <Input id="reauth-secret" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!error && !needsCode} autoFocus />
          </FormField>
          {needsCode && (
            <FormField id="reauth-code" label="Authenticator code" error={error}>
              <Input id="reauth-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} aria-invalid={!!error} placeholder="e.g. 123456" />
            </FormField>
          )}
          <button type="submit" hidden />
        </form>
      )}
    </DialogShell>
  );
}

// One step-up per browser tab, reused until it expires, so Reviews, bulk approve and chat ask once per 5 minutes.
let cached: StepUp | null = null;
const fresh = () => (cached && new Date(cached.expiresAt).getTime() > Date.now() ? cached.token : undefined);
/** The API refuses such an approval without a step-up with 422 and a message naming step-up. */
export const isStepUpRefusal = (e: unknown) => e instanceof Error && (e as Error & { status?: number }).status === 422 && /step-up/i.test(e.message);

/**
 * Runs an action that may need a step-up: it sends the cached token if there is one, and when the API refuses for
 * want of one it opens "Confirm it is you", then retries once with the new token. Render `dialog` once on the page.
 */
export function useStepUpGate() {
  const [pending, setPending] = React.useState<{ label: string; resolve: (t: string) => void; reject: (e: Error) => void } | null>(null);
  // Back from an identity-provider step-up: keep its token so the next Approve goes straight through.
  const takeStepUp = useTakeStepUp();
  React.useEffect(() => {
    const s = takeStepUp();
    if (!s) return;
    cached = s;
    toast.success('Identity confirmed', { description: 'Approve now; the confirmation lasts 5 minutes.' });
  }, [takeStepUp]);
  const ask = React.useCallback((label: string) => new Promise<string>((resolve, reject) => setPending({ label, resolve, reject })), []);
  /** `upfront`: the server marked the action as needing a step-up, so ask before sending rather than after its 422. */
  const withStepUp = React.useCallback(async <T,>(label: string, run: (token?: string) => Promise<T>, opts?: { upfront?: boolean }): Promise<T> => {
    try {
      return await run(fresh() ?? (opts?.upfront ? await ask(label) : undefined));
    } catch (e) {
      if (!isStepUpRefusal(e)) throw e;
      return run(await ask(label));
    }
  }, [ask]);
  const dialog = (
    <ReauthDialog
      open={!!pending}
      onOpenChange={(o) => {
        if (o) return;
        pending?.reject(new StepUpCancelled());
        setPending(null);
      }}
      action={pending?.label ?? 'This approval'}
      onVerified={(s) => {
        cached = s;
        pending?.resolve(s.token);
        setPending(null);
      }}
    />
  );
  return { withStepUp, dialog };
}

/** Thrown when the person closes "Confirm it is you"; callers treat it as a cancel, not a failure. */
export class StepUpCancelled extends Error {
  constructor() {
    super('Approval cancelled: identity not confirmed.');
    this.name = 'StepUpCancelled';
  }
}
