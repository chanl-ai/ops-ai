'use client';

import * as React from 'react';
import { KeyRound, ShieldCheck, Users } from 'lucide-react';

import { AuthError } from '@/components/auth/auth-form-wrapper';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';
import type { InvitePreview } from '@/lib/types/invites';

const PASSWORD_MIN = 12;

/**
 * Accept an invitation: your name, then a password, or Continue with SSO when the email belongs to a verified SSO
 * domain. The page signs you in with what you chose; this form only collects it.
 */
export function InviteForm({ invite, pending, error, onSubmit }: { invite: InvitePreview; pending: boolean; error?: string; onSubmit: (input: { name: string; password?: string }) => void }) {
  const [name, setName] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [touched, setTouched] = React.useState(false);
  const errors = {
    name: name.trim().length < 2 ? 'Enter your name.' : undefined,
    password: invite.sso ? undefined : password.length < PASSWORD_MIN ? `Use at least ${PASSWORD_MIN} characters.` : undefined,
    confirm: invite.sso ? undefined : confirm !== password ? 'The two passwords do not match.' : undefined,
  };
  const err = (k: keyof typeof errors) => (touched ? errors[k] : undefined);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (errors.name || errors.password || errors.confirm) return;
    onSubmit({ name: name.trim(), password: invite.sso ? undefined : password });
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} data-testid="invite-form">
      <div className="flex items-start gap-3 rounded-md border bg-muted/30 p-3 text-sm">
        <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <p>
          <span className="font-medium">{invite.invitedBy}</span> invited <span className="font-medium">{invite.email}</span> to <span className="font-medium">{invite.team}</span> as {invite.role}.
        </p>
      </div>
      <AuthError message={error ?? null} />
      <FormField id="inv-name" label="Your name" error={err('name')}>
        <Input id="inv-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="e.g. Sam Ortiz" aria-invalid={!!err('name')} autoFocus />
      </FormField>
      {invite.sso ? (
        <p className="flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" /> {invite.email.split('@')[1]} signs in with {invite.ssoProviderLabel ?? 'your company’s identity provider'}. You will not set a password here.
        </p>
      ) : (
        <>
          <FormField id="inv-password" label="Password" error={err('password')} hint={`At least ${PASSWORD_MIN} characters. Not your name or email.`}>
            <Input id="inv-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" aria-invalid={!!err('password')} />
          </FormField>
          <FormField id="inv-confirm" label="Confirm password" error={err('confirm')}>
            <Input id="inv-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" aria-invalid={!!err('confirm')} />
          </FormField>
        </>
      )}
      {invite.mfaRequired && <p className="text-xs text-muted-foreground">Your workspace requires two-step verification. You will set up an authenticator app after this.</p>}
      <LoadingButton type="submit" isLoading={pending} loadingText={invite.sso ? 'Redirecting…' : 'Joining…'} data-testid="invite-accept">
        {invite.sso ? (
          <>
            <ShieldCheck className="size-4" /> Continue with SSO
          </>
        ) : (
          <>
            <KeyRound className="size-4" /> Join {invite.team}
          </>
        )}
      </LoadingButton>
    </form>
  );
}
