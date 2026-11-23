'use client';

import { RouteTabs } from '@/components/shared/route-tabs';
import { useCan } from '@/hooks/me-queries';

/**
 * The Apps area's two pages: the apps the team turned on, and the people who signed in to them. People needs
 * permission to manage the team's apps, so nobody else is offered the tab.
 */
export function AppsTabs() {
  const mayManage = useCan('connections', 'manage') === true;
  return (
    <RouteTabs
      tabs={[
        { href: '/data/connectors', label: 'Apps', testId: 'apps-tab-apps' },
        ...(mayManage ? [{ href: '/data/connectors/people', label: 'People', testId: 'apps-tab-people' }] : []),
      ]}
    />
  );
}
