'use client';

import * as React from 'react';
import { Globe, ShieldCheck } from 'lucide-react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { EgressHostForm } from '@/components/settings/preview/egress-host-form';
import { SecretForm } from '@/components/settings/preview/secret-form';
import { Combobox } from '@/components/shared/setting/pickers';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { Note } from '@/components/shared/setting/note';
import { PrefixedInput } from '@/components/shared/setting/prefixed-input';
import { SecretField } from '@/components/shared/setting/secret-field';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { SwitchRow } from '@/components/shared/setting/setting-row';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { Input } from '@/components/ui/input';
import { relativeTime } from '@/lib/format';
import { previewStore, usePreviewStore, useViewerRole } from '@/lib/settings-preview-store';

import { mockSave } from '../../_sample/save';

const PROVIDERS = [{ value: 'entra', label: 'Microsoft Entra ID' }, { value: 'okta', label: 'Okta' }, { value: 'saml', label: 'SAML 2.0' }];
const HOURS = ['1', '4', '8', '12', '24'].map((h) => ({ value: h, label: `${h} ${h === '1' ? 'hour' : 'hours'}` }));

/** Govern › Security (S07 to S11, S15 to S17): sign-in, egress and secrets; a Security admin changes them, others read. */
export default function SecurityPage() {
  const { can } = useViewerRole();
  const locked = !can('Security admin');
  const common = { locked, requiredRole: 'Security admin' } as const;
  const hosts = usePreviewStore((s) => s.hosts);
  const secrets = usePreviewStore((s) => s.secrets);
  const [methods, setMethods] = React.useState({ password: true, sso: true, google: false });
  const [provider, setProvider] = React.useState<string | null>('entra');
  const [hours, setHours] = React.useState<string | null>('12');
  const [mfa, setMfa] = React.useState(true);
  const [signup, setSignup] = React.useState(false);
  return (
    <PreviewPageLayout title="Security" description="Sign-in, which hosts tool calls may reach, and the credentials they send">
      <section id="sign-in" className="flex scroll-mt-20 flex-col gap-4">
        <h2 className="text-sm font-semibold">Sign-in</h2>
        <SettingCard title="Sign-in methods" description="What the sign-in screen offers." help="At least one stays on. Single sign-on needs a verified domain." onSave={() => mockSave('Sign-in methods')} {...common}>
          <div className="divide-y">
            <SwitchRow id="m-password" label="Email and password" effect="For people outside the SSO domains, such as contractors." defaultLabel="On" role="Security admin" canChange={!locked} checked={methods.password} onCheckedChange={(v) => setMethods({ ...methods, password: v })} />
            <SwitchRow id="m-sso" label="Single sign-on" effect="People on a verified domain are sent to the identity provider." defaultLabel="Off" role="Security admin" canChange={!locked} checked={methods.sso} onCheckedChange={(v) => setMethods({ ...methods, sso: v })} />
            <SwitchRow id="m-google" label="Google" effect="Google accounts on an allowed domain. Usually off at a bank." defaultLabel="Off" role="Security admin" canChange={!locked} checked={methods.google} onCheckedChange={(v) => setMethods({ ...methods, google: v })} />
          </div>
        </SettingCard>
        <SettingCard id="sso" title="SSO connection" description="The identity provider and its metadata." help="Test the connection after saving." onSave={() => mockSave('SSO connection')} {...common}>
          <div className="flex w-full flex-col gap-3">
            <Combobox options={PROVIDERS} value={provider} onChange={setProvider} noun="providers" />
            <PrefixedInput prefix="https://" defaultValue="login.harborpine.example/metadata" aria-label="Metadata address" />
          </div>
        </SettingCard>
        <section id="sso-domains" className="flex flex-col gap-2">
          <EntityRow name="harborpine.example" icon={<ShieldCheck className="size-4" />} meta="Sends people to Entra ID" trailing={<StatusDot status="ok" label="Verified" at={new Date(Date.now() - 86_400_000 * 3).toISOString()} />} actions={locked ? undefined : [{ label: 'Remove', onClick: () => mockSave('Remove'), destructive: true }]} />
          <EntityRow name="harborpine-contractors.com" icon={<ShieldCheck className="size-4" />} meta="Publish the TXT record, then verify" trailing={<StatusDot status="warn" label="Not verified" detail="The TXT record was not found." />} actions={locked ? undefined : [{ label: 'Verify', onClick: () => mockSave('Verify') }]} />
        </section>
        <SettingCard id="sign-in-security" title="Sessions and two-step" description="How long a session lasts and whether a second step is required." help="Applies at the next sign-in." onSave={() => mockSave('Sign-in security')} {...common}>
          <div className="divide-y">
            <SwitchRow id="mfa" label="Require two-step verification" effect="People without an authenticator are sent to set one up." defaultLabel="On" role="Security admin" canChange={!locked} checked={mfa} onCheckedChange={setMfa} />
            <div className="flex items-center justify-between gap-4 py-3">
              <div>
                <p className="text-sm font-medium">Session length</p>
                <p className="text-xs text-muted-foreground">Default: 12 hours · Changed by Security admin</p>
              </div>
              <div className="w-40"><Combobox options={HOURS} value={hours} onChange={setHours} noun="lengths" /></div>
            </div>
          </div>
        </SettingCard>
        <SettingCard id="signup" title="Self-signup" description="Let anyone on a verified domain create an account." help="Off means an admin invites everyone." onSave={() => mockSave('Self-signup')} {...common}>
          <SwitchRow id="signup-switch" label="Allow self-signup" effect="A new person lands in the default team as a Builder." defaultLabel="Off" role="Security admin" canChange={!locked} checked={signup} onCheckedChange={setSignup} />
        </SettingCard>
      </section>

      <section id="egress" className="flex scroll-mt-20 flex-col gap-3">
        <h2 className="text-sm font-semibold">Egress</h2>
        <div className="flex flex-col gap-2" data-testid="egress-hosts">
          {hosts.map((h) => (
            <EntityRow key={h.id} name={h.host} icon={<Globe className="size-4" />} meta={`${h.note || 'No note'} · added by ${h.addedBy} ${relativeTime(h.addedAt)}`} actions={locked ? undefined : [{ label: 'Remove', onClick: () => previewStore.removeHost(h.id), destructive: true }]} />
          ))}
        </div>
        <EgressHostForm shell="card" locked={locked} />
        <SettingCard id="egress-ranges" title="Private ranges" description="Address ranges inside the bank that tool calls may reach." help="Please use CIDR notation, one range per line." onSave={() => mockSave('Private ranges')} {...common}>
          <Input defaultValue="10.20.0.0/16" aria-label="Private range" className="w-full sm:w-1/2 bg-card font-mono text-sm" />
        </SettingCard>
      </section>

      <section id="secrets" className="flex scroll-mt-20 flex-col gap-3">
        <h2 className="text-sm font-semibold">Secrets</h2>
        <div className="flex flex-col gap-3" data-testid="secrets-list">
          {secrets.map((s) => (
            <SettingCard key={s.id} title={<code className="font-mono text-sm">{s.name}</code>} description={`Teams: ${s.teams.length ? s.teams.join(', ') : 'every team'}`} help="Used as {{NAME}} in a tool header." locked={locked} requiredRole="Security admin">
              <SecretField name={s.name} hint={s.hint} lastUsedAt={s.lastUsedAt} rotatedAt={s.rotatedAt} onRotate={async () => 'sk_live_new_91ab5c0e7d3f2486'} canRotate={!locked} />
            </SettingCard>
          ))}
        </div>
        <SecretForm shell="card" locked={locked} />
        <Note>Storage credentials are listed on Workspace › Storage, where they are changed.</Note>
      </section>
    </PreviewPageLayout>
  );
}
