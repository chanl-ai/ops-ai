'use client';

import * as React from 'react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { ChoiceChecks } from '@/components/shared/setting/choice-cards';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { useViewerRole } from '@/lib/settings-preview-store';

import { CHANNELS } from '../../_sample/data';
import { mockSave } from '../../_sample/save';

const EVENTS = [
  { id: 'approvals', title: 'Approvals', description: 'A run is waiting for a person to approve it.', initial: ['app', 'email'] },
  { id: 'sla', title: 'SLA warnings', description: 'A review is about to pass its deadline.', initial: ['app'] },
  { id: 'alerts', title: 'Alerts', description: 'A run failed or a guardrail blocked an answer.', initial: ['app', 'slack'] },
];

/** Team › Notifications (S05, the team half): one card per event so each commits on its own. The personal half is My notifications. */
export default function TeamNotificationsPage() {
  const { can } = useViewerRole();
  const [value, setValue] = React.useState<Record<string, string[]>>(Object.fromEntries(EVENTS.map((e) => [e.id, e.initial])));
  return (
    <PreviewPageLayout title="Notifications" description="Where Operations hears about work that needs a person">
      {EVENTS.map((e) => (
        <SettingCard key={e.id} id={e.id} title={e.title} description={e.description} help="Approvals can be decided from Email and Slack as well; the same four-eyes rules apply." onSave={() => mockSave(e.title)} dirty={value[e.id].join() !== e.initial.join()} locked={!can('Admin')} requiredRole="Team admin">
          <ChoiceChecks name={e.id} label={e.title} choices={CHANNELS} value={value[e.id]} onChange={(v) => setValue({ ...value, [e.id]: v })} />
        </SettingCard>
      ))}
    </PreviewPageLayout>
  );
}
