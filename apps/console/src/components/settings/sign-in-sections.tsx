'use client';

import * as React from 'react';
import { CheckCircle2, Plus, ShieldCheck, Trash2, XCircle } from 'lucide-react';

import { FileUpload, type UploadItem } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { relativeTime } from '@/lib/format';
import type { SignInPolicy, SignInPolicyPatch, SsoProvider } from '@/lib/types/sign-in';

export const SSO_PROVIDER_LABEL: Record<SsoProvider, string> = { entra: 'Microsoft Entra ID', okta: 'Okta', oidc: 'Generic OIDC', saml: 'SAML 2.0' };
const SESSION_OPTIONS = [1, 2, 4, 8, 10, 12, 24, 72, 168];
const hoursLabel = (h: number) => (h === 1 ? '1 hour' : h < 24 ? `${h} hours` : h === 24 ? '1 day' : `${h / 24} days`);

/** A switch row with its label and one-line explanation, for the methods and sign-up sections. */
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

/** Which sign-in options the login screen offers. At least one stays on; SSO needs a verified domain. */
export function SignInMethodsSection({ policy, saving, onSave }: { policy: SignInPolicy; saving: boolean; onSave: Save }) {
  const [m, setM] = React.useState(policy.methods);
  React.useEffect(() => {
    setM(policy.methods);
  }, [policy.methods]);
  const dirty = JSON.stringify(m) !== JSON.stringify(policy.methods);
  const noVerified = !policy.sso.domains.some((d) => d.verified);
  return (
    <SettingsSection title="Methods" description="What the sign-in screen offers. People on a verified SSO domain are sent to SSO whatever else is on.">
      <div className="flex flex-col gap-3" data-testid="sign-in-methods">
        <SwitchRow id="m-password" label="Email and password" hint="For people outside the SSO domains, such as contractors." checked={m.password} onChange={(v) => setM({ ...m, password: v })} />
        <SwitchRow id="m-sso" label="Single sign-on" hint={noVerified ? 'Verify a domain under SSO connection first.' : 'Through the identity provider below.'} checked={m.sso} disabled={noVerified && !m.sso} onChange={(v) => setM({ ...m, sso: v })} />
        <SwitchRow id="m-google" label="Google" hint="Google accounts on an allowed domain. Usually off at a bank." checked={m.google} onChange={(v) => setM({ ...m, google: v })} />
        <LoadingButton size="sm" className="self-start" isLoading={saving} disabled={!dirty} onClick={() => onSave({ section: 'methods', methods: m })} data-testid="save-methods">
          Save methods
        </LoadingButton>
      </div>
    </SettingsSection>
  );
}

/** The identity provider, its metadata, the domains it signs in for and a test sign-in. */
export function SignInSsoSection({
  policy,
  saving,
  onSave,
  onAddDomain,
  onVerifyDomain,
  onRemoveDomain,
  onTest,
  busyDomain,
  testing,
}: {
  policy: SignInPolicy;
  saving: boolean;
  onSave: Save;
  onAddDomain: (d: string) => Promise<unknown>;
  onVerifyDomain: (d: string) => void;
  onRemoveDomain: (d: string) => void;
  onTest: () => void;
  busyDomain: string | null;
  testing: boolean;
}) {
  const [provider, setProvider] = React.useState<SsoProvider>(policy.sso.provider);
  const [url, setUrl] = React.useState(policy.sso.metadataUrl);
  const [file, setFile] = React.useState<UploadItem | null>(null);
  const [domain, setDomain] = React.useState('');
  const [adding, setAdding] = React.useState(false);
  const [domainError, setDomainError] = React.useState<string>();
  React.useEffect(() => {
    setProvider(policy.sso.provider);
    setUrl(policy.sso.metadataUrl);
  }, [policy.sso.provider, policy.sso.metadataUrl]);
  const dirty = provider !== policy.sso.provider || url !== policy.sso.metadataUrl || (!!file?.fileId && file.fileId !== policy.sso.metadataFileId);
  const t = policy.sso.lastTest;

  const add = async () => {
    setDomainError(undefined);
    setAdding(true);
    try {
      await onAddDomain(domain);
      setDomain('');
    } catch (e) {
      setDomainError((e as Error).message);
    } finally {
      setAdding(false);
    }
  };

  return (
    <SettingsSection title="SSO connection" description="The identity provider people on the verified domains sign in with.">
      <div className="flex flex-col gap-4" data-testid="sign-in-sso">
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="sso-provider" label="Identity provider">
            <Select value={provider} onValueChange={(v) => setProvider(v as SsoProvider)}>
              <SelectTrigger id="sso-provider" className="w-full bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(SSO_PROVIDER_LABEL) as SsoProvider[]).map((p) => (
                  <SelectItem key={p} value={p}>
                    {SSO_PROVIDER_LABEL[p]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="sso-url" label="Metadata URL" hint="Or upload the metadata file below.">
            <Input id="sso-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="e.g. https://login.microsoftonline.com/…/federationmetadata.xml" className="bg-background font-mono text-xs" />
          </FormField>
        </div>
        <FormField id="sso-file" label="Metadata file" optional hint={policy.sso.metadataFileName ? `Current: ${policy.sso.metadataFileName}` : 'XML from the identity provider.'}>
          <FileUpload id="sso-file" purpose="idp_metadata" types={['.xml']} variant="compact" title="Upload metadata" onChange={(items) => setFile(items[0] ?? null)} />
        </FormField>
        <div className="flex flex-wrap items-center gap-2">
          <LoadingButton size="sm" isLoading={saving} disabled={!dirty} onClick={() => onSave({ section: 'sso', provider, metadataUrl: url, metadataFileId: file?.fileId ?? policy.sso.metadataFileId, metadataFileName: file?.name ?? policy.sso.metadataFileName })} data-testid="save-sso">
            Save connection
          </LoadingButton>
          <LoadingButton size="sm" variant="outline" isLoading={testing} onClick={onTest} data-testid="test-sso">
            <ShieldCheck className="size-4" /> Test connection
          </LoadingButton>
          {t && (
            <span className={`flex items-center gap-1.5 text-xs ${t.ok ? 'text-success-text' : 'text-destructive'}`} data-testid="sso-test-result">
              {t.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />} {t.message} · {relativeTime(t.at)}
            </span>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <Label>Verified domains</Label>
          <div className="rounded-md border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Domain</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>DNS TXT record</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {policy.sso.domains.length ? (
                  policy.sso.domains.map((d) => (
                    <TableRow key={d.domain} data-testid={`sso-domain-${d.domain}`}>
                      <TableCell className="font-mono text-sm">{d.domain}</TableCell>
                      <TableCell>{d.verified ? <Badge variant="secondary">Verified {d.verifiedAt ? relativeTime(d.verifiedAt) : ''}</Badge> : <Badge variant="outline">Unverified</Badge>}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{d.txtRecord}</TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          {!d.verified && (
                            <LoadingButton size="sm" variant="outline" isLoading={busyDomain === d.domain} onClick={() => onVerifyDomain(d.domain)} data-testid={`verify-${d.domain}`}>
                              Verify
                            </LoadingButton>
                          )}
                          <Button size="icon" variant="ghost" aria-label={`Remove ${d.domain}`} disabled={busyDomain === d.domain} onClick={() => onRemoveDomain(d.domain)}>
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={4} className="py-6 text-center text-sm text-muted-foreground">
                      No domains yet. Add the email domain your staff sign in with, publish the TXT record, then verify it.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-wrap items-start gap-2">
            <FormField id="sso-domain" label="Add a domain" error={domainError} className="min-w-64 flex-1">
              <Input id="sso-domain" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="e.g. northfield.ca" className="bg-background font-mono text-sm" aria-invalid={!!domainError} onKeyDown={(e) => e.key === 'Enter' && domain.trim() && add()} />
            </FormField>
            <LoadingButton size="sm" variant="outline" className="mt-6" isLoading={adding} disabled={!domain.trim()} onClick={add} data-testid="add-domain">
              <Plus className="size-4" /> Add domain
            </LoadingButton>
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}

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
            <TagInput id="s-domains" value={domains} onChange={setDomains} placeholder="e.g. northfieldbank.com" />
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
