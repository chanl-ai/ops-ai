'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** Profile, Security and Memory are the account's pages; the account is not a sidebar item, so they switch here. */
export function AccountTabs() {
  return <RouteTabs tabs={[{ href: '/settings/account', label: 'Profile' }, { href: '/settings/account/security', label: 'Security' }, { href: '/settings/account/memory', label: 'Memory' }]} />;
}
