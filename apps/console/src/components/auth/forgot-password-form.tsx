'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeft, Building2, Mail } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/**
 * Ask for a reset link. The confirmation reads the same whether or not the email has an account. `previewUrl` is
 * the mock's stand-in for the email, so the demo can follow the link. `managedBy` names the IdP when the email is on
 * a verified SSO domain: no link is sent, and the person signs in through SSO instead.
 */
export function ForgotPasswordForm({ pending, error, sentTo, previewUrl, managedBy, ssoPending, onSend, onSso }: { pending: boolean; error: string | null; sentTo: string | null; previewUrl?: string; managedBy?: { email: string; idp: string }; ssoPending?: boolean; onSend: (email: string) => void; onSso?: (email: string) => void }) {
  const [email, setEmail] = React.useState('');
  const [missing, setMissing] = React.useState<string | null>(null);
  if (managedBy)
    return (
      <AuthFormWrapper>
        <div className="flex flex-col gap-6" data-testid="forgot-managed">
          <AuthHeading icon={<Building2 className="size-6" />} title={`Your password is managed by ${managedBy.idp}.`} description={`${managedBy.email} signs in through ${managedBy.idp}, so its password is reset there, not here.`} />
          <AuthError message={error} />
          <LoadingButton className="w-full" isLoading={!!ssoPending} loadingText="Redirecting…" onClick={() => onSso?.(managedBy.email)} data-testid="forgot-sso">
            Sign in with SSO
          </LoadingButton>
          <Link href="/login" className="inline-flex items-center justify-center gap-1 text-sm underline underline-offset-4">
            <ArrowLeft className="size-3" /> Back to sign in
          </Link>
        </div>
      </AuthFormWrapper>
    );
  if (sentTo)
    return (
      <AuthFormWrapper>
        <div className="flex flex-col gap-6" data-testid="forgot-sent">
          <AuthHeading icon={<Mail className="size-6" />} title="Check your email" description={`If ${sentTo} has an account, a reset link is on its way. It works once, for an hour.`} />
          {previewUrl && (
            <p className="rounded-md border bg-muted/40 p-3 text-center text-sm">
              Demo mailbox:{' '}
              <Link href={previewUrl} className="font-medium underline underline-offset-4" data-testid="reset-preview-link">
                open the reset link
              </Link>
            </p>
          )}
          <Link href="/login" className="inline-flex items-center justify-center gap-1 text-sm underline underline-offset-4">
            <ArrowLeft className="size-3" /> Back to sign in
          </Link>
        </div>
      </AuthFormWrapper>
    );
  return (
    <AuthFormWrapper>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) return setMissing('Enter your work email.');
          onSend(email.trim());
        }}
      >
        <div className="flex flex-col gap-6">
          <AuthHeading title="Reset your password" description="Enter your work email and we’ll send a link to choose a new one." />
          <FormField id="forgot-email" label="Work email" error={missing ?? undefined}>
            <Input id="forgot-email" type="email" autoFocus value={email} aria-invalid={!!missing} onChange={(e) => (setEmail(e.target.value), setMissing(null))} placeholder="e.g. name@harborpine.example" />
          </FormField>
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending} loadingText="Sending…" data-testid="forgot-send">
            Send reset link
          </LoadingButton>
          <Link href="/login" className="inline-flex items-center justify-center gap-1 text-sm underline underline-offset-4">
            <ArrowLeft className="size-3" /> Back to sign in
          </Link>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
