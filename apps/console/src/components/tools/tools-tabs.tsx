'use client';

import { RouteTabs } from '@/components/shared/route-tabs';

/** The Tools page's own tabs: every tool one row each, the tool sets a team built, and every call they made. */
export function ToolsTabs() {
  return (
    <RouteTabs
      tabs={[
        { href: '/tools', label: 'All tools', testId: 'tools-tab-all' },
        { href: '/tools/custom', label: 'Custom tools', testId: 'tools-tab-custom' },
        { href: '/tools/calls', label: 'Logs', testId: 'tools-tab-logs' },
      ]}
    />
  );
}
