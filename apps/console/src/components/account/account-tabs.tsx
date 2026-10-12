'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** Profile and Security are the account's two pages; the account is not a sidebar item, so they switch here. */
export function AccountTabs() {
  return <RouteTabs tabs={[{ href: '/account', label: 'Profile' }, { href: '/account/security', label: 'Security' }]} />;
}
