'use client';

import * as React from 'react';
import { Copy, LogOut, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { AccountTabs } from '@/components/account/account-tabs';
import { MfaDevicesTable, SessionsTable } from '@/components/account/account-tables';
import { PageLayout } from '@/components/page-layout';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { SampleData } from '@/components/shared/sample-data';
import { SettingsSection } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useAccountProfile, useAccountSessions, useChangePassword, useMfaDevices, useRegenerateRecoveryCodes, useRemoveMfaDevice, useRevokeOtherSessions, useRevokeSession } from '@/hooks/account-queries';
import { useReauthenticate, useSession } from '@/hooks/auth-queries';
import type { AccountSession, MfaDevice } from '@/lib/types/account';

const MIN = 12;
const ALL = { page: 1, pageSize: 50 };

/** Account → Security: password (password accounts only), two-step methods and recovery codes, and where you are signed in. */
export default function AccountSecurityPage() {
  const profile = useAccountProfile();
  const devices = useMfaDevices();
  const sessions = useAccountSessions(ALL);
  const reauth = useReauthenticate();
  const changePassword = useChangePassword();
  const regenerate = useRegenerateRecoveryCodes();
  const removeDevice = useRemoveMfaDevice();
  const revoke = useRevokeSession();
  const revokeOthers = useRevokeOtherSessions();
  const { session } = useSession();
  // Enrolled password accounts confirm the change with their authenticator code too, as at sign-in.
  const needsCode = session?.authMethod === 'password' && !!session.mfaEnrolled;
  const [pw, setPw] = React.useState({ current: '', code: '', next: '', confirm: '' });
  const [pwError, setPwError] = React.useState<string>();
  const [codes, setCodes] = React.useState<string[] | null>(null);
  const [confirmAll, setConfirmAll] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const p = profile.data;
  const others = (sessions.data?.data ?? []).filter((s) => !s.current).length;

  const submitPassword = async () => {
    setPwError(undefined);
    if (pw.next.length < MIN) return setPwError(`Use at least ${MIN} characters.`);
    if (pw.next !== pw.confirm) return setPwError('The new passwords do not match.');
    if (needsCode && !/^\d{6}$/.test(pw.code.trim())) return setPwError('Enter the 6-digit code from your authenticator app.');
    try {
      await reauth.mutateAsync({ method: 'password', password: pw.current, code: needsCode ? pw.code.trim() : undefined });
      await changePassword.mutateAsync(pw.next);
      setPw({ current: '', code: '', next: '', confirm: '' });
      toast.success('Password changed', { description: 'Use it next time you sign in. Other sessions stay signed in; sign them out below if you need to.' });
    } catch (e) {
      setPwError((e as Error).message);
    }
  };
  const onRevoke = (s: AccountSession) => {
    setBusyId(s.id);
    revoke.mutate(s.id, { onSuccess: () => toast.success(`Signed out ${s.device}`), onError: (e) => toast.error('Couldn’t sign it out', { description: e.message }), onSettled: () => setBusyId(null) });
  };
  const onRemove = (d: MfaDevice) => removeDevice.mutate(d.id, { onSuccess: () => toast.success(`Removed ${d.label}`), onError: (e) => toast.error('Couldn’t remove it', { description: e.message }) });

  const loading = profile.isPending || devices.isPending || sessions.isPending;
  const failed = (profile.isError && !p) || (devices.isError && !devices.data) || (sessions.isError && !sessions.data);

  return (
    <PageLayout icon={ShieldCheck} title="Account" description="Your profile and how you sign in" tabs={<AccountTabs />}>
      {loading ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      ) : failed ? (
        <QueryError what="your security settings" onRetry={() => (profile.refetch(), devices.refetch(), sessions.refetch())} retrying={profile.isFetching || devices.isFetching || sessions.isFetching} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="account-security">
          <SampleData>
          {p?.authMethod === 'password' ? (
            <SettingsSection title="Password" description="You confirm your current password (and authenticator code) first. The new one works from your next sign-in.">
              <div className="flex max-w-sm flex-col gap-3" data-testid="change-password">
                {pwError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{pwError}</p>}
                <FormField id="pw-current" label="Current password">
                  <Input id="pw-current" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} className="bg-background" />
                </FormField>
                {needsCode && (
                  <FormField id="pw-code" label="Authenticator code">
                    <Input id="pw-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={pw.code} onChange={(e) => setPw({ ...pw, code: e.target.value })} className="bg-background" placeholder="e.g. 123456" />
                  </FormField>
                )}
                <FormField id="pw-next" label="New password" hint={`At least ${MIN} characters.`}>
                  <Input id="pw-next" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} className="bg-background" />
                </FormField>
                <FormField id="pw-confirm" label="Confirm new password">
                  <Input id="pw-confirm" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} className="bg-background" />
                </FormField>
                <LoadingButton size="sm" className="self-start" isLoading={reauth.isPending || changePassword.isPending} disabled={!pw.current || !pw.next} onClick={submitPassword} data-testid="save-password">
                  Change password
                </LoadingButton>
              </div>
            </SettingsSection>
          ) : (
            <SettingsSection title="Password" description={`You sign in with ${p?.ssoProvider ?? 'single sign-on'}; your password is managed there.`}>
              <span />
            </SettingsSection>
          )}
          <SettingsSection title="Two-step verification" description="An authenticator app code at sign-in, and recovery codes for when the phone is lost.">
            <MfaDevicesTable
              devices={devices.data ?? []}
              busy={regenerate.isPending || removeDevice.isPending}
              onRemove={onRemove}
              onRegenerate={() => regenerate.mutate(undefined, { onSuccess: (r) => setCodes(r.codes), onError: (e) => toast.error('Couldn’t regenerate the codes', { description: e.message }) })}
            />
          </SettingsSection>
          <SettingsSection title="Where you are signed in" description="Sign out a device you do not recognise, or every device except this one.">
            <div className="flex flex-col gap-3">
              <SessionsTable sessions={sessions.data?.data ?? []} onRevoke={onRevoke} busyId={busyId} />
              <Button variant="outline" size="sm" className="self-start" disabled={!others} onClick={() => setConfirmAll(true)} data-testid="sign-out-everywhere">
                <LogOut className="size-4" /> Sign out everywhere else
              </Button>
            </div>
          </SettingsSection>
          </SampleData>
        </div>
      )}

      <DialogShell
        open={!!codes}
        onOpenChange={(o) => !o && setCodes(null)}
        size="md"
        title="New recovery codes"
        description="Each works once. Keep them somewhere safe; they are not shown again. The old codes no longer work."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => codes && navigator.clipboard?.writeText(codes.join('\n')).then(() => toast.success('Copied the codes'))}>
              <Copy className="size-4" /> Copy
            </Button>
            <Button onClick={() => setCodes(null)}>Done</Button>
          </div>
        }
      >
        <ul className="grid grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2" data-testid="recovery-codes">
          {(codes ?? []).map((c) => (
            <li key={c} className="rounded-md border bg-muted/40 px-3 py-1.5 text-center">
              {c}
            </li>
          ))}
        </ul>
      </DialogShell>
      <DialogShell
        open={confirmAll}
        onOpenChange={setConfirmAll}
        size="sm"
        title="Sign out everywhere else?"
        description={`${others} other ${others === 1 ? 'session' : 'sessions'} end now. This device stays signed in.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmAll(false)}>
              Cancel
            </Button>
            <LoadingButton
              variant="destructive"
              isLoading={revokeOthers.isPending}
              onClick={() => revokeOthers.mutate(undefined, { onSuccess: (r) => (toast.success(`Signed out ${r.revoked} sessions`), setConfirmAll(false)), onError: (e) => toast.error('Couldn’t sign them out', { description: e.message }) })}
              data-testid="confirm-sign-out-everywhere"
            >
              Sign out {others}
            </LoadingButton>
          </div>
        }
      >
        <span />
      </DialogShell>
    </PageLayout>
  );
}
