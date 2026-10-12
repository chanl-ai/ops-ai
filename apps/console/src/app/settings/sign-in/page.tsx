'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { SignInMethodsSection, SignInSecuritySection, SignInSignupSection, SignInSsoSection } from '@/components/settings/sign-in-sections';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Skeleton } from '@/components/ui/skeleton';
import { useAddSsoDomain, useRemoveSsoDomain, useSaveSignInPolicy, useSignInPolicySettings, useTestSsoConnection, useVerifySsoDomain } from '@/hooks/account-queries';
import { relativeTime } from '@/lib/format';
import type { SignInPolicyPatch } from '@/lib/types/sign-in';
import { KeyRound } from 'lucide-react';

const SAVED: Record<SignInPolicyPatch['section'], string> = { methods: 'Saved sign-in methods', sso: 'Saved the SSO connection', security: 'Saved sign-in security', signup: 'Saved self-signup' };

/** Settings → Sign-in: what the login screen offers, the SSO connection and its domains, MFA and sessions. Each section saves on its own and is audited. */
export default function SignInSettingsPage() {
  const query = useSignInPolicySettings();
  const save = useSaveSignInPolicy();
  const addDomain = useAddSsoDomain();
  const verify = useVerifySsoDomain();
  const remove = useRemoveSsoDomain();
  const test = useTestSsoConnection();
  const [saving, setSaving] = React.useState<SignInPolicyPatch['section'] | null>(null);
  const [busyDomain, setBusyDomain] = React.useState<string | null>(null);
  const p = query.data;

  const onSave = async (patch: SignInPolicyPatch) => {
    setSaving(patch.section);
    try {
      await save.mutateAsync(patch);
      toast.success(SAVED[patch.section], { description: 'Applies at the next sign-in. Recorded in the audit log.' });
    } catch (e) {
      toast.error('Couldn’t save', { description: (e as Error).message });
    } finally {
      setSaving(null);
    }
  };
  const onDomain = (fn: typeof verify | typeof remove, done: (d: string) => string) => (d: string) => {
    setBusyDomain(d);
    fn.mutate(d, { onSuccess: () => toast.success(done(d)), onError: (e) => toast.error(`Couldn’t change ${d}`, { description: e.message }), onSettled: () => setBusyDomain(null) });
  };

  return (
    <SettingsPageLayout section="Sign-in" description="How people sign in to this workspace: methods, single sign-on, two-step verification and sessions.">
      {query.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-36 w-full" />
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError && !p ? (
        <QueryError what="the sign-in settings" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : p ? (
        <div className="flex flex-col gap-4" data-testid="sign-in-settings">
          <p className="text-xs text-muted-foreground">
            Saved by {p.updatedBy} {relativeTime(p.updatedAt)}
          </p>
          <SignInMethodsSection policy={p} saving={saving === 'methods'} onSave={onSave} />
          <SignInSsoSection
            policy={p}
            saving={saving === 'sso'}
            onSave={onSave}
            onAddDomain={async (d) => {
              await addDomain.mutateAsync(d);
              toast.success(`Added ${d.trim().toLowerCase()}`, { description: 'Publish the TXT record shown, then verify it.' });
            }}
            onVerifyDomain={onDomain(verify, (d) => `Verified ${d}`)}
            onRemoveDomain={onDomain(remove, (d) => `Removed ${d}`)}
            onTest={() => test.mutate(undefined, { onSuccess: (r) => (r.ok ? toast.success('SSO connection works', { description: r.message }) : toast.error('SSO connection failed', { description: r.message })) })}
            busyDomain={busyDomain}
            testing={test.isPending}
          />
          {!p.sso.domains.length && <EmptyState icon={KeyRound} title="No SSO domains yet" description="Add the email domain your staff use so they sign in with your identity provider." />}
          <SignInSecuritySection policy={p} saving={saving === 'security'} onSave={onSave} />
          <SignInSignupSection policy={p} saving={saving === 'signup'} onSave={onSave} />
        </div>
      ) : null}
    </SettingsPageLayout>
  );
}
