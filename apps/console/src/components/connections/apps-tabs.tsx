'use client';

import { RouteTabs } from '@/components/shared/route-tabs';
import { useCan } from '@/hooks/me-queries';

/**
 * The Apps area's two pages: the apps the team turned on, and the people who signed in to them. People needs
 * permission to manage the team's apps, so nobody else is offered the tabs.
 */
export function AppsTabs() {
  const mayManage = useCan('connections', 'manage') === true;
  // One tab is no choice: a person who may not see People gets no tab row at all.
  if (!mayManage) return null;
  return (
    <RouteTabs
      tabs={[
        { href: '/data/connectors', label: 'Apps', testId: 'apps-tab-apps' },
        { href: '/data/connectors/people', label: 'People', testId: 'apps-tab-people' },
      ]}
    />
  );
}
