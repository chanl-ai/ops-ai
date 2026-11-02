'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/**
 * The Apps menu's tabs (owner, 11-01: the menu is Apps): the catalog, the apps a person connected as themselves,
 * the tools those apps bring with every call they made, and Credentials: the OAuth apps and secret values they use.
 */
export function AppsTabs() {
  return (
    <RouteTabs
      tabs={[
        { href: '/integrations', label: 'Apps', testId: 'apps-tab-apps' },
        { href: '/integrations/credentials', label: 'Credentials', testId: 'apps-tab-credentials' },
        { href: '/integrations/my-accounts', label: 'My accounts', testId: 'apps-tab-mine' },
        { href: '/tools', label: 'Tools', testId: 'apps-tab-tools' },
      ]}
    />
  );
}
