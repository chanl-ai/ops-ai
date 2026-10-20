'use client';

import type { ReactNode } from 'react';
import { Settings } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { SampleDataGate, SampleDataNote } from '@/components/shared/sample-data';

/**
 * Settings shell: the page header carries the section's name, one line about it and its actions; the settings sidebar
 * (components/settings/settings-sidebar.tsx) is the navigation. `sample`: nothing stores this page yet, so it says so
 * and its controls (header actions included) are off.
 */
export function SettingsPageLayout({ section, description, actions, sample, children }: { section?: string; description?: string; actions?: ReactNode; sample?: boolean; children: ReactNode }) {
  return (
    <PageLayout
      icon={Settings}
      title={section ?? 'Settings'}
      description={description ?? 'Members, notifications, integrations and usage for the current team'}
      actions={actions && sample ? <SampleDataGate>{actions}</SampleDataGate> : actions}
    >
      <div className="flex min-w-0 flex-col gap-4">
        {sample ? (
          <>
            <SampleDataNote />
            <SampleDataGate>{children}</SampleDataGate>
          </>
        ) : (
          children
        )}
      </div>
    </PageLayout>
  );
}
