'use client';

import * as React from 'react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { DangerCard } from '@/components/shared/setting/danger-card';
import { SourceBadge } from '@/components/shared/setting/inherit-switch';
import { Combobox } from '@/components/shared/setting/pickers';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { SwitchRow } from '@/components/shared/setting/setting-row';
import { Input } from '@/components/ui/input';
import { useViewerRole } from '@/lib/settings-preview-store';

import { mockSave } from '../_sample/save';

const OWNERS = [
  { value: 'ops', label: 'Operations leads' },
  { value: 'platform', label: 'Platform admins' },
];

/** Team › General (new): the team's name and owner, and which workspace settings the team has overridden. */
export default function TeamGeneralPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const [name, setName] = React.useState('Operations');
  const [owner, setOwner] = React.useState<string | null>('ops');
  const [model, setModel] = React.useState(false);
  return (
    <PreviewPageLayout title="Operations" description="The team's name, owner and overrides">
      <SettingCard id="name" title="Team name" description="Shown in the team switcher and on everything the team owns." help="Please use 32 characters at maximum." onSave={() => mockSave('Team name')} dirty={name !== 'Operations'} locked={!admin} requiredRole="Admin">
        <Input value={name} maxLength={32} onChange={(e) => setName(e.target.value)} aria-label="Team name" className="w-full sm:w-1/2 bg-card" />
      </SettingCard>
      <SettingCard id="owner" title="Owner" description="The group that answers for what this team runs." onSave={() => mockSave('Owner')} dirty={owner !== 'ops'} locked={!admin} requiredRole="Admin">
        <div className="w-full sm:w-1/2">
          <Combobox options={OWNERS} value={owner} onChange={setOwner} noun="groups" />
        </div>
      </SettingCard>
      <SettingCard id="overrides" title="Overrides" description="Workspace settings this team may change for itself." help={<span className="flex items-center gap-2">The workspace allows this. <SourceBadge level={model ? 'Team' : 'Workspace'} /></span>}>
        <SwitchRow id="team-model" label="Use its own default model" effect="New agents in this team start with the team's alias instead of the workspace's." defaultLabel="Off" role="Admin" canChange={admin} checked={model} onCheckedChange={(v) => (setModel(v), mockSave('Override'))} />
      </SettingCard>
      <div className="flex flex-col gap-4 pt-4">
        <h2 className="text-sm font-semibold text-destructive">Danger zone</h2>
        <DangerCard title="Leave team" description="You lose access to what this team owns." precondition="Ensure at least one more Admin is in the team." action="Leave team" confirmName="Operations" onConfirm={() => mockSave('Leave')} />
        <DangerCard title="Delete team" description="Deletes the team and hands its agents and workflows to the workspace owner." precondition="Ensure nothing in the team is published." action="Delete team" confirmName="Operations" onConfirm={() => mockSave('Delete')} blockedReason="3 workflows are published. Retire them first." />
      </div>
    </PreviewPageLayout>
  );
}
