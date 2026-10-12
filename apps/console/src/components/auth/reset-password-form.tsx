'use client';

import * as React from 'react';
import Link from 'next/link';
import { CheckCircle2 } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/** Choose a new password from a reset link. */
export function ResetPasswordForm({ pending, error, done, onReset }: { pending: boolean; error: string | null; done: boolean; onReset: (password: string) => void }) {
  const [password, setPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [err, setErr] = React.useState<{ password?: string; confirm?: string }>({});
  if (done)
    return (
      <AuthFormWrapper>
        <div className="flex flex-col gap-6" data-testid="reset-done">
          <AuthHeading icon={<CheckCircle2 className="size-6" />} title="Password changed" description="Sign in with your new password." />
          <Button asChild className="w-full">
            <Link href="/login">Sign in</Link>
          </Button>
        </div>
      </AuthFormWrapper>
    );
  return (
    <AuthFormWrapper>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const next = { password: password.length >= 12 ? undefined : 'Use at least 12 characters.', confirm: confirm === password ? undefined : 'The two passwords do not match.' };
          setErr(next);
          if (next.password || next.confirm) return;
          onReset(password);
        }}
      >
        <div className="flex flex-col gap-6">
          <AuthHeading title="Choose a new password" description="At least 12 characters. A passphrase is easiest to remember." />
          <FormField id="new-password" label="New password" error={err.password}>
            <Input id="new-password" type="password" autoComplete="new-password" autoFocus value={password} aria-invalid={!!err.password} onChange={(e) => (setPassword(e.target.value), setErr({}))} />
          </FormField>
          <FormField id="confirm-password" label="Confirm password" error={err.confirm}>
            <Input id="confirm-password" type="password" autoComplete="new-password" value={confirm} aria-invalid={!!err.confirm} onChange={(e) => (setConfirm(e.target.value), setErr({}))} />
          </FormField>
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending} loadingText="Saving…" data-testid="reset-save">
            Save new password
          </LoadingButton>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
