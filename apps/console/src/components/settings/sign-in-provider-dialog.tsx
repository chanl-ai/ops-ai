'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { CopyField } from '@/components/shared/setting/copy-field';
import { TagInput } from '@/components/shared/tag-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/contract';
import type { JitRole, SignInProvider, SignInProviderInput, SignInProviderKind } from '@/lib/types/sign-in';

export const KIND_LABEL: Record<SignInProviderKind, string> = { oidc: 'OpenID Connect', saml: 'SAML 2.0', password: 'Email and password' };
export const ROLE_LABEL: Record<JitRole, string> = { chat_user: 'Chat user', viewer: 'Viewer', builder: 'Builder', approver: 'Approver' };
const NONE = '__none';
const DEFAULT_TEAM = '__default';
const DOMAIN = /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

type Field = 'label' | 'issuer' | 'clientId' | 'secret' | 'entity' | 'ssoUrl' | 'certificate' | 'domains' | 'jit' | 'form';
type Errors = Partial<Record<Field, string>>;

/** Which field a server refusal is about, by its code, so the reason shows where it can be fixed. */
const FIELD_OF: Record<string, Field> = { sp_key_missing: 'form', secret_missing: 'secret', certificate: 'certificate', domain_taken: 'domains', domains_not_allowed: 'domains', jit_role: 'jit', jit_not_allowed: 'jit', not_found: 'jit' };

interface Form {
  kind: SignInProviderKind;
  label: string;
  enabled: boolean;
  issuer: string;
  clientId: string;
  secret: string;
  entity: string;
  ssoUrl: string;
  certificate: string;
  emailAttribute: string;
  signRequests: boolean;
  requireEncryption: boolean;
  domains: string[];
  role: JitRole | typeof NONE;
  team: string;
}

const formOf = (p?: SignInProvider | null): Form => ({
  kind: p?.kind ?? 'oidc',
  label: p?.label ?? '',
  enabled: p?.enabled ?? true,
  issuer: p?.oidc?.issuer ?? '',
  clientId: p?.oidc?.clientId ?? '',
  secret: p?.oidc?.clientSecretRef ?? NONE,
  entity: p?.saml?.idpEntityId ?? '',
  ssoUrl: p?.saml?.ssoUrl ?? '',
  certificate: p?.saml?.certificate ?? '',
  emailAttribute: p?.saml?.emailAttribute ?? '',
  signRequests: p?.saml?.signRequests ?? false,
  requireEncryption: p?.saml?.requireEncryption ?? false,
  domains: p?.domains ?? [],
  role: p?.jit?.role ?? NONE,
  team: p?.jit?.team ?? DEFAULT_TEAM,
});

/**
 * Adds or edits a sign-in provider. The fields are platform-service's own (an OIDC issuer and client, or a SAML entity,
 * sign-in URL and certificate), the client secret is picked by name, and a group map set through the API is sent back
 * unchanged. A refusal shows the server's words under the field it is about.
 */
export function SignInProviderDialog({
  open,
  onOpenChange,
  provider,
  teams,
  secretNames,
  metadataUrl,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  provider?: SignInProvider | null;
  teams: { id: string; name: string }[];
  secretNames: string[];
  /** Where the bank's identity provider reads this installation's SAML metadata. */
  metadataUrl?: string;
  pending: boolean;
  onSubmit: (input: SignInProviderInput) => Promise<unknown>;
}) {
  const [f, setF] = React.useState<Form>(formOf(provider));
  const [errors, setErrors] = React.useState<Errors>({});
  React.useEffect(() => {
    if (!open) return;
    setF(formOf(provider));
    setErrors({});
  }, [open, provider]);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => (setF((x) => ({ ...x, [k]: v })), setErrors({}));
  const sso = f.kind !== 'password';

  const submit = async () => {
    const found: Errors = {
      label: f.label.trim() ? undefined : 'Name the provider as people will see it on the sign-in page.',
      issuer: f.kind === 'oidc' && !/^https?:\/\//.test(f.issuer.trim()) ? 'Give the issuer URL, e.g. https://login.bank.com.' : undefined,
      clientId: f.kind === 'oidc' && !f.clientId.trim() ? 'Give the client ID the identity provider issued.' : undefined,
      entity: f.kind === 'saml' && !f.entity.trim() ? 'Give the identity provider’s entity ID.' : undefined,
      ssoUrl: f.kind === 'saml' && !/^https?:\/\//.test(f.ssoUrl.trim()) ? 'Give the sign-in URL, starting with https://.' : undefined,
      certificate: f.kind === 'saml' && !f.certificate.includes('BEGIN CERTIFICATE') ? 'Paste the signing certificate in PEM form.' : undefined,
      domains: f.domains.find((d) => !DOMAIN.test(d)) ? `${f.domains.find((d) => !DOMAIN.test(d))} is not a domain.` : undefined,
    };
    if (Object.values(found).some(Boolean)) return setErrors(found);
    const input: SignInProviderInput = {
      kind: f.kind,
      label: f.label.trim(),
      enabled: f.enabled,
      domains: sso ? f.domains : [],
      ...(f.kind === 'oidc' ? { oidc: { issuer: f.issuer.trim(), clientId: f.clientId.trim(), clientSecretRef: f.secret === NONE ? null : f.secret, scopes: provider?.oidc?.scopes ?? null } } : {}),
      ...(f.kind === 'saml'
        ? {
            saml: {
              idpEntityId: f.entity.trim(),
              ssoUrl: f.ssoUrl.trim(),
              certificate: f.certificate.trim(),
              emailAttribute: f.emailAttribute.trim() || null,
              nameAttribute: provider?.saml?.nameAttribute ?? null,
              signRequests: f.signRequests,
              requireEncryption: f.requireEncryption,
            },
          }
        : {}),
      ...(sso && f.role !== NONE ? { jit: { role: f.role, team: f.team === DEFAULT_TEAM ? null : f.team } } : {}),
      ...(sso && provider?.groups ? { groups: provider.groups } : {}),
    };
    try {
      await onSubmit(input);
      onOpenChange(false);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : undefined;
      setErrors({ [(code && FIELD_OF[code]) || 'form']: (e as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !pending && onOpenChange(o)}
      size="lg"
      title={provider ? `Edit ${provider.label}` : 'Add sign-in provider'}
      description="Changes apply at the next sign-in and are recorded in the audit log. A new domain signs nobody in until it is verified."
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive" data-testid="provider-form-error">
            {errors.form ?? ''}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending} loadingText="Saving…" data-testid="provider-submit">
              {provider ? 'Save provider' : 'Add provider'}
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4" data-testid="provider-form">
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="provider-kind" label="Type" hint={provider ? 'Fixed once saved.' : undefined}>
            <Select value={f.kind} onValueChange={(v) => set('kind', v as SignInProviderKind)} disabled={!!provider}>
              <SelectTrigger id="provider-kind" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(KIND_LABEL) as SignInProviderKind[]).map((k) => (
                  <SelectItem key={k} value={k}>
                    {KIND_LABEL[k]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="provider-label" label="Name" error={errors.label} hint="Shown on the sign-in page.">
            <Input id="provider-label" value={f.label} maxLength={200} aria-invalid={!!errors.label} onChange={(e) => set('label', e.target.value)} placeholder="e.g. Northfield SSO" />
          </FormField>
        </div>
        <div className="flex items-start gap-3">
          <Switch id="provider-enabled" checked={f.enabled} onCheckedChange={(v) => set('enabled', v)} className="mt-0.5" />
          <Label htmlFor="provider-enabled" className="flex flex-col items-start gap-0.5 font-normal">
            <span className="font-medium">On</span>
            <span className="text-xs text-muted-foreground">{sso ? 'People on its verified domains sign in here.' : 'Anyone without a company sign-in uses a password.'}</span>
          </Label>
        </div>

        {f.kind === 'oidc' && (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="provider-issuer" label="Issuer URL" error={errors.issuer} className="sm:col-span-2">
              <Input id="provider-issuer" value={f.issuer} aria-invalid={!!errors.issuer} onChange={(e) => set('issuer', e.target.value)} placeholder="https://login.bank.com" />
            </FormField>
            <FormField id="provider-client" label="Client ID" error={errors.clientId}>
              <Input id="provider-client" value={f.clientId} aria-invalid={!!errors.clientId} onChange={(e) => set('clientId', e.target.value)} />
            </FormField>
            <FormField id="provider-secret" label="Client secret" error={errors.secret} hint="Set by your operator; pick its name.">
              <Select value={f.secret} onValueChange={(v) => set('secret', v)}>
                <SelectTrigger id="provider-secret" className="w-full" aria-invalid={!!errors.secret}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>None (public client)</SelectItem>
                  {[...new Set([...secretNames, ...(provider?.oidc?.clientSecretRef ? [provider.oidc.clientSecretRef] : [])])].map((n) => (
                    <SelectItem key={n} value={n}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
        )}

        {f.kind === 'saml' && (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="provider-entity" label="Identity provider entity ID" error={errors.entity}>
              <Input id="provider-entity" value={f.entity} aria-invalid={!!errors.entity} onChange={(e) => set('entity', e.target.value)} />
            </FormField>
            <FormField id="provider-sso-url" label="Sign-in URL" error={errors.ssoUrl}>
              <Input id="provider-sso-url" value={f.ssoUrl} aria-invalid={!!errors.ssoUrl} onChange={(e) => set('ssoUrl', e.target.value)} placeholder="https://login.bank.com/saml/sso" />
            </FormField>
            <FormField id="provider-certificate" label="Signing certificate" error={errors.certificate} hint="PEM, from the identity provider’s metadata." className="sm:col-span-2">
              <Textarea id="provider-certificate" value={f.certificate} rows={5} className="font-mono text-xs" aria-invalid={!!errors.certificate} onChange={(e) => set('certificate', e.target.value)} placeholder="-----BEGIN CERTIFICATE-----" />
            </FormField>
            <FormField id="provider-email-attr" label="Email attribute" optional hint="When the email is not the NameID.">
              <Input id="provider-email-attr" value={f.emailAttribute} onChange={(e) => set('emailAttribute', e.target.value)} />
            </FormField>
            <div className="flex flex-col gap-3 sm:col-span-2">
              <div className="flex items-start gap-3">
                <Switch id="provider-sign-requests" checked={f.signRequests} onCheckedChange={(v) => set('signRequests', v)} className="mt-0.5" />
                <Label htmlFor="provider-sign-requests" className="flex flex-col items-start gap-0.5 font-normal">
                  <span className="font-medium">Sign requests</span>
                  <span className="text-xs text-muted-foreground">For an identity provider that checks who is asking.</span>
                </Label>
              </div>
              <div className="flex items-start gap-3">
                <Switch id="provider-require-encryption" checked={f.requireEncryption} onCheckedChange={(v) => set('requireEncryption', v)} className="mt-0.5" />
                <Label htmlFor="provider-require-encryption" className="flex flex-col items-start gap-0.5 font-normal">
                  <span className="font-medium">Require encrypted assertions</span>
                  <span className="text-xs text-muted-foreground">Refuse a sign-in the identity provider did not encrypt to this installation.</span>
                </Label>
              </div>
            </div>
            {metadataUrl && (
              <FormField id="provider-metadata" label="Metadata for your identity provider" hint="Give this URL to the bank's identity team; it holds the certificate for signed requests and encryption." className="sm:col-span-2">
                <CopyField id="provider-metadata" value={metadataUrl} label="SAML metadata URL" />
              </FormField>
            )}
          </div>
        )}

        {sso && (
          <>
            <FormField id="provider-domains" label="Email domains" error={errors.domains} hint="Each is verified by a DNS TXT record before it sends anyone here. Press Enter after each.">
              <TagInput id="provider-domains" value={f.domains} invalid={!!errors.domains} onChange={(v) => set('domains', v.map((d) => d.toLowerCase()))} placeholder="e.g. northfield.ca" />
            </FormField>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField id="provider-role" label="New people join as" error={errors.jit} hint="Someone new to the workspace gets an account on their first sign-in.">
                <Select value={f.role} onValueChange={(v) => set('role', v as Form['role'])}>
                  <SelectTrigger id="provider-role" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NONE}>Nobody new (invited people only)</SelectItem>
                    {(Object.keys(ROLE_LABEL) as JitRole[]).map((r) => (
                      <SelectItem key={r} value={r}>
                        {ROLE_LABEL[r]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="provider-team" label="In team">
                <Select value={f.team} onValueChange={(v) => set('team', v)} disabled={f.role === NONE}>
                  <SelectTrigger id="provider-team" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DEFAULT_TEAM}>The workspace’s default team</SelectItem>
                    {[...teams, ...(f.team !== DEFAULT_TEAM && !teams.some((t) => t.id === f.team) ? [{ id: f.team, name: f.team }] : [])].map((t) => (
                      <SelectItem key={t.id} value={t.id}>
                        {t.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            </div>
            {provider?.groups?.map.length ? <p className="text-xs text-muted-foreground">{provider.groups.map.length} group mappings set through the API are kept as they are.</p> : null}
          </>
        )}
      </div>
    </DialogShell>
  );
}
