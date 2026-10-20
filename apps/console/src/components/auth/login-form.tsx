'use client';

import * as React from 'react';
import Link from 'next/link';
import { KeyRound } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { AuthError, AuthFormWrapper, AuthHeading } from './auth-form-wrapper';

/**
 * Email and password, with SSO and Google as the workspace allows. Typing an email on a verified SSO domain turns
 * the form into "Continue with SSO", so people on those domains never see a password field they cannot use.
 * Every call goes through props, never an identity SDK.
 */
export function LoginForm({
  methods,
  ssoDomainOf,
  ssoLabel,
  selfSignup,
  initialEmail = '',
  demo = null,
  pending,
  error,
  onPassword,
  onSso,
  onGoogle,
  onEmailChange,
}: {
  methods: { password: boolean; sso: boolean; google: boolean };
  /** The verified SSO domain for an email, or undefined. */
  ssoDomainOf: (email: string) => string | undefined;
  /** The workspace's identity provider by name, when the sign-in service gives one. */
  ssoLabel?: string;
  selfSignup: boolean;
  initialEmail?: string;
  /** A one-click demo sign-in; only the mock adapter supplies one. */
  demo?: { name: string; email: string; password: string } | null;
  pending: 'password' | 'sso' | 'google' | null;
  error: string | null;
  onPassword: (email: string, password: string) => void;
  onSso: (email: string) => void;
  onGoogle: () => void;
  /** Called as the email changes, so the page can ask how that email signs in. */
  onEmailChange?: (email: string) => void;
}) {
  const [email, setEmail] = React.useState(initialEmail);
  const [password, setPassword] = React.useState('');
  const [missing, setMissing] = React.useState<{ email?: string; password?: string }>({});
  const ssoDomain = methods.sso ? ssoDomainOf(email) : undefined;
  const ssoMode = !!ssoDomain || !methods.password;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const m = { email: /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) ? undefined : 'Enter your work email.', password: ssoMode || password ? undefined : 'Enter your password.' };
    setMissing(m);
    if (m.email || m.password) return;
    if (ssoMode) onSso(email.trim());
    else onPassword(email.trim(), password);
  };

  return (
    <AuthFormWrapper>
      <form onSubmit={submit} noValidate data-testid="login-form" data-mode={ssoMode ? 'sso' : 'password'}>
        <div className="flex flex-col gap-6">
          <AuthHeading title="Welcome back" description="Sign in to Northfield Ops AI" />
          <FormField id="email" label="Work email" error={missing.email}>
            <Input id="email" type="email" autoComplete="username" autoFocus value={email} aria-invalid={!!missing.email} onChange={(e) => (setEmail(e.target.value), setMissing({}), onEmailChange?.(e.target.value))} placeholder="e.g. name@northfieldbank.com" />
          </FormField>
          {ssoMode ? (
            <p className="flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-sm" data-testid="login-sso-notice">
              <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              {ssoDomain ? `${ssoDomain} signs in through ${ssoLabel ?? 'your company’s identity provider'}.` : `This workspace signs in through ${ssoLabel ?? 'your company’s identity provider'}.`}
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center">
                <label htmlFor="password" className="text-sm font-medium">
                  Password
                </label>
                <Link href="/forgot-password" className="ml-auto text-sm underline-offset-2 hover:underline">
                  Forgot your password?
                </Link>
              </div>
              <Input id="password" type="password" autoComplete="current-password" value={password} aria-invalid={!!missing.password} onChange={(e) => (setPassword(e.target.value), setMissing({}))} />
              {missing.password && <p className="text-xs text-destructive">{missing.password}</p>}
            </div>
          )}
          <AuthError message={error} />
          <LoadingButton type="submit" className="w-full" isLoading={pending === (ssoMode ? 'sso' : 'password')} loadingText={ssoMode ? 'Opening your sign-in…' : 'Signing in…'} data-testid="login-submit">
            {ssoMode ? 'Continue with SSO' : 'Sign in'}
          </LoadingButton>
          {demo && (
            <Button type="button" variant="secondary" className="w-full" onClick={() => onPassword(demo.email, demo.password)} data-testid="login-demo">
              Sign in as {demo.name} (demo)
            </Button>
          )}
          {(methods.sso && !ssoMode) || methods.google ? (
            <>
              <div className="relative text-center text-sm after:absolute after:inset-0 after:top-1/2 after:z-0 after:flex after:items-center after:border-t after:border-border">
                <span className="relative z-10 bg-card px-2 text-muted-foreground">Or continue with</span>
              </div>
              <div className="flex flex-col gap-2">
                {methods.sso && !ssoMode && (
                  <Button variant="outline" type="button" className="w-full" asChild>
                    <Link href={email ? `/sso?email=${encodeURIComponent(email.trim())}` : '/sso'} data-testid="login-continue-sso">
                      <KeyRound className="size-4" /> Continue with SSO
                    </Link>
                  </Button>
                )}
                {methods.google && (
                  <LoadingButton variant="outline" type="button" className="w-full" isLoading={pending === 'google'} onClick={onGoogle}>
                    Continue with Google
                  </LoadingButton>
                )}
              </div>
            </>
          ) : null}
          <p className="text-center text-sm text-muted-foreground">
            {selfSignup ? (
              <>
                New here?{' '}
                <Link href="/signup" className="underline underline-offset-4">
                  Create an account
                </Link>
              </>
            ) : (
              'New to Northfield Ops AI? Ask your workspace admin for an invite.'
            )}
          </p>
        </div>
      </form>
    </AuthFormWrapper>
  );
}
