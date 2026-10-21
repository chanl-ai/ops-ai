'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { SignInPolicy, SignInPolicyPatch, SsoProvider } from '@/lib/types/sign-in';

export const SSO_PROVIDER_LABEL: Record<SsoProvider, string> = { entra: 'Microsoft Entra ID', okta: 'Okta', oidc: 'Generic OIDC', saml: 'SAML 2.0' };
const SESSION_OPTIONS = [1, 2, 4, 8, 10, 12, 24, 72, 168];
const hoursLabel = (h: number) => (h === 1 ? '1 hour' : h < 24 ? `${h} hours` : h === 24 ? '1 day' : `${h / 24} days`);

/** A switch row with its label and one-line explanation, for the sign-up section. */
function SwitchRow({ id, label, hint, checked, onChange, disabled }: { id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} className="mt-0.5" />
      <Label htmlFor={id} className="flex flex-col items-start gap-0.5 font-normal">
        <span className="font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </Label>
    </div>
  );
}

type Save = (patch: SignInPolicyPatch) => Promise<unknown>;

/** MFA, how long a session lasts and which email domains may be invited. */
export function SignInSecuritySection({ policy, saving, onSave }: { policy: SignInPolicy; saving: boolean; onSave: Save }) {
  const [mfa, setMfa] = React.useState(policy.mfaRequired);
  const [hours, setHours] = React.useState(policy.sessionHours);
  const [domains, setDomains] = React.useState(policy.allowedDomains);
  React.useEffect(() => {
    setMfa(policy.mfaRequired);
    setHours(policy.sessionHours);
    setDomains(policy.allowedDomains);
  }, [policy.mfaRequired, policy.sessionHours, policy.allowedDomains]);
  const dirty = mfa !== policy.mfaRequired || hours !== policy.sessionHours || domains.join() !== policy.allowedDomains.join();
  return (
    <SettingsSection title="Security" description="Applies at the next sign-in. People already signed in keep their session until it ends.">
      <div className="flex flex-col gap-4" data-testid="sign-in-security">
        <SwitchRow id="s-mfa" label="Require two-step verification" hint="Password sign-ins ask for an authenticator code. New people set one up on first sign-in." checked={mfa} onChange={setMfa} />
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="s-hours" label="Session length" hint="Signed out after this long without activity.">
            <Select value={String(hours)} onValueChange={(v) => setHours(Number(v))}>
              <SelectTrigger id="s-hours" className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[...new Set([...SESSION_OPTIONS, hours])].sort((a, b) => a - b).map((h) => (
                  <SelectItem key={h} value={String(h)}>
                    {hoursLabel(h)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="s-domains" label="Allowed email domains" hint="Invites to other domains are refused. Empty allows any.">
            <TagInput id="s-domains" value={domains} onChange={setDomains} placeholder="e.g. harborpine.example" />
          </FormField>
        </div>
        <LoadingButton size="sm" className="self-start" isLoading={saving} disabled={!dirty} onClick={() => onSave({ section: 'security', mfaRequired: mfa, sessionHours: hours, allowedDomains: domains })} data-testid="save-security">
          Save security
        </LoadingButton>
      </div>
    </SettingsSection>
  );
}

/** Whether anyone on an allowed domain can create an account without an invite. Off at a bank. */
export function SignInSignupSection({ policy, saving, onSave }: { policy: SignInPolicy; saving: boolean; onSave: Save }) {
  const [on, setOn] = React.useState(policy.selfSignup);
  React.useEffect(() => {
    setOn(policy.selfSignup);
  }, [policy.selfSignup]);
  return (
    <SettingsSection title="Self-signup" description="People join by invitation from Members. Turning this on lets anyone on an allowed domain create an account.">
      <div className="flex flex-col gap-3">
        <SwitchRow id="s-signup" label="Allow self-signup" hint={on ? 'Anyone on an allowed domain can create an account and lands in no team.' : 'Off: only invited people can join.'} checked={on} onChange={setOn} />
        <LoadingButton size="sm" className="self-start" isLoading={saving} disabled={on === policy.selfSignup} onClick={() => onSave({ section: 'signup', selfSignup: on })} data-testid="save-signup">
          Save
        </LoadingButton>
      </div>
    </SettingsSection>
  );
}
