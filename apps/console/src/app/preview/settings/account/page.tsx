'use client';

import * as React from 'react';
import { Laptop, Smartphone } from 'lucide-react';
import { toast } from 'sonner';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { SwitchRow } from '@/components/shared/setting/setting-row';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

import { mockSave } from '../_sample/save';

/**
 * My account (avatar menu): profile, security and my notifications. Profile and password commit with a Save; the
 * notification switches are personal and reversible, so they save the moment they change and say "Saved".
 */
export default function AccountPage() {
  const [name, setName] = React.useState('James Richardson');
  const [mute, setMute] = React.useState(false);
  const [digest, setDigest] = React.useState(true);
  const auto = (set: (v: boolean) => void, what: string) => (v: boolean) => (set(v), toast.success('Saved', { description: `${what}. Design mock: nothing was stored.` }));
  return (
    <PreviewPageLayout title="My account" description="Your profile, how you sign in, and the notifications that are only yours">
      <SettingCard id="profile" title="Name" description="Your name as reviewers and the audit log show it." help="Please use 2 to 60 characters." onSave={() => mockSave('Name')} dirty={name !== 'James Richardson'}>
        <Input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" className="w-full sm:w-1/2 bg-card" />
      </SettingCard>
      <SettingCard id="password" title="Password" description="Confirm your current password first. The new one works from your next sign-in." help="Please use at least 12 characters." onSave={() => mockSave('Password')}>
        <div className="flex w-full flex-col sm:w-1/2 gap-3">
          <Input type="password" placeholder="Current password" aria-label="Current password" className="bg-card" autoComplete="current-password" />
          <Input type="password" placeholder="New password" aria-label="New password" className="bg-card" autoComplete="new-password" />
        </div>
      </SettingCard>
      <section id="two-step" className="flex scroll-mt-20 flex-col gap-2">
        <h2 className="text-sm font-semibold">Two-step verification</h2>
        <EntityRow name="Authenticator app · iPhone" icon={<Smartphone className="size-4" />} meta="Added 3 months ago" actions={[{ label: 'Regenerate recovery codes', onClick: () => mockSave('Recovery codes') }, { label: 'Remove', onClick: () => mockSave('Remove'), destructive: true }]} />
      </section>
      <section id="sessions" className="flex scroll-mt-20 flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Where you are signed in</h2>
          <Button variant="outline" size="sm" onClick={() => mockSave('Sign out')}>
            Sign out everywhere else
          </Button>
        </div>
        <EntityRow name="MacBook · Chrome" icon={<Laptop className="size-4" />} meta="This device · Toronto" />
        <EntityRow name="Branch workstation 14 · Edge" icon={<Laptop className="size-4" />} meta="Yesterday · Mississauga" actions={[{ label: 'Sign out', onClick: () => mockSave('Sign out'), destructive: true }]} />
      </section>
      <SettingCard id="my-notifications" title="My notifications" description="Only you see these. They save as you change them." help="Team routing is set by a team admin under Team › Notifications.">
        <div className="divide-y">
          <SwitchRow id="mute" label="Mute while I'm away" effect="Nothing reaches you until you turn it off; the team's routing still applies to others." defaultLabel="Off" role="Self" checked={mute} onCheckedChange={auto(setMute, 'Mute')} />
          <SwitchRow id="digest" label="Morning digest" effect="One email at 07:30 with what is waiting for you." defaultLabel="On" role="Self" checked={digest} onCheckedChange={auto(setDigest, 'Digest')} />
        </div>
      </SettingCard>
    </PreviewPageLayout>
  );
}
