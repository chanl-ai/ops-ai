'use client';

import * as React from 'react';
import { HardDrive } from 'lucide-react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { Combobox } from '@/components/shared/setting/pickers';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Input } from '@/components/ui/input';
import { useViewerRole } from '@/lib/settings-preview-store';
import { relativeTime } from '@/lib/format';

import { STORAGE_PURPOSES } from '../../_sample/data';
import { mockSave } from '../../_sample/save';

const TARGETS = [
  { value: 'primary', label: 'Primary bucket', hint: 'ca-central-1' },
  { value: 'archive', label: 'Archive bucket', hint: 'ca-central-1' },
];

/** Workspace › Storage (S18 to S22): changed by a Security admin only; everyone else reads the values and sees the lock. */
export default function StoragePage() {
  const { can } = useViewerRole();
  const locked = !can('Security admin');
  const [limit, setLimit] = React.useState('25');
  const [minutes, setMinutes] = React.useState('15');
  const [retention, setRetention] = React.useState('standard');
  const [targets, setTargets] = React.useState<Record<string, string | null>>(Object.fromEntries(STORAGE_PURPOSES.map((p) => [p, 'primary'])));
  const common = { locked, requiredRole: 'Security admin' } as const;
  return (
    <PreviewPageLayout title="Storage" description="Where files are kept, how large they may be and how long they stay">
      <section id="credentials" className="flex flex-col gap-2 scroll-mt-20">
        <h2 className="text-sm font-semibold">Storage credentials</h2>
        <EntityRow name="STORAGE_PRIMARY" icon={<HardDrive className="size-4" />} meta={`Access key · set by Sam Adeyemi ${relativeTime(new Date(Date.now() - 86_400_000 * 9).toISOString())}`} actions={locked ? undefined : [{ label: 'Rotate', onClick: () => mockSave('Rotation') }]} />
        <p className="text-xs text-muted-foreground">Also listed on Govern › Security › Secrets, where it can be read; it is changed here.</p>
      </section>
      <SettingCard id="targets" title="Where each kind of file goes" description="Each purpose writes to one bucket." help="Files already stored stay where they are." onSave={() => mockSave('Targets')} {...common}>
        <div className="grid gap-3 sm:grid-cols-2">
          {STORAGE_PURPOSES.map((p) => (
            <div key={p} className="flex flex-col gap-1.5">
              <span className="text-xs text-muted-foreground">{p}</span>
              <Combobox options={TARGETS} value={targets[p]} onChange={(v) => setTargets({ ...targets, [p]: v })} noun="buckets" />
            </div>
          ))}
        </div>
      </SettingCard>
      <SettingCard id="limits" title="Upload limit" description="The largest file a person can upload, in megabytes." help="Please use a number from 1 to 100." onSave={() => mockSave('Upload limit')} dirty={limit !== '25'} {...common}>
        <Input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(e.target.value)} aria-label="Upload limit in megabytes" className="max-w-32 bg-card" />
      </SettingCard>
      <SettingCard id="retention" title="Retention" description="How long a file is kept after the last time it was used." help="Files under a legal hold are never deleted." onSave={() => mockSave('Retention')} dirty={retention !== 'standard'} {...common}>
        <ChoiceCards name="retention" label="Retention" value={retention} onChange={setRetention} choices={[{ value: 'short', title: '90 days', description: 'Chat uploads and temporary exports.' }, { value: 'standard', title: '7 years', description: 'Records the bank must keep.' }]} />
      </SettingCard>
      <SettingCard id="links" title="Download link lifetime" description="How long a signed link to a file works." help="Links already sent keep their old lifetime." onSave={() => mockSave('Link lifetime')} dirty={minutes !== '15'} {...common}>
        <Input type="number" min={1} max={1440} value={minutes} onChange={(e) => setMinutes(e.target.value)} aria-label="Signed link lifetime in minutes" className="max-w-32 bg-card" />
      </SettingCard>
    </PreviewPageLayout>
  );
}
